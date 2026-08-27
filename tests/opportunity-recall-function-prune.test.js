// stage-1 召回的「跨职能扩展词」剪枝契约。
//
// 病因（2026-08-27 实测）：召回方向层的 tsquery 是把用户每个词过一遍词库扩展后全 OR 起来，
// 而 stage-2 的方向门（eligibility.computeMatchFacts）还要再过一道**职能门**——岗位职能判得出
// 且不在用户目标职能集里就直接拒。两者不一致的后果是：某真实校招产品画像召回 1,216 个候选，
// 其中 1,053 个被方向门拒掉，**光「研发」职能就 724 个**——用户要的是产品岗，而召回把整个
// 研发词库（工程师/engineer/后端/java/架构…）都拉了进来，白占候选名额、白烧 JS 打分。
//
// 修法：扩展产出里，职能判得出且不在用户目标职能集内的词，不进召回 tsquery。
// **用户自己写的原词一律保留**（他写「工程师」就是要搜工程师）。
//
// ⚠️ 为什么这是安全的：判据与 stage-2 的职能门用的是**同一个** userTargetFunctions +
// classifyJobFunction，所以被剪掉的词本来就召不回能过门的岗。唯一的缝是「职能判不出(其他)」
// 的岗——职能门放行它们，而它们可能只匹配到被剪的词。实测 33 个真实画像里 11 个有可剪的词，
// 展示岗位数没有一个画像下降（详见 docs/superpowers/specs/2026-08-27-observability-and-ux-plan.md）。
const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { buildRecallSql } = loadTs(path.join(__dirname, "..", "lib", "jobs-store", "opportunities.ts"));
const { buildTsquery } = loadTs(path.join(__dirname, "..", "lib", "job-search.ts"));

const baseProfile = {
  userId: "u1",
  jobScope: "domestic",
  targetRegions: [],
  targetRoles: [],
  targetKeywords: [],
  excludeKeywords: [],
  targetLocations: [],
  targetCompanies: [],
  targetIndustries: [],
  skills: [],
  experienceStage: "",
  seniority: null,
  highestEducation: null,
  dailyLimit: 20,
};
const mk = (over) => ({ ...baseProfile, ...over });
const SINCE = "2026-08-20T00:00:00.000Z";

// buildTsquery 单词会多包一层括号（`((a & b))`），多词是 `((a & b) | (c))`；
// 剥掉最外层才是可用于子串比对的单词子句。
const clauseFor = (term) => buildTsquery([term], []).slice(1, -1);

/** 取出方向层那条 tsquery（含用户原词的那个 string 参数）。 */
function roleTsqueryOf(built, anchorTerm) {
  const anchor = clauseFor(anchorTerm);
  const found = built.params.find((p) => typeof p === "string" && p.includes(anchor));
  assert.ok(found, `方向 tsquery 里必须能找到用户原词 ${anchorTerm}`);
  return found;
}

test("跨职能的扩展词不进召回 tsquery（产品画像不该把研发词库拉进来）", () => {
  // 「Prompt Engineering」的词库组落在「研发」职能，会展开出 工程师/engineer/研发/developer
  const built = buildRecallSql(
    mk({ targetRoles: ["产品经理"], targetKeywords: ["Prompt Engineering"] }),
    SINCE,
    900,
  );
  const roleTs = roleTsqueryOf(built, "产品经理");
  for (const dropped of ["工程师", "engineer", "研发", "developer"]) {
    assert.ok(
      !roleTs.includes(clauseFor(dropped)),
      `「${dropped}」属于研发职能、用户目标职能是产品，不该进召回 tsquery`,
    );
  }
});

test("用户自己写的原词一律保留，哪怕它属于别的职能", () => {
  // 原词就是「Prompt Engineering」（研发职能）：用户明确写了，必须留
  const built = buildRecallSql(
    mk({ targetRoles: ["产品经理"], targetKeywords: ["Prompt Engineering"] }),
    SINCE,
    900,
  );
  const roleTs = roleTsqueryOf(built, "产品经理");
  assert.ok(
    roleTs.includes(clauseFor("Prompt Engineering")),
    "用户原词 Prompt Engineering 被剪掉了——原词永远不能剪",
  );
});

test("同职能与判不出职能的扩展词照常保留（别剪过头）", () => {
  const built = buildRecallSql(
    mk({ targetRoles: ["产品经理"], targetKeywords: ["Prompt Engineering"] }),
    SINCE,
    900,
  );
  const roleTs = roleTsqueryOf(built, "产品经理");
  // 同职能（产品）
  assert.ok(roleTs.includes(clauseFor("pm")), "同职能扩展词 pm 不该被剪");
  // 职能判不出（其他）——职能门会放行这类岗，所以词也要留
  assert.ok(roleTs.includes(clauseFor("产品")), "职能判不出的扩展词 产品 不该被剪");
});

test("用户没填 targetRoles（判不出目标职能）时一个词都不剪", () => {
  // userTargetFunctions 只看 targetRoles；集合为空 = 无从判断，此时必须保持原样不剪
  const built = buildRecallSql(mk({ targetKeywords: ["Prompt Engineering"] }), SINCE, 900);
  const roleTs = roleTsqueryOf(built, "Prompt Engineering");
  for (const kept of ["工程师", "engineer", "研发"]) {
    assert.ok(roleTs.includes(clauseFor(kept)), `没有目标职能可依据时不该剪掉「${kept}」`);
  }
});

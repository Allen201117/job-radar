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

test("用户自己写的原词一律保留：方向词全部来自 targetRoles，天然在目标职能集内", () => {
  // 这条原来的语料是「roles=产品经理 + keywords=Prompt Engineering」，考的是「用户手写的跨职能
  // 原词不能被职能剪枝剪掉」。2026-09-02 起召回方向词**只取 targetRoles**，而目标职能集
  // （userTargetFunctions）恰恰就是从 targetRoles 推出来的 —— 于是「原词落在目标职能集外」
  // 这个情形在结构上不再可能发生，剪枝只可能剪到词库**展开**出来的跨职能词。
  // 这里把它钉成结构性事实：用户写的每个方向词，都必须原样出现在召回 tsquery 里。
  const roles = ["产品经理", "Prompt Engineering", "水泥搅拌"];
  const built = buildRecallSql(mk({ targetRoles: roles }), SINCE, 900);
  const roleTs = roleTsqueryOf(built, "产品经理");
  for (const raw of ["产品经理", "prompt", "水泥搅拌"]) {
    assert.ok(
      roleTs.includes(clauseFor(raw)) || roleTs.includes(clauseFor(raw).toLowerCase()),
      `用户原词「${raw}」被剪掉了——原词永远不能剪`,
    );
  }
});

test("填了目标岗位时，targetKeywords 不进召回（到方向门也必被 role_mismatch 拒）", () => {
  // 与 lib/opportunities/eligibility.ts:165/238 对齐：有 targetRoles 时方向判定只认 targetRoles，
  // 匹配不上就 reject("role_mismatch")。所以只靠关键词召回来的岗一个都展示不出来，
  // 留在 stage-1 只是白扫 GIN、白占召回预算（实测某产品画像 1,216 个候选里 1,053 个如此）。
  const built = buildRecallSql(
    mk({ targetRoles: ["产品经理"], targetKeywords: ["水泥搅拌"] }),
    SINCE,
    900,
  );
  const roleTs = roleTsqueryOf(built, "产品经理");
  assert.ok(
    !roleTs.includes(clauseFor("水泥搅拌")),
    "填了目标岗位时 targetKeywords 不该进召回方向层",
  );
});

test("没填目标岗位时才回退 targetKeywords（否则这类用户一个岗都召不回）", () => {
  const built = buildRecallSql(mk({ targetKeywords: ["水泥搅拌"] }), SINCE, 900);
  const roleTs = roleTsqueryOf(built, "水泥搅拌");
  assert.ok(roleTs.includes(clauseFor("水泥搅拌")), "没有目标岗位时必须回退用关键词召回");
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
  // 锚点用扩展词而非原词整串：方向 tsquery 现在是 AND-of-ORs（见 roleTsquery 注释），
  // 「Prompt Engineering」被拆成 `(工程师|engineer|…) & (prompt)`，整串不再字面出现。
  // 剪枝契约看的是「哪些词在」，不是「以什么结构在」——逐词断言即可。
  const roleTs = roleTsqueryOf(built, "engineer");
  for (const kept of ["工程师", "engineer", "研发"]) {
    assert.ok(roleTs.includes(clauseFor(kept)), `没有目标职能可依据时不该剪掉「${kept}」`);
  }
  assert.ok(roleTs.includes(clauseFor("prompt")), "残差单元 prompt 必须在，否则原词意图丢失");
});

test("方向 tsquery 是 AND-of-ORs：泛词不能单独召回岗位", () => {
  // 本轮召回改造的核心契约。旧实现把词库扩展拍平成一个大 OR，「前端开发工程师」里的「工程师」
  // 单独就能命中 → 库里 82,738 个泛工程师岗把 1,800 的召回预算吃干净，真前端岗（1,225 个）
  // 只有 24 个进得了候选池。AND 结构让泛词只能做限定、不能单独召回。
  const built = buildRecallSql(mk({ targetRoles: ["前端开发工程师"] }), SINCE, 900);
  const roleTs = roleTsqueryOf(built, "前端");
  assert.match(roleTs, /&/, "方向 tsquery 必须含 AND 连接符，否则又退回泛词全 OR");
  assert.ok(roleTs.includes(clauseFor("工程师")), "泛词仍参与，但只作为 AND 的一侧");
});

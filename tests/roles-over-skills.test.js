// 「岗位方向 > 技能」的口径护栏（2026-09-02 立）。
//
// 由来：简历解析本来分得清（prompt 明写 target_roles 只输出岗位方向、不要输出技能），但
// 写进偏好那一步做了 `target_keywords = skills`，把「会什么」贴成了「要搜什么」。真实后果：
//   · /jobs 的默认筛选词被填成技能词「用户旅程」→ 全库 39 万在招岗没有一个标题带它 → 恒 0 结果；
//   · /today 召回被技能词稀释，某产品画像 1,216 个候选里 1,053 个到方向门才被拒（白扫白算）。
//
// 三条不变量，任何一条被推翻上面的事故就会复发：
//   ① 简历解析产出的技能进 skills，绝不进 target_keywords（后者归用户手填）；
//   ② 填了目标岗位时召回词只用目标岗位；没填才回退关键词（与 eligibility.ts:165 同一行判据）；
//   ③ 技能仍进画像、只用于打分加分，不参与方向判定。
const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("node:path");

const { loadTs } = require("./_load-ts");
const { buildPreferencesFromResumeProfile } = require("../lib/resume-parser.js");

const ROOT = path.join(__dirname, "..");
const { buildRecallSql } = loadTs(path.join(ROOT, "lib", "jobs-store", "opportunities.ts"));
const { buildRadarProfile } = loadTs(path.join(ROOT, "lib", "opportunities", "profile.ts"));

const SINCE = "2026-08-20T00:00:00.000Z";

/** 召回 SQL 的全部字符串参数（方向 / 公司 / 城市几层 tsquery 都在里面）。 */
function allTsqueryParams(built) {
  return (built?.params || []).filter((p) => typeof p === "string");
}

test("① 简历解析的技能进 skills，不进 target_keywords", () => {
  const prefs = buildPreferencesFromResumeProfile({
    target_locations: ["上海"],
    target_roles: ["产品经理"],
    skills: ["SQL", "Figma", "用户旅程"],
    industries: [],
  });
  assert.deepEqual(prefs.skills, ["SQL", "Figma", "用户旅程"]);
  assert.ok(
    !("target_keywords" in prefs),
    "简历解析不得再产出 target_keywords —— 那是用户在偏好页手填的补充搜索词",
  );
});

test("② 填了目标岗位 → 召回只用岗位，技能/概念词不进召回", () => {
  const profile = buildRadarProfile(
    "u1",
    {
      target_roles: ["产品经理"],
      target_keywords: ["用户旅程"],
      skills: ["SQL"],
      target_locations: ["上海"],
      target_companies: [],
      exclude_keywords: [],
      job_scope: "domestic",
    },
    null,
  );
  const built = buildRecallSql(profile, SINCE, 900, []);
  assert.ok(built, "有目标岗位时应能构造召回 SQL");
  const joined = allTsqueryParams(built).join(" ");
  assert.ok(/产品/.test(joined), `召回里必须有目标岗位「产品经理」：${joined}`);
  assert.ok(!/旅程/.test(joined), `技能/概念词不得进召回：${joined}`);
});

test("② 没填目标岗位 → 回退用关键词，否则这类用户一个岗都召不回", () => {
  const profile = buildRadarProfile(
    "u2",
    {
      target_roles: [],
      target_keywords: ["用户旅程"],
      skills: [],
      target_locations: ["上海"],
      target_companies: [],
      exclude_keywords: [],
      job_scope: "domestic",
    },
    null,
  );
  const built = buildRecallSql(profile, SINCE, 900, []);
  assert.ok(built, "没有目标岗位但有关键词时仍应能构造召回 SQL");
  assert.ok(
    /旅程/.test(allTsqueryParams(built).join(" ")),
    "没填目标岗位时必须回退关键词",
  );
});

test("③ 技能仍进画像（供打分加分），但不参与方向判定", () => {
  const profile = buildRadarProfile(
    "u3",
    {
      target_roles: ["产品经理"],
      target_keywords: ["Prompt Engineering"],
      skills: ["SQL", "Python"],
      target_locations: ["上海"],
      target_companies: [],
      exclude_keywords: [],
      job_scope: "domestic",
    },
    null,
  );
  // 与 lib/opportunities/eligibility.ts:165 同一行判据：有 roles 就只认 roles。
  const directionQueries =
    profile.targetRoles.length > 0 ? profile.targetRoles : profile.targetKeywords;
  assert.deepEqual(directionQueries, ["产品经理"]);
  assert.ok(
    profile.skills.includes("SQL") && profile.skills.includes("Python"),
    "技能必须留在画像里，打分要用",
  );
});

test("③ 偏好列里的技能也能进画像（老账号只有 candidate_profiles.skills 时同样兜得住）", () => {
  const fromPrefs = buildRadarProfile(
    "u4",
    { target_roles: ["产品经理"], target_keywords: [], skills: ["Figma"], target_locations: [], target_companies: [], exclude_keywords: [], job_scope: "domestic" },
    null,
  );
  assert.ok(fromPrefs.skills.includes("Figma"), "偏好列 skills 应并入画像");

  const fromCandidate = buildRadarProfile(
    "u5",
    { target_roles: ["产品经理"], target_keywords: [], target_locations: [], target_companies: [], exclude_keywords: [], job_scope: "domestic" },
    { skills: ["Axure"], target_roles: [], target_locations: [], industries: [] },
  );
  assert.ok(fromCandidate.skills.includes("Axure"), "简历档案 skills 应并入画像");
});

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const Module = require("node:module");

function loadModule(rel) {
  const sourcePath = path.join(__dirname, "..", "lib", "opportunities", rel);
  const source = fs.readFileSync(sourcePath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
  const mod = { exports: {} };
  const scopedRequire = Module.createRequire(sourcePath);
  const fn = new Function("exports", "require", "module", "__filename", "__dirname", compiled);
  fn(mod.exports, scopedRequire, mod, sourcePath, path.dirname(sourcePath));
  return mod.exports;
}

const { buildRadarProfile, isProfileReady, profileReadiness } = loadModule("profile.ts");

function prefs(over = {}) {
  return {
    id: "p",
    user_id: "u",
    target_locations: [],
    target_roles: [],
    target_keywords: [],
    exclude_keywords: [],
    target_companies: [],
    target_industries: [],
    daily_limit: 20,
    ...over,
  };
}
function cand(over = {}) {
  return {
    user_id: "u",
    resume_id: null,
    headline: null,
    target_roles: [],
    target_locations: [],
    skills: [],
    industries: [],
    seniority: null,
    experience_stage: null,
    education: [],
    experience: [],
    education_summary: null,
    experience_summary: null,
    raw_profile: {},
    created_at: "",
    updated_at: "",
    ...over,
  };
}

test("手工偏好优先于简历：roles/locations 用偏好", () => {
  const p = buildRadarProfile(
    "u",
    prefs({ target_roles: ["产品经理"], target_locations: ["上海"] }),
    cand({ target_roles: ["数据分析"], target_locations: ["北京"] })
  );
  assert.deepEqual(p.targetRoles, ["产品经理"]);
  assert.deepEqual(p.targetLocations, ["上海"]);
});

test("偏好缺失时用简历兜底 roles/locations", () => {
  const p = buildRadarProfile(
    "u",
    prefs({ target_roles: [], target_locations: [] }),
    cand({ target_roles: ["数据分析"], target_locations: ["北京"] })
  );
  assert.deepEqual(p.targetRoles, ["数据分析"]);
  assert.deepEqual(p.targetLocations, ["北京"]);
});

test("简历补 skills（偏好无此字段）", () => {
  const p = buildRadarProfile("u", prefs(), cand({ skills: ["Python", "SQL"] }));
  assert.deepEqual(p.skills, ["Python", "SQL"]);
});

test("target industries 合并（偏好 ∪ 简历）", () => {
  const p = buildRadarProfile(
    "u",
    prefs({ target_industries: ["互联网"] }),
    cand({ industries: ["金融", "互联网"] })
  );
  assert.deepEqual([...p.targetIndustries].sort(), ["互联网", "金融"].sort());
});

test("最高学历从简历 education/summary 推导（取最高档）", () => {
  assert.equal(
    buildRadarProfile("u", prefs(), cand({ education_summary: "硕士 清华大学" })).highestEducation,
    "硕士"
  );
  assert.equal(
    buildRadarProfile("u", prefs(), cand({ education: ["本科 复旦", "博士研究生 北大"] })).highestEducation,
    "博士"
  );
  assert.equal(buildRadarProfile("u", prefs(), cand({})).highestEducation, null);
});

test("daily_limit clamp 到 5–30", () => {
  assert.equal(buildRadarProfile("u", prefs({ daily_limit: 100 }), null).dailyLimit, 30);
  assert.equal(buildRadarProfile("u", prefs({ daily_limit: 2 }), null).dailyLimit, 5);
  assert.equal(buildRadarProfile("u", prefs({ daily_limit: 20 }), null).dailyLimit, 20);
  assert.equal(buildRadarProfile("u", null, null).dailyLimit, 20);
});

test("数组大小写不敏感去重，保留首次出现", () => {
  const p = buildRadarProfile("u", prefs({ target_keywords: ["AI", "ai", "AI", " 数据 ", "数据"] }), null);
  assert.deepEqual(p.targetKeywords, ["AI", "数据"]);
});

test("profile_ready = content(roles|keywords|companies) AND location", () => {
  assert.equal(isProfileReady(buildRadarProfile("u", prefs({ target_roles: ["x"], target_locations: ["上海"] }), null)), true);
  // 仅 target_companies 也算 content signal
  assert.equal(isProfileReady(buildRadarProfile("u", prefs({ target_companies: ["字节"], target_locations: ["上海"] }), null)), true);
  assert.equal(isProfileReady(buildRadarProfile("u", prefs({ target_roles: ["x"] }), null)), false); // 缺城市
  assert.equal(isProfileReady(buildRadarProfile("u", prefs({ target_locations: ["上海"] }), null)), false); // 缺 content
});

test("profileReadiness 暴露缺失维度", () => {
  const r = profileReadiness(buildRadarProfile("u", prefs({ target_locations: ["上海"] }), null));
  assert.equal(r.ready, false);
  assert.equal(r.missingContent, true);
  assert.equal(r.missingLocation, false);
});

test("null 偏好 + 历史 null 字段不崩", () => {
  const p = buildRadarProfile("u", null, null);
  assert.deepEqual(p.targetRoles, []);
  assert.deepEqual(p.skills, []);
  assert.equal(p.experienceStage, "");
  assert.equal(p.highestEducation, null);
  assert.equal(p.dailyLimit, 20);
});

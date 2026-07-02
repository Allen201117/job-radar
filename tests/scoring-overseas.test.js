const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const Module = require("node:module");

function loadScoringModule() {
  const sourcePath = path.join(__dirname, "..", "lib", "scoring.ts");
  const source = fs.readFileSync(sourcePath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
  const module = { exports: {} };
  const scopedRequire = Module.createRequire(sourcePath);
  const fn = new Function("exports", "require", "module", "__filename", "__dirname", compiled);
  fn(module.exports, scopedRequire, module, sourcePath, path.dirname(sourcePath));
  return module.exports;
}

const { scoreJob } = loadScoringModule();

test("scoring uses city aliases for overseas location matches", () => {
  const result = scoreJob(
    makeJob({ id: "sg-data", title: "Data Engineer", location: "Singapore", job_scope: "overseas" }),
    makePreferences({ target_locations: ["新加坡"], target_roles: [], target_keywords: [] }),
    [],
  );

  assert.equal(result.location_matched, true);
  assert.ok(result.match_reasons.some((r) => r.type === "location" && r.value === "新加坡"));
  assert.equal(result.score, 20);
});

test("scoring uses en profile fields and overseas lexicon only for overseas scope", () => {
  const job = makeJob({
    id: "server-side",
    title: "Server-side Engineer",
    location: "Seattle, WA",
    job_scope: "overseas",
    summary: "",
  });
  const prefs = makePreferences({
    job_scope: "overseas",
    target_roles: [],
    target_keywords: [],
    target_locations: [],
    en_target_roles: ["后端"],
    en_target_keywords: ["分布式系统"],
  });

  const result = scoreJob(job, prefs, []);
  assert.equal(result.content_matched, true);
  assert.ok(result.match_reasons.some((r) => r.type === "role" && r.value === "后端"));
  assert.equal(result.score, 30);
});

test("scoring keeps domestic scope from using en profile fields", () => {
  const result = scoreJob(
    makeJob({ id: "domestic-server-side", title: "Server-side Engineer", job_scope: "overseas" }),
    makePreferences({
      job_scope: "domestic",
      target_roles: [],
      target_keywords: [],
      target_locations: [],
      en_target_roles: ["后端"],
    }),
    [],
  );

  assert.equal(result.content_matched, false);
  assert.equal(result.score, 0);
  assert.deepEqual(result.match_reasons, []);
});

function makeJob(overrides = {}) {
  return {
    id: "job-1",
    source_id: null,
    company: "测试公司",
    title: "Data Engineer",
    location: "上海",
    country_code: null,
    job_scope: "domestic",
    job_type: "社招",
    summary: "Python SQL data platform",
    jd_url: "https://example.com/jobs/1",
    apply_url: "https://example.com/jobs/1",
    salary_text: null,
    posted_at: null,
    experience: null,
    education: null,
    deadline: null,
    first_seen_at: "2026-05-25T00:00:00.000Z",
    last_seen_at: "2026-05-25T00:00:00.000Z",
    status: "active",
    content_hash: null,
    created_at: "2026-05-25T00:00:00.000Z",
    ...overrides,
  };
}

function makePreferences(overrides = {}) {
  return {
    id: "prefs-1",
    user_id: "user-1",
    job_scope: "domestic",
    target_regions: [],
    target_locations: ["上海"],
    target_roles: ["数据分析"],
    target_keywords: ["Python"],
    exclude_keywords: [],
    target_companies: [],
    target_industries: [],
    daily_limit: 20,
    en_target_roles: [],
    en_skills: [],
    en_target_keywords: [],
    has_en_resume: false,
    ...overrides,
  };
}

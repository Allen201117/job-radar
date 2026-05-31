const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

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
  const fn = new Function("exports", "require", "module", "__filename", "__dirname", compiled);
  fn(module.exports, require, module, sourcePath, path.dirname(sourcePath));
  return module.exports;
}

const { sortAndFilterJobs } = loadScoringModule();

test("applies job actions only to the matching job id", () => {
  const jobs = [
    makeJob("job-1", "数据分析实习生"),
    makeJob("job-2", "产品经理校招生"),
  ];
  const actions = [
    {
      id: "action-1",
      user_id: "user-1",
      job_id: "job-2",
      action: "ignored",
      note: null,
      created_at: "2026-05-25T00:00:00.000Z",
    },
  ];

  const scored = sortAndFilterJobs(jobs, makePreferences(), actions, {
    showIgnored: true,
  });

  assert.equal(scored.find((job) => job.id === "job-1").user_action, null);
  assert.equal(scored.find((job) => job.id === "job-1").hidden_reason, null);
  assert.equal(scored.find((job) => job.id === "job-2").user_action, "ignored");
  assert.equal(scored.find((job) => job.id === "job-2").hidden_reason, "ignored");
});

function makeJob(id, title) {
  return {
    id,
    source_id: null,
    company: "测试公司",
    title,
    location: "上海",
    job_type: "实习",
    summary: "Python SQL 数据分析",
    jd_url: `https://example.com/jobs/${id}`,
    apply_url: `https://example.com/jobs/${id}`,
    salary_text: null,
    posted_at: null,
    first_seen_at: "2026-05-25T00:00:00.000Z",
    last_seen_at: "2026-05-25T00:00:00.000Z",
    status: "active",
    content_hash: null,
    created_at: "2026-05-25T00:00:00.000Z",
  };
}

function makePreferences() {
  return {
    id: "prefs-1",
    user_id: "user-1",
    target_locations: ["上海"],
    target_roles: ["数据分析", "产品经理"],
    target_keywords: ["Python", "SQL"],
    exclude_keywords: [],
    target_companies: [],
    daily_limit: 20,
  };
}

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
  // scoring.ts 现在有运行时依赖（import { keywordMatchTier } from "./china-keyword-expansion"）；
  // 用 createRequire 绑定到源文件位置，让相对 require 从 lib/ 解析，而非测试文件所在的 tests/。
  const scopedRequire = Module.createRequire(sourcePath);
  const fn = new Function("exports", "require", "module", "__filename", "__dirname", compiled);
  fn(module.exports, scopedRequire, module, sourcePath, path.dirname(sourcePath));
  return module.exports;
}

const { sortAndFilterJobs, scoreJob, matchTier } = loadScoringModule();

test("matchTier classifies a score into three tiers at the 40/15 boundaries", () => {
  // high tier: score >= 40
  assert.equal(matchTier(82).level, "high");
  assert.equal(matchTier(40).level, "high");
  assert.equal(matchTier(40).label, "高匹配");

  // related tier: 15 <= score < 40
  assert.equal(matchTier(39).level, "related");
  assert.equal(matchTier(15).level, "related");
  assert.equal(matchTier(15).label, "相关");

  // none tier: score < 15 → no badge (label null)
  assert.equal(matchTier(14).level, "none");
  assert.equal(matchTier(14).label, null);
  assert.equal(matchTier(0).level, "none");
  assert.equal(matchTier(-50).level, "none");
});

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

test("scores a cross-language role hit: Chinese preference role matches English title", () => {
  const jobs = [makeJob("job-en", "Product Manager")];
  // 只留 target_roles，清空其余项，把分数隔离到「角色命中」这一项，便于断言。
  const prefs = {
    ...makePreferences(),
    target_roles: ["产品经理"],
    target_keywords: [],
    target_locations: [],
    target_companies: [],
    exclude_keywords: [],
  };

  const [scored] = sortAndFilterJobs(jobs, prefs, []);

  // 旧的裸 includes：'product manager'.includes('产品经理') === false → 0 分、召不回；
  // 新口径走 keywordMatchTier 跨语言召回 → 命中 +30 并记录该 role。
  assert.equal(scored.match_score, 30);
  assert.ok(scored.matched_keywords.includes("产品经理"));
});

test("exclude_keywords hit hard-filters the job regardless of showIgnored/showApplied", () => {
  const jobs = [
    makeJob("job-keep", "数据分析师"),
    makeJob("job-drop", "数据分析师 外包"),
  ];
  const prefs = {
    ...makePreferences(),
    target_keywords: [],
    exclude_keywords: ["外包"],
  };

  // scoreJob：命中 exclude 的岗位 hidden_reason 标 "excluded"（不再是 score -= 50）。
  assert.equal(scoreJob(jobs[1], prefs, []).hidden_reason, "excluded");
  assert.equal(scoreJob(jobs[0], prefs, []).hidden_reason, null);

  // sortAndFilterJobs：默认剔除 excluded。
  const shown = sortAndFilterJobs(jobs, prefs, []);
  assert.ok(shown.some((job) => job.id === "job-keep"));
  assert.ok(!shown.some((job) => job.id === "job-drop"));

  // 即便 showIgnored / showApplied 全开，excluded 依然被硬过滤（与 ignored 不同，不受开关影响）。
  const forced = sortAndFilterJobs(jobs, prefs, [], {
    showIgnored: true,
    showApplied: true,
  });
  assert.ok(!forced.some((job) => job.id === "job-drop"));
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

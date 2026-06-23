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

test("returns structured match reasons without changing the existing score", () => {
  const job = {
    ...makeJob("job-reasons", "Product Manager", "上海", "负责用户研究与产品规划"),
    company: "字节跳动",
    first_seen_at: new Date(Date.now() - 3 * 86400000).toISOString(),
  };
  const prefs = {
    ...makePreferences(),
    target_roles: ["产品经理"],
    target_locations: ["上海"],
    target_companies: ["字节跳动"],
    target_keywords: ["用户研究"],
    exclude_keywords: [],
  };

  const result = scoreJob(job, prefs, []);

  assert.equal(result.score, 80);
  assert.deepEqual(result.match_reasons, [
    { type: "role", value: "产品经理" },
    { type: "location", value: "上海" },
    { type: "company", value: "字节跳动" },
    { type: "keyword", value: "用户研究" },
    { type: "freshness", value: "近 7 天新增" },
  ]);

  const [scored] = sortAndFilterJobs([job], prefs, []);
  assert.equal(scored.match_score, 80);
  assert.deepEqual(scored.match_reasons, result.match_reasons);
});

test("returns no structured reasons when preferences or matches are absent", () => {
  const job = makeJob("job-no-reasons", "行政专员", "北京", "负责行政事务");
  const emptyPrefs = {
    ...makePreferences(),
    target_roles: [],
    target_locations: [],
    target_companies: [],
    target_keywords: [],
    exclude_keywords: [],
  };

  assert.deepEqual(scoreJob(job, null, []).match_reasons, []);
  assert.deepEqual(scoreJob(job, emptyPrefs, []).match_reasons, []);
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

test("岗位职能门（硬门）：产品经理用户不被推研发/数据岗（用户实锤）", () => {
  // 用户=产品经理（target_roles 判出职能=产品）。蔚来「AI Agent算法评测工程师」=研发、
  // B站「数据科学家」=数据 → 即便共享 AI/数据/SQL/Python 关键词，也不应算「命中目标方向」。
  const prefs = {
    ...makePreferences(),
    target_roles: ["AI 数据产品经理", "AI Agent"], // AI 数据产品经理→产品；AI Agent→其他不计 → 目标职能={产品}
    target_keywords: ["SQL", "Python", "数据埋点"],
    target_locations: [],
    target_companies: [],
    target_industries: [],
  };

  const engineer = makeJob("nio-eng", "AI Agent算法评测工程师", "上海", "自动化评测Pipeline，LLM-as-a-Judge，SQL Python");
  const dataSci = {
    ...makeJob("bili-ds", "商业化-数据科学家（AI Agent 开发方向）", "上海", "Agent 能力开发，SQL，Python，数据埋点"),
    job_type: "产品运营类", // B站把数据科学家挂产品运营部门下——不得据此误判产品
  };
  const pm = makeJob("real-pm", "AI 数据产品经理", "上海", "负责 AI 数据产品规划，SQL Python");

  const eng = scoreJob(engineer, prefs, []);
  const ds = scoreJob(dataSci, prefs, []);
  const product = scoreJob(pm, prefs, []);

  assert.ok(!eng.match_reasons.some((r) => r.type === "role" || r.type === "keyword"), "研发岗不应有 role/技能命中");
  assert.equal(eng.content_matched, false, "研发岗职能不符 → 内容不命中");
  assert.ok(!ds.match_reasons.some((r) => r.type === "role" || r.type === "keyword"), "数据科学家(挂产品运营类)不应命中");
  assert.equal(ds.content_matched, false, "数据岗职能不符 → 内容不命中");
  // 真·产品岗：职能=产品 ∈ 用户职能 → 正常命中（证明门只拦跨职能、不误伤本职能）。
  assert.ok(product.match_reasons.some((r) => r.type === "role"), "真产品岗应命中 role");
  assert.equal(product.content_matched, true);

  // Today 看板相关性门：研发/数据岗被过滤出榜，只留产品岗。
  const shown = sortAndFilterJobs([engineer, dataSci, pm], prefs, [], { requireRelevance: true });
  assert.deepEqual(shown.map((j) => j.id), ["real-pm"], "看板只留产品岗");
});

test("岗位职能门保守放行：用户无可判职能 / 岗位职能判不出 → 不误杀", () => {
  const eng = makeJob("eng2", "AI Agent工程师", "上海", ""); // 研发岗，精确命中 role「AI Agent」
  // (a) 用户 roles 全是纯领域词（AI Agent→其他，判不出职能）→ 不设职能门，研发岗也放行。
  const prefs1 = { ...makePreferences(), target_roles: ["AI Agent"], target_keywords: [], target_industries: [] };
  assert.ok(scoreJob(eng, prefs1, []).match_reasons.some((r) => r.type === "role"), "用户无可判职能 → 放行");
  // 对照：用户=产品经理（职能=产品）→ 同一研发岗被职能门拦（证明门确实在起作用）。
  const prefs2 = { ...makePreferences(), target_roles: ["产品经理", "AI Agent"], target_keywords: [], target_industries: [] };
  assert.ok(!scoreJob(eng, prefs2, []).match_reasons.some((r) => r.type === "role"), "产品用户 → 研发岗被职能门拦");
  // (b) 岗位职能判不出（其他）但匹配到 role → 放行不误杀。
  const other = makeJob("other", "AI Agent 专家顾问", "上海", "");
  assert.ok(scoreJob(other, prefs2, []).match_reasons.some((r) => r.type === "role"), "岗位职能其他 → 放行");
});

test("跨行业门（硬门）：同职能跨行业岗不算命中目标方向（互联网用户 ✗ 消费业产品经理）", () => {
  // 农夫山泉=消费/零售；用户目标行业=互联网 → 即便职能都是产品经理，也不应算命中 role。
  const job = { ...makeJob("fmcg-pm", "产品经理", "杭州", ""), company: "农夫山泉 养生堂" };
  const prefs = {
    ...makePreferences(),
    target_roles: ["产品经理"],
    target_keywords: [],
    target_locations: ["杭州"],
    target_companies: [],
    target_industries: ["互联网"],
  };

  const blocked = scoreJob(job, prefs, []);
  assert.ok(!blocked.match_reasons.some((r) => r.type === "role"), "跨行业不应出现命中目标方向");
  assert.equal(blocked.content_matched, false, "跨行业 → 内容不命中");

  // 同岗，用户目标行业=消费 → 行业相容，role 正常命中（证明门只拦跨行业、不误伤同行业）。
  const allowed = scoreJob(job, { ...prefs, target_industries: ["消费"] }, []);
  assert.ok(allowed.match_reasons.some((r) => r.type === "role" && r.value === "产品经理"), "同行业应命中 role");
  assert.equal(allowed.content_matched, true);
});

test("跨行业门保守放行：岗位行业判不出 / 用户没填行业 → 不误杀", () => {
  const job = { ...makeJob("unknown-co", "产品经理", "杭州", ""), company: "某某集团" };
  // 用户填了行业，但公司行业判不出 → 放行，role 仍命中。
  const prefs1 = { ...makePreferences(), target_roles: ["产品经理"], target_keywords: [], target_industries: ["互联网"] };
  assert.ok(scoreJob(job, prefs1, []).match_reasons.some((r) => r.type === "role"), "行业判不出 → 放行");
  // 用户没填行业 → 门不生效，role 命中（已知公司也放行）。
  const job2 = { ...makeJob("fmcg2", "产品经理", "杭州", ""), company: "农夫山泉" };
  const prefs2 = { ...makePreferences(), target_roles: ["产品经理"], target_keywords: [], target_industries: [] };
  assert.ok(scoreJob(job2, prefs2, []).match_reasons.some((r) => r.type === "role"), "用户没填行业 → 放行");
});

test("跨行业门不挡公司命中：用户指名的公司，行业无关", () => {
  // 用户把农夫山泉列进 target_companies → 即便行业=消费而用户行业=互联网，公司命中仍算数。
  const job = { ...makeJob("named-co", "产品经理", "杭州", ""), company: "农夫山泉" };
  const prefs = {
    ...makePreferences(),
    target_roles: [],
    target_keywords: [],
    target_companies: ["农夫山泉"],
    target_industries: ["互联网"],
  };
  const r = scoreJob(job, prefs, []);
  assert.ok(r.match_reasons.some((x) => x.type === "company"), "指名公司应命中，不被跨行业门挡");
  assert.equal(r.content_matched, true);
});

test("不把非软件工程岗误判为命中目标方向（用户实锤：机械工艺岗 ✗ AI 数据产品经理）", () => {
  // 「工艺技术开发（机械/自动化）」与目标「AI 数据产品经理」毫不相干，
  // 旧逻辑经相关层把它判成命中 role + 高匹配。修复后不应再产生 role 命中理由。
  const job = {
    ...makeJob("proc-eng", "工艺技术开发（机械/自动化）", "杭州", ""),
    company: "农夫山泉 养生堂",
    first_seen_at: new Date(Date.now() - 6 * 86400000).toISOString(),
  };
  const prefs = {
    ...makePreferences(),
    target_roles: ["AI 数据产品经理"],
    target_locations: ["杭州"],
    target_keywords: [],
    target_companies: [],
    exclude_keywords: [],
  };

  const result = scoreJob(job, prefs, []);
  assert.ok(
    !result.match_reasons.some((r) => r.type === "role"),
    "机械工艺岗不应出现「命中目标方向」理由",
  );
  assert.equal(result.content_matched, false, "无内容信号命中");
  // 仅命中城市(+20)+新鲜(+10)=30 < 40 → 不应是「高匹配」。
  assert.ok(result.score < 40, "不应到达高匹配阈值");

  // Today 看板相关性门：有 role 信号但内容不命中 → 应被过滤掉，不刷屏。
  const shown = sortAndFilterJobs([job], prefs, [], { requireRelevance: true });
  assert.equal(shown.length, 0, "机械工艺岗应被相关性门过滤出 Today 看板");
});

test("requireRelevance drops jobs with no role/keyword/company match when user has content signal", () => {
  const jobs = [
    makeJob("hit", "数据分析师"), // 标题命中 role「数据分析」
    makeJob("miss", "行政专员", "上海", "负责日常行政事务"), // 标题/正文都不含查询职能
  ];
  const prefs = {
    ...makePreferences(),
    target_locations: [], // 隔离到「内容门」这一项
    target_roles: ["数据分析"],
    target_keywords: [],
    target_companies: [],
    exclude_keywords: [],
  };

  const shown = sortAndFilterJobs(jobs, prefs, [], { requireRelevance: true });
  assert.ok(shown.some((job) => job.id === "hit"));
  assert.ok(!shown.some((job) => job.id === "miss"));

  // 默认不开门 → 两者都在（回归保护：旧行为是只排序不过滤）。
  const all = sortAndFilterJobs(jobs, prefs, [], { requireRelevance: false });
  assert.equal(all.length, 2);
});

test("requireRelevance drops wrong-city jobs when user has a location signal", () => {
  const jobs = [
    makeJob("sh", "数据分析师", "上海"),
    makeJob("bj", "数据分析师", "北京"),
  ];
  const prefs = {
    ...makePreferences(),
    target_locations: ["上海"],
    target_roles: ["数据分析"],
    target_keywords: [],
    target_companies: [],
    exclude_keywords: [],
  };

  const shown = sortAndFilterJobs(jobs, prefs, [], { requireRelevance: true });
  assert.ok(shown.some((job) => job.id === "sh"));
  assert.ok(!shown.some((job) => job.id === "bj"));
});

test("requireRelevance keeps cross-language role matches (Chinese role, English title)", () => {
  const jobs = [makeJob("en", "Product Manager", "上海")];
  const prefs = {
    ...makePreferences(),
    target_locations: ["上海"],
    target_roles: ["产品经理"],
    target_keywords: [],
    target_companies: [],
    exclude_keywords: [],
  };

  const shown = sortAndFilterJobs(jobs, prefs, [], { requireRelevance: true });
  assert.equal(shown.length, 1);
  assert.equal(shown[0].id, "en");
});

test("requireRelevance with only a location signal keeps any role in that city", () => {
  const jobs = [
    makeJob("sh", "随便什么岗位", "上海", "无关描述"),
    makeJob("bj", "随便什么岗位", "北京", "无关描述"),
  ];
  const prefs = {
    ...makePreferences(),
    target_locations: ["上海"],
    target_roles: [],
    target_keywords: [],
    target_companies: [],
    exclude_keywords: [],
  };

  const shown = sortAndFilterJobs(jobs, prefs, [], { requireRelevance: true });
  assert.ok(shown.some((job) => job.id === "sh"));
  assert.ok(!shown.some((job) => job.id === "bj"));
});

function makeJob(id, title, location = "上海", summary = "Python SQL 数据分析") {
  return {
    id,
    source_id: null,
    company: "测试公司",
    title,
    location,
    job_type: "实习",
    summary,
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
    target_industries: [], // 默认空 → 跨行业门放行，旧用例不受影响
    daily_limit: 20,
  };
}

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

// 仿 tests/insight-verification.test.js：读 .ts 源码即时转译为 CommonJS 再执行（import type 被擦除）
function loadTsModule(relPath) {
  const sourcePath = path.join(__dirname, "..", relPath);
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

const D = loadTsModule(path.join("lib", "insight-derive.ts"));

const NOW = new Date("2026-06-15T00:00:00.000Z");
const NOW_ISO = NOW.toISOString();

// 构造一行最小 Job（按 lib/types.ts Job 形状），用 over 覆盖关心的字段
function j(over = {}) {
  return {
    id: "x", source_id: null, company: "测试公司", title: "工程师",
    location: "北京", job_type: "社招", summary: null, jd_url: "https://e.com/1",
    apply_url: null, salary_text: null, posted_at: null, experience: null,
    education: null, deadline: null, first_seen_at: "2026-06-01T00:00:00.000Z",
    last_seen_at: "2026-06-01T00:00:00.000Z", status: "active",
    content_hash: null, created_at: "2026-06-01T00:00:00.000Z", ...over,
  };
}

test("classifyRecruitment 按关键词归三桶（保守：无明确关键词 = unknown）", () => {
  assert.equal(D.classifyRecruitment("实习", "数据分析实习生"), "intern");
  assert.equal(D.classifyRecruitment("校招", "2026届校园招聘-后端"), "campus");
  assert.equal(D.classifyRecruitment("应届", "应届生-算法"), "campus");
  assert.equal(D.classifyRecruitment("社招", "高级后端工程师"), "social");
  assert.equal(D.classifyRecruitment(null, "Software Engineer Intern"), "intern");
  assert.equal(D.classifyRecruitment(null, "资深产品经理"), "unknown");
});

test("parseSalaryText 只解析明示月薪区间；歧义/无值返回 null", () => {
  assert.deepEqual(D.parseSalaryText("15-30K"), { minK: 15, maxK: 30 });
  assert.deepEqual(D.parseSalaryText("15k-30k"), { minK: 15, maxK: 30 });
  assert.deepEqual(D.parseSalaryText("20-40千/月"), { minK: 20, maxK: 40 });
  assert.deepEqual(D.parseSalaryText("15000-30000"), { minK: 15, maxK: 30 });
  assert.equal(D.parseSalaryText("面议"), null);
  assert.equal(D.parseSalaryText("官网未披露"), null);
  assert.equal(D.parseSalaryText(null), null);
  assert.equal(D.parseSalaryText("15-30万"), null); // 年/月歧义，保守跳过
});

test("deriveSalaryBand 聚合明示薪资（>=5 才出，否则 null）", () => {
  const jobs = [
    j({ salary_text: "15-25K" }), j({ salary_text: "20-30K" }),
    j({ salary_text: "18-28K" }), j({ salary_text: "25-35K" }),
    j({ salary_text: "面议" }), j({ salary_text: "22000-32000" }),
  ];
  const v = D.deriveSalaryBand(jobs, NOW_ISO);
  assert.ok(v);
  assert.equal(v.dimension, "compensation_intensity");
  assert.equal(v.grade, "fact");
  assert.equal(v.derived, true);
  assert.equal(v.payload.sample, 5);
  assert.match(v.content, /K/);
});

test("deriveSalaryBand 不足阈值返回 null", () => {
  assert.equal(D.deriveSalaryBand([j({ salary_text: "15-25K" })], NOW_ISO), null);
});

test("deriveTiming 概括校招峰值月 + 社招全年滚动", () => {
  const jobs = [
    j({ job_type: "校招", posted_at: "2026-08-05T00:00:00Z" }),
    j({ job_type: "校招", posted_at: "2026-09-05T00:00:00Z" }),
    j({ job_type: "校招", posted_at: "2026-08-20T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-01-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-03-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-04-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-07-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-10-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-12-05T00:00:00Z" }),
  ];
  const v = D.deriveTiming(jobs, NOW_ISO);
  assert.ok(v);
  assert.equal(v.dimension, "timing");
  assert.match(v.content, /校招集中在 8、9 月/);
  assert.match(v.content, /社招全年滚动/);
});

test("deriveTiming 不足阈值返回 null", () => {
  assert.equal(D.deriveTiming([j({ posted_at: "2026-08-01T00:00:00Z" })], NOW_ISO), null);
});

test("deriveHiring 概括在招规模/城市/方向（排除非 active）", () => {
  const jobs = [
    j({ status: "active", location: "北京", title: "后端工程师" }),
    j({ status: "active", location: "北京·海淀", title: "前端工程师" }),
    j({ status: "active", location: "上海", title: "产品经理" }),
    j({ status: "expired", location: "深圳", title: "测试" }),
  ];
  const v = D.deriveHiring(jobs, NOW_ISO);
  assert.ok(v);
  assert.equal(v.dimension, "hiring");
  assert.equal(v.derived, true);
  assert.equal(v.payload.active_count, 3);
  assert.match(v.content, /当前在招约 3 个岗位/);
  assert.match(v.content, /北京/);
});

test("deriveHiring 不足阈值返回 null", () => {
  assert.equal(D.deriveHiring([j(), j()], NOW_ISO), null);
});

// ---- 招聘大小年 / HC 强度信号 ----
test("classifyHiringSignal 趋势分级 expanding/steady/tightening", () => {
  assert.equal(D.classifyHiringSignal(100, 30).momentum, "expanding");
  assert.equal(D.classifyHiringSignal(100, -30).momentum, "tightening");
  assert.equal(D.classifyHiringSignal(100, 5).momentum, "steady");
  assert.equal(D.classifyHiringSignal(100, null).momentum, "steady"); // 无趋势→平稳
});

test("classifyHiringSignal 相对规模强度（需 headcountBand）", () => {
  assert.equal(D.classifyHiringSignal(200, 0, "5000-1万").intensity, "high"); // ≈0.027
  assert.equal(D.classifyHiringSignal(50, 0, "5000-1万").intensity, "mid"); // ≈0.0067
  assert.equal(D.classifyHiringSignal(20, 0, "5000-1万").intensity, "low"); // ≈0.0027
  assert.equal(D.classifyHiringSignal(200, 0).intensity, undefined); // 无规模档→不给强度
  assert.equal(D.classifyHiringSignal(200, 0, "未知档").intensity, undefined);
});

test("deriveHiring 带 hiring_signal + 信号写进正文", () => {
  const jobs = [1, 2, 3, 4, 5, 6, 7, 8].map(() => j({ status: "active" }));
  const v = D.deriveHiring(jobs, NOW_ISO, { headcountBand: "5000-1万" });
  assert.ok(v.payload.hiring_signal, "payload 带 hiring_signal");
  assert.equal(typeof v.payload.hiring_signal.momentum, "string");
  assert.match(v.content, /招聘信号/);
});

test("deriveCompanyInsights 只返回算得出的维度", () => {
  const jobs = [1, 2, 3, 4, 5, 6].map((i) =>
    j({ status: "active", salary_text: "15-25K", job_type: "社招", title: "后端工程师",
        location: "北京", posted_at: `2026-0${i}-05T00:00:00Z` }),
  );
  const out = D.deriveCompanyInsights(jobs, NOW);
  assert.ok(out.compensation_intensity, "应有薪资带");
  assert.ok(out.hiring, "应有招聘动态");
  assert.ok(out.timing, "社招覆盖 1–6 月（6 个不同月）→ 全年滚动");
  assert.equal(out.compensation_intensity[0].derived, true);
});

test("deriveCompanyInsights 空数据返回空对象", () => {
  assert.deepEqual(D.deriveCompanyInsights([], NOW), {});
});

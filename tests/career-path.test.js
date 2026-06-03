const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadTsModule(relPath) {
  const sourcePath = path.join(__dirname, "..", relPath);
  const compiled = ts.transpileModule(fs.readFileSync(sourcePath, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
  const module = { exports: {} };
  new Function("exports", "require", "module", "__filename", "__dirname", compiled)(
    module.exports,
    require,
    module,
    sourcePath,
    path.dirname(sourcePath),
  );
  return module.exports;
}

const C = loadTsModule(path.join("lib", "career-path.ts"));
const SEP = new Date("2026-09-15T00:00:00.000Z"); // 9 月
const JUN = new Date("2026-06-15T00:00:00.000Z"); // 6 月

function view(over = {}) {
  return {
    id: "i", company_id: "c", dimension: "timing", grade: "fact",
    title: null, content: "", sample_size: null, payload: {},
    time_window: null, valid_from: null, valid_until: null,
    last_verified_at: "", deidentified: true, status: "active",
    created_at: "", updated_at: "", sources: [], outdated: false, ...over,
  };
}
function company(over = {}) {
  return {
    company: "X", display_name: "X", job_count: 0,
    dimensions: { timing: [], compensation_intensity: [], path: [], culture: [] },
    ...over,
  };
}

test("parseRecruitingMonths: 区间 + 单月 + 滚动 + 负向 + 不可解析", () => {
  const a = C.parseRecruitingMonths("每年 7–9 月（秋招）/ 3–4 月（春招）");
  assert.deepEqual([...a.months].sort((x, y) => x - y), [3, 4, 7, 8, 9]);
  assert.equal(a.rolling, false);
  assert.equal(a.negative, false);

  const r = C.parseRecruitingMonths("全年滚动（无固定大批次）");
  assert.equal(r.rolling, true);
  assert.equal(r.months.size, 0);
  assert.equal(r.parseable, true);

  const n = C.parseRecruitingMonths("每年约 5–7 月（财年切换前后 HC 偏紧）");
  assert.deepEqual([...n.months].sort((x, y) => x - y), [5, 6, 7]);
  assert.equal(n.negative, true);

  const u = C.parseRecruitingMonths("没有月份信息");
  assert.equal(u.parseable, false);
});

test("timingStatus: 正窗口 in-range=open / out=closed", () => {
  assert.equal(C.timingStatus([view({ time_window: "每年 8–10 月（秋招）" })], SEP).status, "open");
  assert.equal(C.timingStatus([view({ time_window: "每年 3–4 月（春招）" })], SEP).status, "closed");
});

test("timingStatus: 全年滚动 / 空 / 多条取最优", () => {
  assert.equal(C.timingStatus([view({ time_window: "全年滚动" })], SEP).status, "rolling");
  assert.equal(C.timingStatus([], SEP).status, "unknown");
  // 春招(closed) + 秋招(open) → open
  const both = [view({ time_window: "每年 3–4 月（春招）" }), view({ time_window: "每年 8–10 月" })];
  assert.equal(C.timingStatus(both, SEP).status, "open");
});

test("timingStatus: 负向窗口 in-range=closed / out=unknown", () => {
  const neg = [view({ time_window: "每年约 5–7 月（HC 偏紧）" })];
  assert.equal(C.timingStatus(neg, JUN).status, "closed"); // 6 月命中偏紧期
  assert.equal(C.timingStatus(neg, SEP).status, "unknown"); // 9 月在偏紧期外，不臆断 open
});

test("buildCareerPath: 窗口期优先于在招数排序", () => {
  const open = company({
    company: "A", display_name: "A", job_count: 10,
    dimensions: {
      timing: [view({ time_window: "每年 8–10 月" })],
      compensation_intensity: [view({ dimension: "compensation_intensity", grade: "experience", title: "薪资偏高" })],
      path: [], culture: [view({ dimension: "culture", grade: "experience", title: "强度偏高", content: "据…" })],
    },
  });
  const closed = company({
    company: "B", display_name: "B", job_count: 50,
    dimensions: { timing: [view({ time_window: "每年 3–4 月" })], compensation_intensity: [], path: [], culture: [] },
  });
  const r = C.buildCareerPath({ target_roles: ["数据分析"], seniority: "校招" }, [closed, open], false, SEP);
  assert.equal(r.recommendations[0].company, "A"); // open 优先，尽管 B 在招更多
  assert.equal(r.recommendations[0].comp_note, "薪资偏高");
  assert.equal(r.recommendations[0].caution_note, "强度偏高");
  assert.ok(r.recommendations[0].reasons.includes("招聘窗口期"));
  assert.ok(r.recommendations[0].reasons.includes("10 个在招岗位"));
  assert.equal(r.cautions.length, 1);
  assert.equal(r.has_profile, true);
  assert.equal(r.failure_reason, null);
});

test("buildCareerPath: 空公司 + 无画像 → no_profile；有画像 → insight_unverified", () => {
  assert.equal(C.buildCareerPath(null, [], false, SEP).failure_reason, "no_profile");
  assert.equal(
    C.buildCareerPath({ target_roles: ["产品经理"] }, [], false, SEP).failure_reason,
    "insight_unverified",
  );
});

test("buildCareerPath: path_notes 汇总", () => {
  const c = company({
    company: "字节跳动", display_name: "字节跳动",
    dimensions: {
      timing: [], compensation_intensity: [], culture: [],
      path: [view({ dimension: "path", grade: "experience", title: "人才流动", content: "据公开报道…" })],
    },
  });
  const r = C.buildCareerPath({ target_roles: [] }, [c], false, SEP);
  assert.equal(r.path_notes.length, 1);
  assert.equal(r.path_notes[0].company, "字节跳动");
});

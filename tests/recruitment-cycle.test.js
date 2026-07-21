const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");
const { campusTimelineSummary } = loadTs(
  path.join(__dirname, "..", "lib", "recruitment-cycle.ts"),
);

// 字节秋招提前批7月/正式批8-9月 + 春招3-4月
const bytedance = [
  { grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放", value_text: "约7月", month_start: 7, month_end: 7, verify_status: "verified" },
  { grad_class: "2027届", season: "秋招", batch: "正式批", event: "开放", value_text: "8-9月", month_start: 8, month_end: 9, verify_status: "verified" },
  { grad_class: "2027届", season: "春招", batch: "正式批", event: "开放", value_text: "3-4月", month_start: 3, month_end: 4, verify_status: "verified" },
];

test("7月：秋招·现处提前批", () => {
  const r = campusTimelineSummary(bytedance, new Date("2026-07-15T00:00:00"));
  assert.equal(r.season, "秋招");
  assert.equal(r.gradClass, "2027届");
  assert.deepEqual(r.batchBits, ["提前批约7月", "正式批8-9月"]);
  assert.equal(r.phaseLabel, "现处提前批");
});

test("8月：现处正式批", () => {
  const r = campusTimelineSummary(bytedance, new Date("2026-08-20T00:00:00"));
  assert.equal(r.phaseLabel, "现处正式批");
});

test("12月：秋招已近尾声", () => {
  const r = campusTimelineSummary(bytedance, new Date("2026-12-01T00:00:00"));
  assert.equal(r.season, "秋招");
  assert.equal(r.phaseLabel, "往年这时多已近尾声");
});

test("3月：切到春招·现处正式批", () => {
  const r = campusTimelineSummary(bytedance, new Date("2027-03-10T00:00:00"));
  assert.equal(r.season, "春招");
  assert.deepEqual(r.batchBits, ["正式批3-4月"]);
  assert.equal(r.phaseLabel, "现处正式批");
});

test("2月且只有秋招观测：回退秋招·phaseLabel null", () => {
  const onlyFall = bytedance.filter((o) => o.season === "秋招");
  const r = campusTimelineSummary(onlyFall, new Date("2027-02-10T00:00:00"));
  assert.equal(r.season, "秋招");
  assert.equal(r.phaseLabel, null);
});

test("黄金期事件命中：现处黄金期", () => {
  const withGolden = [
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "黄金期", value_text: "9月", month_start: 9, month_end: 9, verify_status: "verified" },
  ];
  const r = campusTimelineSummary(withGolden, new Date("2026-09-10T00:00:00"));
  assert.equal(r.phaseLabel, "现处黄金期");
});

test("过期观测被过滤 → null", () => {
  const expired = bytedance.map((o) => ({ ...o, valid_until: "2025-06-30" }));
  const r = campusTimelineSummary(expired, new Date("2026-07-15T00:00:00"));
  assert.equal(r, null);
});

test("未 verified 被过滤 → null", () => {
  const draft = bytedance.map((o) => ({ ...o, verify_status: "draft" }));
  assert.equal(campusTimelineSummary(draft, new Date("2026-07-15T00:00:00")), null);
});

test("空数组 → null", () => {
  assert.equal(campusTimelineSummary([], new Date("2026-07-15T00:00:00")), null);
});

const { validateCycleInput } = loadTs(
  path.join(__dirname, "..", "lib", "recruitment-cycle-validate.ts"),
);

test("合法输入通过", () => {
  const r = validateCycleInput({
    company_id: "c1", grad_class: "2027届", season: "秋招", batch: "提前批",
    event: "开放", time_expr_type: "月", value_text: "约7月", month_start: 7, month_end: 7,
  });
  assert.equal(r.ok, true);
  assert.equal(r.fields.value_text, "约7月");
});

test("非法季 → 报错", () => {
  const r = validateCycleInput({ company_id: "c1", grad_class: "2027届", season: "夏招", batch: "提前批", event: "开放", time_expr_type: "月", value_text: "x" });
  assert.equal(r.ok, false);
});

test("缺 grad_class → 报错（据往年必绑届别）", () => {
  const r = validateCycleInput({ company_id: "c1", season: "秋招", batch: "提前批", event: "开放", time_expr_type: "月", value_text: "x" });
  assert.equal(r.ok, false);
});

test("精确日期缺 evidence_url → 报错（P3 官方源门）", () => {
  const r = validateCycleInput({ company_id: "c1", grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放", time_expr_type: "精确日期", value_text: "9月1日", date_start: "2026-09-01" });
  assert.equal(r.ok, false);
});

test("month 越界 → 报错", () => {
  const r = validateCycleInput({ company_id: "c1", grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放", time_expr_type: "月", value_text: "x", month_start: 13 });
  assert.equal(r.ok, false);
});

const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");
const { campusPreciseDates, campusBatchTimingGap, cleanCampusDeadlineMs } = loadTs(
  path.join(__dirname, "..", "lib", "recruitment-cycle.ts"),
);

const NOW = new Date("2026-07-22T00:00:00Z");

test("campusPreciseDates 取 verified 未过期精确日期行", () => {
  const obs = [
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "截止",
      time_expr_type: "精确日期", value_text: "网申9月10日截止", month_start: 9, month_end: null,
      verify_status: "verified", valid_until: "2027-06-30" },
    { grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放",
      time_expr_type: "月", value_text: "约7月", month_start: 7, month_end: null,
      verify_status: "verified", valid_until: "2027-06-30" }, // 非精确日期，排除
  ];
  const bits = campusPreciseDates(obs, NOW);
  assert.equal(bits.length, 1);
  assert.match(bits[0].label, /网申9月10日截止/);
});

test("campusPreciseDates 排除 draft / 过期", () => {
  const obs = [
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "截止",
      time_expr_type: "精确日期", value_text: "9月10日", month_start: 9,
      verify_status: "draft", valid_until: "2027-06-30" },
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "截止",
      time_expr_type: "精确日期", value_text: "9月10日", month_start: 9,
      verify_status: "verified", valid_until: "2025-06-30" },
  ];
  assert.equal(campusPreciseDates(obs, NOW).length, 0);
});

test("campusBatchTimingGap 提前批比正式批早", () => {
  const obs = [
    { grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放",
      month_start: 7, verify_status: "verified", valid_until: "2027-06-30" },
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "开放",
      month_start: 9, verify_status: "verified", valid_until: "2027-06-30" },
  ];
  assert.match(campusBatchTimingGap(obs, NOW), /提前批.*早/);
});

test("campusBatchTimingGap 缺一批返回 null", () => {
  const obs = [
    { grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放",
      month_start: 7, verify_status: "verified", valid_until: "2027-06-30" },
  ];
  assert.equal(campusBatchTimingGap(obs, NOW), null);
});

test("cleanCampusDeadlineMs 接受近未来、滤垃圾/过去", () => {
  assert.ok(cleanCampusDeadlineMs("2026-08-01", NOW) > 0);
  assert.equal(cleanCampusDeadlineMs("长期有效", NOW), null);
  assert.equal(cleanCampusDeadlineMs("3000-01-01", NOW), null);
  assert.equal(cleanCampusDeadlineMs("2025-01-01", NOW), null);
  assert.equal(cleanCampusDeadlineMs("", NOW), null);
});

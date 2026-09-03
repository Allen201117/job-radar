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

test("12月：秋招已近尾声（措辞自陈推测，不再说「往年这时」）", () => {
  // 原措辞「往年这时多已近尾声」：数据其实是本届（2027届）观测，说「往年」是错的归因。
  const r = campusTimelineSummary(bytedance, new Date("2026-12-01T00:00:00"));
  assert.equal(r.season, "秋招");
  assert.equal(r.phaseLabel, "推测已近尾声");
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

// ============================================================
// 2026-09-03 标签矛盾治本（用户实锤：「标签好多都矛盾」）
//
// live 渲染 47 家有观测的公司，14 家会出标签，**14 家全部长这样**：
//   「[据往年] 2027届 · 正式批8-10月 · 现处正式批」
// 「据往年」和「2027届」字面就打架 —— 往年不可能有 2027 届。根因是措辞被硬编码在
// UI 里，而底下的数据其实是**本届**的公开信息聚合（库里 113 条观测 grad_class 全是 2027届）。
//
// 第二处更伤：高途 212 个在招校招岗、作业帮 53 个，卡面徽章写「🟢 招聘中」，
// 同一张卡上的时间线却写「往年这时多已近尾声」—— 推测在视觉上压过了硬证据。
// `windowStatus` 早就立过这条规矩（「有真实校招岗就不能判待接入，否则卡面列着岗
// 却说待接入自相矛盾」），phaseLabel 却没受同一约束。
// ============================================================

test("basis：数据是本届 + 官方来源 → official（措辞该说「今年·据官方公告」）", () => {
  const obs = [
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "开放", value_text: "8-10月",
      month_start: 8, month_end: 10, verify_status: "verified", source_kind: "official_site" },
  ];
  const r = campusTimelineSummary(obs, new Date("2026-09-03T00:00:00"));
  assert.equal(r.basis, "official");
  assert.equal(r.gradClass, "2027届");
});

test("basis：数据是本届 + 公开聚合 → public（不许说「据往年」）", () => {
  const obs = [
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "开放", value_text: "8-10月",
      month_start: 8, month_end: 10, verify_status: "verified", source_kind: "public_aggregate" },
  ];
  const r = campusTimelineSummary(obs, new Date("2026-09-03T00:00:00"));
  assert.equal(r.basis, "public");
});

test("basis：数据是往届 → historical（这时候「据往年」才是诚实的）", () => {
  const obs = [
    { grad_class: "2025届", season: "秋招", batch: "正式批", event: "开放", value_text: "8-10月",
      month_start: 8, month_end: 10, verify_status: "verified", source_kind: "public_aggregate" },
  ];
  const r = campusTimelineSummary(obs, new Date("2026-09-03T00:00:00"));
  assert.equal(r.basis, "historical");
});

test("硬证据压过推测：公司当下有在招校招岗时，不得输出「已近尾声」", () => {
  // 高途实测：212 个在招校招岗，徽章「🟢 招聘中」，时间线却说「往年这时多已近尾声」。
  // 自有岗位库是第一手事实，外部聚合的月份窗口是推测；打架时以事实为准。
  const obs = [
    { grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放", value_text: "8月7日",
      month_start: 8, month_end: 8, verify_status: "verified", source_kind: "public_aggregate" },
  ];
  const now = new Date("2026-09-03T00:00:00");
  assert.equal(campusTimelineSummary(obs, now).phaseLabel, "推测已近尾声",
    "没有岗位数信息时仍可给推测，但措辞必须自陈是推测");
  assert.equal(campusTimelineSummary(obs, now, { campusJobCount: 212 }).phaseLabel, null,
    "有 212 个在招岗 → 绝不能说已近尾声，宁可不说");
  assert.equal(campusTimelineSummary(obs, now, { campusJobCount: 0 }).phaseLabel, "推测已近尾声",
    "确实 0 个在招岗 → 推测可以保留");
});

test("「现处正式批」这类肯定性判断不受岗位数约束（它与在招并不矛盾）", () => {
  const obs = [
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "开放", value_text: "8-10月",
      month_start: 8, month_end: 10, verify_status: "verified", source_kind: "official_site" },
  ];
  const now = new Date("2026-09-03T00:00:00");
  assert.equal(campusTimelineSummary(obs, now, { campusJobCount: 212 }).phaseLabel, "现处正式批");
  assert.equal(campusTimelineSummary(obs, now, { campusJobCount: 0 }).phaseLabel, "现处正式批");
});

test("旧调用方（不传 campusJobCount）行为不变，只是措辞自陈推测", () => {
  const r = campusTimelineSummary(bytedance, new Date("2026-12-01T00:00:00"));
  assert.equal(r.season, "秋招");
  assert.equal(r.phaseLabel, "推测已近尾声");
});

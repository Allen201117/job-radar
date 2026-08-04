const { test } = require("node:test");
const assert = require("node:assert");
const { extractGradClass, currentGradClass, isCurrentSeasonGradClass } = require("../lib/grad-class");

test("extractGradClass: 四位年份 + 届", () => {
  assert.equal(extractGradClass({ title: "2027届校园招聘-后端工程师" }), 2027);
  assert.equal(extractGradClass({ title: "2027 届 算法工程师" }), 2027);
  assert.equal(extractGradClass({ summary: "面向2026届毕业生" }), 2026);
});

test("extractGradClass: 两位年份 + 届", () => {
  assert.equal(extractGradClass({ title: "27届秋招-数据分析" }), 2027);
  assert.equal(extractGradClass({ title: "26届春季校园招聘" }), 2026);
});

test("extractGradClass: 年份 + 校招/秋招/春招/校园招聘", () => {
  assert.equal(extractGradClass({ title: "2027校招-产品经理" }), 2027);
  assert.equal(extractGradClass({ title: "2027秋招正式批 前端" }), 2027);
  assert.equal(extractGradClass({ title: "2028春招提前批" }), 2028);
  assert.equal(extractGradClass({ summary: "2027年校园招聘正式启动" }), 2027);
});

test("extractGradClass: 英文硬信号", () => {
  assert.equal(extractGradClass({ title: "Software Engineer, Class of 2027" }), 2027);
  assert.equal(extractGradClass({ title: "2027 Graduate Program - Analyst" }), 2027);
});

test("extractGradClass: 多个届别取最大（『2026/2027届均可』取更晚那届）", () => {
  assert.equal(extractGradClass({ title: "2026/2027届校园招聘" }), 2027);
  assert.equal(extractGradClass({ title: "26届、27届均可投递", summary: "2025届不再接收" }), 2027);
});

test("extractGradClass: 无硬信号一律 null，绝不靠时间/上下文猜", () => {
  // 宁缺不编：8 月抓到的校招岗大概率是 2027 届，但也可能是 2026 届收尾岗。
  // 猜错会把上一届残岗标成当季，比留白更伤用户。
  assert.equal(extractGradClass({ title: "校园招聘-后端工程师" }), null);
  assert.equal(extractGradClass({ title: "管培生" }), null);
  assert.equal(extractGradClass({}), null);
  assert.equal(extractGradClass(null), null);
});

test("extractGradClass: 不把无关年份当届别", () => {
  // 「2027年12月前入职」「成立于2027」这类年份不带届别语境，不能当届别
  assert.equal(extractGradClass({ summary: "预计2027年12月前完成入职" }), null);
  assert.equal(extractGradClass({ title: "2027 年度预算分析师" }), null);
  // 电话/薪资等数字噪声
  assert.equal(extractGradClass({ summary: "月薪 20000-27000" }), null);
});

test("extractGradClass: 届别年份必须落在合理窗口内", () => {
  // 防把 1999 届 / 3027 届之类的垃圾解析出来当真
  assert.equal(extractGradClass({ title: "1998届校园招聘" }), null);
  assert.equal(extractGradClass({ title: "3027届校园招聘" }), null);
});

test("currentGradClass: 5-12 月看下一届，1-4 月看当年那届", () => {
  // 与 lib/recruitment-cycle.ts 的选季口径一致：5-12 月是秋招（招次年毕业的那届）
  assert.equal(currentGradClass(new Date("2026-08-04T00:00:00Z")), 2027);
  assert.equal(currentGradClass(new Date("2026-12-31T00:00:00Z")), 2027);
  // 1-4 月是春招，补的还是当年毕业的那届
  assert.equal(currentGradClass(new Date("2027-03-01T00:00:00Z")), 2027);
  assert.equal(currentGradClass(new Date("2027-04-30T00:00:00Z")), 2027);
  assert.equal(currentGradClass(new Date("2027-05-01T00:00:00Z")), 2028);
});

test("isCurrentSeasonGradClass: 当季 + 未知都放行，往届不放行", () => {
  const now = new Date("2026-08-04T00:00:00Z"); // 当季 = 2027 届
  assert.equal(isCurrentSeasonGradClass(2027, now), true);
  // 未知届别照常展示（留白不等于隐藏）——绝大多数岗抽不出届别，隐藏它们等于清空专区
  assert.equal(isCurrentSeasonGradClass(null, now), true);
  assert.equal(isCurrentSeasonGradClass(undefined, now), true);
  // 明确是上一届的岗移出默认列表
  assert.equal(isCurrentSeasonGradClass(2026, now), false);
  // 更晚的届别（提前批常见）放行，不该被当成过期
  assert.equal(isCurrentSeasonGradClass(2028, now), true);
});

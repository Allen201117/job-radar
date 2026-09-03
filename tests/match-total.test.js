const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { formatMatchTotal } = loadTs(path.join(__dirname, "..", "lib", "match-total.ts"));

// 「匹配岗位数」诚实展示：候选没撞上限才允许给确定数字。
// 背景：检索是「先取候选、再 JS 精筛」，候选撞上限时 total 只是取数上限——
// 线上「深圳+社招」因此长期把 8000（FTS_CAP）当真实数展示，实际库里 15,290 个。

test("没撞上限 → 原样给精确数字", () => {
  assert.deepEqual(formatMatchTotal(2285, false, null), { text: "2285", approximate: false });
});

test("撞上限且服务端算不出真实总数 → 只给下限，不给确定数字", () => {
  const r = formatMatchTotal(8000, true, null);
  assert.equal(r.text, "8000+");
  assert.equal(r.approximate, true);
  // 关键断言：撞上限时绝不能渲染成裸的「8000」。
  assert.notEqual(r.text, "8000");
});

test("撞上限但服务端给出可信真实总数 → 用真实总数", () => {
  const r = formatMatchTotal(8000, true, 15290);
  assert.deepEqual(r, { text: "15290", approximate: false });
});

test("真实总数比已排出的条数还小 = 不可信 → 退回下限表述", () => {
  const r = formatMatchTotal(8000, true, 12);
  assert.equal(r.text, "8000+");
  assert.equal(r.approximate, true);
});

test("exactTotal 缺省 / 非数字一律当没有", () => {
  for (const bad of [undefined, null, NaN, "15290"]) {
    assert.equal(formatMatchTotal(8000, true, bad).text, "8000+");
  }
});

test("0 和异常 total 不会渲染成 NaN", () => {
  assert.equal(formatMatchTotal(0, false, null).text, "0");
  assert.equal(formatMatchTotal(NaN, false, null).text, "0");
  assert.equal(formatMatchTotal(-3, true, null).text, "0+");
});

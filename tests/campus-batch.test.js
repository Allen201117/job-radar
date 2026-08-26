const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { gradClassLabel, isEarlyBatch } = loadTs(
  path.join(__dirname, "..", "lib", "campus-batch.ts"),
);

test("gradClassLabel：有届别才展示短标签，空值安静留白", () => {
  assert.equal(gradClassLabel(2027), "2027届");
  assert.equal(gradClassLabel(null), null);
  assert.equal(gradClassLabel(undefined), null);
});

test("gradClassLabel：异常届别输入不产生标签", () => {
  assert.equal(gradClassLabel("2027"), null);
  assert.equal(gradClassLabel(NaN), null);
  assert.equal(gradClassLabel(Infinity), null);
});

test("isEarlyBatch：只认标题里的提前批", () => {
  assert.equal(isEarlyBatch("2027届提前批算法工程师"), true);
  assert.equal(isEarlyBatch("2027届正式批算法工程师"), false);
  assert.equal(isEarlyBatch("2027届预批算法工程师"), false);
  assert.equal(isEarlyBatch(""), false);
  assert.equal(isEarlyBatch(null), false);
  assert.equal(isEarlyBatch(undefined), false);
});

test("批次展示永远不产生正式批标签", () => {
  for (const gradClass of [2027, null, undefined, "2027", NaN]) {
    assert.notEqual(gradClassLabel(gradClass), "正式批");
  }
  for (const title of ["正式批", "提前批", "", null, undefined]) {
    assert.notEqual(isEarlyBatch(title), "正式批");
  }
});

test("gradClassLabel：明显超出合理窗口的误提取不展示", () => {
  // 生产实测 active 里真有这些值：2030 有 12 条、2037 有 1 条，
  // 都是标题里其它年份被当成届别；渲染出来就是错的。
  const aug2026 = new Date("2026-08-26T00:00:00Z"); // 当季 = 2027 届
  assert.equal(gradClassLabel(2037, aug2026), null);
  assert.equal(gradClassLabel(2019, aug2026), null);
  // 窗口内的照常展示
  assert.equal(gradClassLabel(2027, aug2026), "2027届");
  assert.equal(gradClassLabel(2026, aug2026), "2026届");
  assert.equal(gradClassLabel(2025, aug2026), "2025届"); // 收尾岗
  assert.equal(gradClassLabel(2030, aug2026), "2030届"); // 低年级实习，窗口上沿
  // 边界外一格
  assert.equal(gradClassLabel(2024, aug2026), null);
  assert.equal(gradClassLabel(2031, aug2026), null);
});

test("gradClassLabel：非整数与异常输入一律留白，且永不产出「正式批」", () => {
  for (const bad of [2027.5, NaN, Infinity, "2027", {}, [], true]) {
    assert.equal(gradClassLabel(bad), null);
  }
  const outputs = [];
  for (let y = 2015; y <= 2100; y += 1) outputs.push(gradClassLabel(y));
  assert.equal(outputs.some((v) => typeof v === "string" && v.includes("正式批")), false);
});

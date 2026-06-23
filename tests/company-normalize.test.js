const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { normalizeCompany } = loadTs(path.join(__dirname, "..", "lib", "company-normalize.ts"));

test("trim + lowercase + NFKC（全角→半角）", () => {
  assert.equal(normalizeCompany("  ByteDance  "), "bytedance");
  assert.equal(normalizeCompany("ＡＢＣ"), "abc");
});

test("移除所有空白", () => {
  assert.equal(normalizeCompany("Morgan Stanley"), "morganstanley");
  assert.equal(normalizeCompany("字节 跳动"), "字节跳动");
});

test("移除常见公司尾缀（长的先移）", () => {
  assert.equal(normalizeCompany("字节跳动有限公司"), "字节跳动");
  assert.equal(normalizeCompany("某某股份有限公司"), "某某");
  assert.equal(normalizeCompany("阿里巴巴集团"), "阿里巴巴");
  assert.equal(normalizeCompany("腾讯控股"), "腾讯");
  assert.equal(normalizeCompany("字节跳动中国"), "字节跳动");
  assert.equal(normalizeCompany("Apple China"), "apple");
});

test("不做模糊合并：不同公司 → 不同归一值", () => {
  assert.notEqual(normalizeCompany("美团"), normalizeCompany("美团点评"));
  assert.notEqual(normalizeCompany("字节"), normalizeCompany("字节跳动"));
});

test("空 / 非法输入 → 空串", () => {
  assert.equal(normalizeCompany(""), "");
  assert.equal(normalizeCompany(null), "");
  assert.equal(normalizeCompany(undefined), "");
  assert.equal(normalizeCompany(123), "");
});

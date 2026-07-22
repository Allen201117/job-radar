const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

// 企业 logo 首字母兜底纯函数（lib/company-logo.ts），被 components/CompanyLogo.tsx 复用。
const { logoKey, monogramText, monogramColor } = loadTs(
  path.join(__dirname, "..", "lib", "company-logo.ts"),
);

const HEX = /^#[0-9a-fA-F]{6}$/;

test("logoKey: trim + 小写归一", () => {
  assert.equal(logoKey("  ByteDance  "), "bytedance");
  assert.equal(logoKey("字节跳动"), "字节跳动");
  assert.equal(logoKey(""), "");
  assert.equal(logoKey(undefined), "");
});

test("monogramText: 中文取首字", () => {
  assert.equal(monogramText("字节跳动"), "字");
  assert.equal(monogramText("小鹏汽车"), "小");
});

test("monogramText: 拉丁取首字母大写", () => {
  assert.equal(monogramText("bytedance"), "B");
  assert.equal(monogramText("airbnb"), "A");
});

test("monogramText: 空串给中性点，不抛错", () => {
  assert.equal(monogramText(""), "·");
  assert.equal(monogramText("   "), "·");
  assert.equal(monogramText(undefined), "·");
});

test("monogramColor: 返回合法 hex 且 bg≠fg", () => {
  for (const c of ["字节跳动", "腾讯", "airbnb", "a"]) {
    const { bg, fg } = monogramColor(c);
    assert.match(bg, HEX, `${c} bg`);
    assert.match(fg, HEX, `${c} fg`);
    assert.notEqual(bg, fg, `${c} bg≠fg`);
  }
});

test("monogramColor: 同名恒定同色（确定性）", () => {
  assert.deepEqual(monogramColor("美团"), monogramColor("美团"));
  assert.deepEqual(monogramColor("Meituan"), monogramColor("Meituan"));
});

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

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
  const fn = new Function(
    "exports",
    "require",
    "module",
    "__filename",
    "__dirname",
    compiled,
  );
  fn(module.exports, require, module, sourcePath, path.dirname(sourcePath));
  return module.exports;
}

const M = loadTsModule(path.join("lib", "insight-match.ts"));

function profile(company, aliases = []) {
  return { id: company, company, display_name: company, aliases, summary: null, last_verified_at: null, created_at: "", updated_at: "" };
}

test("normalizeCompany 去后缀与地域装饰", () => {
  assert.equal(M.normalizeCompany("字节跳动有限公司"), "字节跳动");
  assert.equal(M.normalizeCompany("Microsoft (China)"), "microsoft");
  assert.equal(M.normalizeCompany("Apple Inc."), "apple");
  assert.equal(M.normalizeCompany("  腾讯科技有限公司 "), "腾讯");
});

test("companyMatches 命中 company 或 alias", () => {
  const p = profile("字节跳动", ["字节", "ByteDance"]);
  assert.equal(M.companyMatches(p, "字节"), true);
  assert.equal(M.companyMatches(p, "bytedance"), true);
  assert.equal(M.companyMatches(p, "字节跳动（中国）"), true);
  assert.equal(M.companyMatches(p, "腾讯"), false);
});

test("findCompanyProfile 全等优先于子串", () => {
  const profiles = [
    profile("苹果", ["Apple", "苹果中国"]),
    profile("微软", ["Microsoft", "微软中国"]),
  ];
  assert.equal(M.findCompanyProfile(profiles, "Apple").company, "苹果");
  assert.equal(M.findCompanyProfile(profiles, "Microsoft (China)").company, "微软");
  assert.equal(M.findCompanyProfile(profiles, "不存在的公司"), null);
});

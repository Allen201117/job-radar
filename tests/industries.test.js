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

const I = loadTsModule(path.join("lib", "industries.ts"));

test("normalizeIndustry: 去空白 / 截断 / 空转 null", () => {
  assert.equal(I.normalizeIndustry("  金融 "), "金融");
  assert.equal(I.normalizeIndustry("制造/工业"), "制造/工业");
  assert.equal(I.normalizeIndustry(""), null);
  assert.equal(I.normalizeIndustry("   "), null);
  assert.equal(I.normalizeIndustry(null), null);
  assert.equal(I.normalizeIndustry(123), null);
  assert.equal(I.normalizeIndustry("x".repeat(50)).length, 40);
});

test("INDUSTRIES 覆盖主要行业", () => {
  for (const ind of ["互联网/科技", "金融", "制造/工业", "医疗/医药", "能源/化工", "央国企"]) {
    assert.ok(I.INDUSTRIES.includes(ind), `${ind} 应在建议列表`);
  }
});

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

const { cleanSummary } = loadTsModule(path.join("lib", "utils.ts"));

test("解 HTML 实体后去标签（修历史 greenhouse 乱码）", () => {
  assert.equal(cleanSummary("&lt;p&gt;-&lt;/p&gt;"), "-");
  const out = cleanSummary('&lt;div class=&quot;intro&quot;&gt;&lt;h2&gt;About&lt;/h2&gt;&lt;p&gt;Hello&lt;/p&gt;');
  assert.ok(!out.includes("&lt;"));
  assert.ok(!out.includes("<"));
  assert.ok(out.includes("About"));
  assert.ok(out.includes("Hello"));
});

test("纯文本与真实标签", () => {
  assert.equal(cleanSummary("plain text stays"), "plain text stays");
  assert.equal(cleanSummary("<p>hi</p>"), "hi");
});

test("空值幂等", () => {
  assert.equal(cleanSummary(null), "");
  assert.equal(cleanSummary(undefined), "");
  assert.equal(cleanSummary(""), "");
});

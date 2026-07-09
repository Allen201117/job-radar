const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const Module = require("node:module");
const { cityMatchTokens } = require("../lib/china-keyword-expansion");

// A2 双向城市匹配：治 normalizeChinaCity 单向归一 → filter「北京」漏掉 location="Beijing" 的岗。
test("cityMatchTokens：中文筛选词带出英文/拼音别名（反向）", () => {
  const bj = cityMatchTokens("北京");
  assert.ok(bj.includes("beijing"), "北京 应含 beijing 别名");
  assert.ok(bj.includes("北京"), "北京 应含自身");
});

test("cityMatchTokens：英文筛选词带出中文规范名（正向）", () => {
  const bj = cityMatchTokens("Beijing");
  assert.ok(bj.includes("北京"), "Beijing 应含中文 北京");
  assert.ok(bj.includes("beijing"));
});

test("cityMatchTokens：空 → []", () => {
  assert.deepEqual(cityMatchTokens(""), []);
  assert.deepEqual(cityMatchTokens(null), []);
});

// 递归 TS 加载器（解 @/ 别名 + 相对 .ts；.js/node_modules 走原生 require）。
const ROOT = path.join(__dirname, "..");
function loadTs(absPath, cache = new Map()) {
  if (cache.has(absPath)) return cache.get(absPath).exports;
  const compiled = ts.transpileModule(fs.readFileSync(absPath, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true },
  }).outputText;
  const mod = { exports: {} };
  cache.set(absPath, mod);
  const dir = path.dirname(absPath);
  const baseRequire = Module.createRequire(absPath);
  const customRequire = (spec) => {
    let base = null;
    if (spec.startsWith("@/")) base = path.join(ROOT, spec.slice(2));
    else if (spec.startsWith(".")) base = path.resolve(dir, spec);
    if (base) {
      const tsPath = base.endsWith(".ts") ? base : `${base}.ts`;
      if (fs.existsSync(tsPath)) return loadTs(tsPath, cache);
      return baseRequire(base);
    }
    return baseRequire(spec);
  };
  new Function("exports", "require", "module", "__filename", "__dirname", compiled)(
    mod.exports, customRequire, mod, absPath, dir,
  );
  return mod.exports;
}
const { jobFilterTier, DEFAULT_FILTERS } = loadTs(path.join(ROOT, "lib", "job-filter.ts"));
const base = { ...DEFAULT_FILTERS };

test("jobFilterTier：筛『北京』命中英文 location=Beijing（核心修复）", () => {
  const job = { id: "1", company: "X", title: "产品经理", location: "Beijing, China", jd_url: "u" };
  assert.notEqual(jobFilterTier(job, { ...base, city: "北京" }), null);
});

test("jobFilterTier：筛『北京』仍淘汰 location=上海", () => {
  const job = { id: "2", company: "X", title: "产品经理", location: "上海", jd_url: "u" };
  assert.equal(jobFilterTier(job, { ...base, city: "北京" }), null);
});

test("jobFilterTier：city 缺失仍降级放行（不淘汰）", () => {
  const job = { id: "3", company: "X", title: "产品经理", location: "", jd_url: "u" };
  assert.equal(jobFilterTier(job, { ...base, city: "北京" }), "related");
});

// 测试辅助：递归即时转译加载 TS 模块（非 *.test.js，不会被 `node --test tests/*.test.js` 当测试跑）。
//
// 背景：lib/opportunities/* 的引擎模块用 .ts 写、且彼此运行时 import（如 eligibility → freshness）。
// 原 tests/scoring.test.js 的单文件 shim 只能解析 .ts→.js 的 import（createRequire 加载不了 .ts 兄弟）。
// 这里做一个会「相对 .ts import 递归转译、.js / node_modules 走原生 require」的加载器，供引擎各测试复用。
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const Module = require("node:module");

function transpile(source) {
  return ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
}

// 加载一个 TS 文件（绝对路径）；cache 跨递归共享，支持循环依赖（执行前先登记 mod）。
function loadTs(absPath, cache = new Map()) {
  if (cache.has(absPath)) return cache.get(absPath).exports;

  const source = fs.readFileSync(absPath, "utf8");
  const compiled = transpile(source);
  const mod = { exports: {} };
  cache.set(absPath, mod);

  const dir = path.dirname(absPath);
  const baseRequire = Module.createRequire(absPath);
  const customRequire = (spec) => {
    if (spec.startsWith(".")) {
      const candidate = path.resolve(dir, spec);
      const tsPath = candidate.endsWith(".ts") ? candidate : `${candidate}.ts`;
      if (fs.existsSync(tsPath)) return loadTs(tsPath, cache);
    }
    return baseRequire(spec); // .js / node_modules / 类型已被转译擦除的不会到这
  };

  const fn = new Function("exports", "require", "module", "__filename", "__dirname", compiled);
  fn(mod.exports, customRequire, mod, absPath, dir);
  return mod.exports;
}

// 便捷：加载 lib/opportunities/<rel>.ts
function loadOpp(rel) {
  const file = rel.endsWith(".ts") ? rel : `${rel}.ts`;
  return loadTs(path.join(__dirname, "..", "lib", "opportunities", file));
}

module.exports = { loadTs, loadOpp, transpile };

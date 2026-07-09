const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const Module = require("node:module");

// 直接测 lib/job-filter.ts 的 jobFilterTier：类型筛选的「自报家门」非对称门。
// 递归 TS 加载器（处理 @/ 别名 + 相对 .ts 依赖，.js/node_modules 走原生 require）。
const ROOT = path.join(__dirname, "..");
function loadTs(absPath, cache = new Map()) {
  if (cache.has(absPath)) return cache.get(absPath).exports;
  const compiled = ts.transpileModule(fs.readFileSync(absPath, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
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
      return baseRequire(base); // 同名 .js
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

// 无任何类型信号的岗（外企 ATS 产品岗常态：job_type 空、正文空、url 无渠道段）。
// recruitmentCategory 会把它兜底成「社招」并在卡片打「社招」芯片。
const unknownType = {
  id: "1",
  company: "Johnson Controls",
  title: "APAC Field Device Product Manager",
  location: "Shanghai",
  summary: "",
  job_type: null,
  jd_url: "https://boards.greenhouse.io/johnsoncontrols/jobs/1",
};

test("选『实习』：无类型信号岗必须淘汰（不是自报家门的实习 → 不放行冒充）", () => {
  assert.equal(jobFilterTier(unknownType, { ...base, jobType: "实习" }), null);
});

test("选『校招』：无类型信号岗必须淘汰（校招也自报家门）", () => {
  assert.equal(jobFilterTier(unknownType, { ...base, jobType: "校招" }), null);
});

test("选『社招』：无类型信号岗放行降级（未知≈社招，保『94% job_type 空不被杀光』）", () => {
  const tier = jobFilterTier(unknownType, { ...base, jobType: "社招" });
  assert.notEqual(tier, null);
});

test("真实习（标题自报家门）选『实习』→ 保留为 exact", () => {
  const intern = {
    id: "2",
    company: "字节跳动",
    title: "2026 暑期实习生 - 产品",
    location: "北京",
    jd_url: "https://example.com/shixi/2",
  };
  assert.equal(jobFilterTier(intern, { ...base, jobType: "实习" }), "exact");
});

test("显式社招（源 job_type=社招）选『实习』→ 淘汰（本就正确，防回归）", () => {
  const social = {
    id: "3",
    company: "某公司",
    title: "数据分析",
    location: "上海",
    job_type: "社招",
    jd_url: "https://example.com/3",
  };
  assert.equal(jobFilterTier(social, { ...base, jobType: "实习" }), null);
});

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const Module = require("node:module");

// 递归 TS 加载器（解 @/ 别名 + 相对 .ts；.js/node_modules 走原生 require）。
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
      return baseRequire(base);
    }
    return baseRequire(spec);
  };
  new Function("exports", "require", "module", "__filename", "__dirname", compiled)(
    mod.exports,
    customRequire,
    mod,
    absPath,
    dir,
  );
  return mod.exports;
}

const {
  DEFAULT_FILTERS,
  filterAndRankJobs,
  jobFilterMatch,
  jobFilterTier,
  countMatchBreakdown,
} = loadTs(path.join(ROOT, "lib", "job-filter.ts"));

const base = { ...DEFAULT_FILTERS };

function job(overrides = {}) {
  return {
    id: overrides.id || "job-1",
    company: "Acme",
    title: "后端开发工程师",
    location: "北京",
    education: "本科及以上",
    job_type: "社招",
    jd_url: `https://example.com/${overrides.id || "job-1"}`,
    match_score: 10,
    ...overrides,
  };
}

test("jobFilterMatch：clean keyword and soft fields stay exact with no degraded fields", () => {
  const filters = { ...base, keyword: "后端", city: "北京", education: "本科", jobType: "社招" };
  const result = jobFilterMatch(job(), filters);

  assert.deepEqual(result, {
    tier: "exact",
    keywordTier: "exact",
    degradedFields: [],
  });
  assert.equal(jobFilterTier(job(), filters), result.tier);
});

test("jobFilterMatch：same-function keyword match is related without degraded fields", () => {
  const filters = { ...base, keyword: "后端" };
  const result = jobFilterMatch(job({ title: "高级软件工程师" }), filters);

  assert.deepEqual(result, {
    tier: "related",
    keywordTier: "related",
    degradedFields: [],
  });
});

test("jobFilterMatch：missing city records only city degradation", () => {
  const filters = { ...base, city: "北京" };
  const result = jobFilterMatch(job({ location: "" }), filters);

  assert.deepEqual(result, {
    tier: "related",
    keywordTier: "none",
    degradedFields: ["city"],
  });
});

test("jobFilterMatch：missing or unparseable education records only education degradation", () => {
  const filters = { ...base, education: "本科" };
  const result = jobFilterMatch(job({ education: "" }), filters);

  assert.deepEqual(result, {
    tier: "related",
    keywordTier: "none",
    degradedFields: ["education"],
  });
});

test("jobFilterMatch：unknown type with 社招 filter records only type degradation", () => {
  const filters = { ...base, jobType: "社招" };
  const result = jobFilterMatch(
    job({
      title: "APAC Field Device Product Manager",
      summary: "",
      job_type: null,
      jd_url: "https://boards.greenhouse.io/acme/jobs/1",
    }),
    filters,
  );

  assert.deepEqual(result, {
    tier: "related",
    keywordTier: "none",
    degradedFields: ["type"],
  });
});

test("jobFilterMatch：keyword-related plus missing fields keeps all structured causes", () => {
  const filters = { ...base, keyword: "后端", city: "北京", education: "本科", jobType: "社招" };
  const result = jobFilterMatch(
    job({
      title: "高级软件工程师",
      location: "",
      education: "",
      job_type: null,
      jd_url: "https://boards.greenhouse.io/acme/jobs/2",
    }),
    filters,
  );

  assert.deepEqual(result, {
    tier: "related",
    keywordTier: "related",
    degradedFields: ["city", "type", "education"],
  });
});

test("countMatchBreakdown：keyword-related wins the related tie-break over missing info", () => {
  const filters = { ...base, keyword: "后端", city: "北京", education: "本科" };
  const ranked = filterAndRankJobs(
    [
      job({ id: "exact", title: "后端开发工程师", match_score: 30 }),
      job({ id: "same-function", title: "高级软件工程师", match_score: 20 }),
      job({ id: "missing-city", title: "后端开发工程师", location: "", match_score: 10 }),
      job({ id: "both", title: "高级软件工程师", location: "", education: "", match_score: 40 }),
    ],
    filters,
  );

  assert.deepEqual(countMatchBreakdown(ranked), {
    exact: 1,
    relatedSameFunction: 2,
    relatedMissingInfo: 1,
  });
  assert.deepEqual(
    ranked.find((j) => j.id === "both").__match.degradedFields,
    ["city", "education"],
  );
});

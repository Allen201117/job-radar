const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

const ROOT = path.join(__dirname, "..");

function loadTsWithMocks(absPath, mocks = {}, cache = new Map()) {
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
    if (spec === "server-only") return {};
    if (Object.prototype.hasOwnProperty.call(mocks, spec)) return mocks[spec];

    let base = null;
    if (spec.startsWith("@/")) base = path.join(ROOT, spec.slice(2));
    else if (spec.startsWith(".")) base = path.resolve(dir, spec);

    if (base) {
      const tsPath = base.endsWith(".ts") ? base : `${base}.ts`;
      if (fs.existsSync(tsPath)) return loadTsWithMocks(tsPath, mocks, cache);
      const jsPath = base.endsWith(".js") ? base : `${base}.js`;
      if (fs.existsSync(jsPath)) return baseRequire(jsPath);
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

const filters = {
  company: "",
  city: "",
  jobType: "",
  keyword: "",
  showIgnored: true,
  showApplied: true,
  showNewOnly: false,
  sortBy: "match",
  capitalOrigin: "",
  region: "",
  salaryOnly: false,
  sponsorshipOnly: false,
  education: "",
};

const prefs = {
  id: "pref-1",
  user_id: "user-1",
  target_locations: [],
  target_roles: ["产品经理"],
  target_keywords: [],
  exclude_keywords: [],
  target_companies: [],
  daily_limit: 20,
};

function job(overrides = {}) {
  const id = overrides.id || "job-1";
  return {
    id,
    source_id: null,
    company: "Acme",
    title: "行政助理",
    location: "北京",
    country_code: "CN",
    job_scope: "domestic",
    job_type: "社招",
    summary: "",
    sponsorship_signal: "unknown",
    jd_url: `https://example.com/${id}`,
    apply_url: null,
    salary_text: null,
    posted_at: "2020-01-01T00:00:00.000Z",
    experience: null,
    education: null,
    deadline: null,
    first_seen_at: "2020-01-01T00:00:00.000Z",
    last_seen_at: "2020-01-01T00:00:00.000Z",
    status: "active",
    content_hash: null,
    created_at: "2020-01-01T00:00:00.000Z",
    ...overrides,
  };
}

function loadJobsStore(jobsQuery) {
  return loadTsWithMocks(path.join(ROOT, "lib", "jobs-store", "search.ts"), {
    "./client": { jobsQuery },
  });
}

test("jobs-store FTS city predicate keeps empty locations and bidirectional city aliases", async () => {
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql, params) => {
    calls.push({ sql, params });
    return [];
  });

  await searchJobsStore({ ...filters, keyword: "产品经理", city: "北京" }, null, [], 0, 10);

  assert.equal(calls.length, 1);
  assert.match(calls[0].sql, /location is null or location = ''/i);
  assert.match(calls[0].sql, /location ilike \$\d+/i);
  assert.ok(calls[0].params.includes("%北京%"));
  assert.ok(calls[0].params.includes("%beijing%"));
  assert.doesNotMatch(calls[0].sql, /location ilike \$\d+\s+and/i);
});

test("jobs-store city-only search stays on FTS (全表覆盖) 且软城市仍保留空 location 行", async () => {
  // 城市留在 tsquery → 走 FTS 全表 GIN，而非只扫最新 28k 的 scan（后者实测只覆盖 ~6% 城市岗）。
  // 同时 appendSoftCityWhere 的 OR 组保住「命中该城的空 location 行」→ JS matcher 标为 city 降级。
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql, params) => {
    calls.push({ sql, params });
    return [job({ id: "missing-city", location: "" })];
  });

  const result = await searchJobsStore({ ...filters, city: "北京" }, null, [], 0, 1);

  assert.match(calls[0].sql, /search_doc @@/i); // FTS 全表覆盖，不退化到 scan
  assert.doesNotMatch(calls[0].sql, /order by first_seen_at desc/i);
  assert.match(calls[0].sql, /location is null or location = ''/i); // 软城市 OR 组仍在
  assert.ok(calls[0].params.includes("%beijing%")); // 双向别名
  assert.equal(result.jobs[0].id, "missing-city");
  assert.deepEqual(result.jobs[0].__match.degradedFields, ["city"]);
});

test("jobs-store scan keeps scanning the budget before match ranking", async () => {
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql, params) => {
    const off = params[params.length - 1];
    calls.push(off);
    if (off === 0) {
      return Array.from({ length: 1000 }, (_, i) => job({ id: `low-${i}` }));
    }
    if (off === 1000) {
      return [job({ id: "high", title: "产品经理" })];
    }
    return [];
  });

  const result = await searchJobsStore({ ...filters, sortBy: "match" }, prefs, [], 0, 1);

  assert.deepEqual(calls, [0, 1000]);
  assert.equal(result.jobs[0].id, "high");
  assert.equal(result.jobs[0].match_score, 30);
});

test("jobs-store scan still stops early for newest ranking", async () => {
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql, params) => {
    const off = params[params.length - 1];
    calls.push(off);
    if (off === 0) return Array.from({ length: 1000 }, (_, i) => job({ id: `new-${i}` }));
    return [job({ id: "older", title: "产品经理" })];
  });

  const result = await searchJobsStore({ ...filters, sortBy: "newest" }, prefs, [], 0, 1);

  assert.deepEqual(calls, [0]);
  assert.equal(result.jobs[0].id, "new-0");
});

function supabaseFtsMock() {
  const calls = { or: [], ilike: [] };
  class Query {
    select() {
      return this;
    }
    eq() {
      return this;
    }
    textSearch() {
      return this;
    }
    or(expr) {
      calls.or.push(expr);
      return this;
    }
    ilike(column, value) {
      calls.ilike.push([column, value]);
      return this;
    }
    async range() {
      return { data: [], error: null };
    }
  }
  return {
    calls,
    from(table) {
      assert.equal(table, "jobs");
      return new Query();
    },
  };
}

test("Supabase FTS city predicate uses one soft-city .or group", async () => {
  const supabase = supabaseFtsMock();
  const { searchJobs } = loadTsWithMocks(path.join(ROOT, "lib", "job-search.ts"));

  await searchJobs(supabase, { ...filters, keyword: "产品经理", city: "北京" }, null, [], 0, 10);

  assert.equal(supabase.calls.or.length, 1);
  assert.match(supabase.calls.or[0], /location\.is\.null/);
  assert.match(supabase.calls.or[0], /location\.eq\./);
  assert.match(supabase.calls.or[0], /location\.ilike\.%北京%/);
  assert.match(supabase.calls.or[0], /location\.ilike\.%beijing%/);
  assert.deepEqual(supabase.calls.ilike, []);
});

function supabaseScanMock(pageForOffset) {
  const ranges = [];
  class Query {
    select() {
      return this;
    }
    eq() {
      return this;
    }
    order() {
      return this;
    }
    async range(from) {
      ranges.push(from);
      return { data: pageForOffset(from), error: null };
    }
  }
  return {
    ranges,
    from(table) {
      assert.equal(table, "jobs");
      return new Query();
    },
  };
}

test("Supabase scan keeps scanning later batches before match ranking", async () => {
  const supabase = supabaseScanMock((off) => {
    if (off < 4000) return Array.from({ length: 1000 }, (_, i) => job({ id: `low-${off}-${i}` }));
    if (off === 4000) return [job({ id: "high", title: "产品经理" })];
    return [];
  });
  const { searchJobs } = loadTsWithMocks(path.join(ROOT, "lib", "job-search.ts"));

  const result = await searchJobs(supabase, { ...filters, sortBy: "match" }, prefs, [], 0, 1);

  assert.ok(supabase.ranges.includes(4000));
  assert.equal(result.jobs[0].id, "high");
  assert.equal(result.jobs[0].match_score, 30);
});

test("jobs-store 多城市：tsquery OR 组 + 软城市 OR 覆盖所有选中城市的别名", async () => {
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql, params) => {
    calls.push({ sql, params });
    return [];
  });

  await searchJobsStore({ ...filters, city: "北京,上海" }, null, [], 0, 10);

  assert.equal(calls.length, 1);
  // FTS 全表覆盖（不退化 scan），tsquery 里城市是 OR 组（含两城 bigram）
  assert.match(calls[0].sql, /search_doc @@/i);
  assert.match(String(calls[0].params[0]), /北京/);
  assert.match(String(calls[0].params[0]), /上海/);
  assert.match(String(calls[0].params[0]), /\|/); // 城市之间 OR
  // 软城市 OR 组保留空 location + 两城别名/拼音
  assert.match(calls[0].sql, /location is null or location = ''/i);
  assert.ok(calls[0].params.includes("%beijing%"));
  assert.ok(calls[0].params.includes("%shanghai%"));
});

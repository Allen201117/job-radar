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

test("jobs-store pushes postedWithin into parameterized SQL", async () => {
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql, params) => {
    calls.push({ sql, params });
    return [];
  });

  await searchJobsStore({ ...filters, postedWithin: "7", keyword: "产品经理" }, null, [], 0, 10);

  assert.match(calls[0].sql, /posted_at >= now\(\) - \(\$\d+::int \* interval '1 day'\)/i);
  assert.ok(calls[0].params.includes(7));
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

// 候选取数调用与「命中页回补展示列」的调用要分开看：回补走 `where id in (...)`，
// 末位参数是 id 而不是 offset，所以按类型区分（数字=候选取数的 offset，字符串=回补）。
function splitScanCalls(calls) {
  return {
    pageOffsets: calls.filter((c) => typeof c === "number"),
    hydrated: calls.filter((c) => typeof c === "string"),
  };
}

test("jobs-store scan takes the whole match budget in ONE query", async () => {
  const calls = [];
  const limits = [];
  const { searchJobsStore } = loadJobsStore(async (sql, params) => {
    const off = params[params.length - 1];
    calls.push(off);
    // 候选取数的参数是 [...where, limit, offset]（offset 是数字）；回补是 where id in (...)（全是 id 字符串）。
    if (typeof off === "number") limits.push(params[params.length - 2]);
    if (off !== 0) return [];
    // 高分岗排在这一大批的靠后位置：只看头 1000 行是找不到它的。
    return [
      ...Array.from({ length: 1000 }, (_, i) => job({ id: `low-${i}` })),
      job({ id: "high", title: "产品经理" }),
    ];
  });

  const result = await searchJobsStore({ ...filters, sortBy: "match" }, prefs, [], 0, 1);

  const { pageOffsets, hydrated } = splitScanCalls(calls);
  // match 必须看满预算才能按分排序 → 一次查完，**不再 OFFSET 翻页**。
  // 翻页是移植 PostgREST(单次上限 1000 行)时留下的阑尾，直连 pg 没有该上限。
  // 实测（热缓存）：28 次翻页累计 679ms vs 单查询 45~73ms。
  // ⚠️ 也别改成并行取页：实测并发 8/16 会让 pg 池抛 connect timeout(500)、并发 3 则
  // 从 25s 恶化到 32s（香港库仅 2 vCPU，扫描是 DB 端 CPU 密集活，并发只是互抢）。
  assert.deepEqual(pageOffsets, [0]);
  assert.deepEqual(limits, [28000]); // SCAN_BUDGET，一次取满
  // 排序仍跨整批生效：高分岗在第 1001 位也要被排到最前。
  assert.equal(result.jobs[0].id, "high");
  assert.equal(result.jobs[0].match_score, 30);
  // 候选阶段不拉展示列 → 命中页必须回补一次，否则前端拿不到 deadline/canonical_jd_url 等。
  assert.deepEqual(hydrated, ["high"]);
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

  // newest 攒够 need 就能停 → 保持串行逐页，**不得**为了并行白拉后面几页（只翻 1 页）。
  const { pageOffsets, hydrated } = splitScanCalls(calls);
  assert.deepEqual(pageOffsets, [0]);
  assert.deepEqual(hydrated, ["new-0"]);
  assert.equal(result.jobs[0].id, "new-0");
});

test("jobs-store scan caches candidates across requests and dedupes concurrent ones", async () => {
  let candidateFetches = 0;
  const { searchJobsStore } = loadJobsStore(async (sql, params) => {
    // 候选取数的末位参数是 offset(数字)；命中页回补走 `where id in (...)`，参数是 id(字符串)。
    if (typeof params[params.length - 1] === "number") candidateFetches += 1;
    return [job({ id: "a", title: "产品经理" })];
  });

  const args = [{ ...filters, sortBy: "match" }, prefs, [], 0, 1];

  // 并发两发：候选与用户无关 → in-flight 去重，只应打库一次。
  const [r1, r2] = await Promise.all([
    searchJobsStore(...args),
    searchJobsStore(...args),
  ]);
  assert.equal(candidateFetches, 1, "并发相同搜索应只取一次候选");

  // 再来一发（TTL 内）→ 命中缓存，仍是一次。
  const r3 = await searchJobsStore(...args);
  assert.equal(candidateFetches, 1, "TTL 内重复搜索应命中缓存");

  // 结果必须与没有缓存时完全一致（缓存只省传输，不改语义）。
  for (const r of [r1, r2, r3]) {
    assert.equal(r.jobs[0].id, "a");
    assert.equal(r.total, 1);
  }

  // 换求职范围 → where/params 变了 → 必须重新取，不能错用上一份候选。
  await searchJobsStore({ ...filters, sortBy: "match" }, { ...prefs, job_scope: "overseas" }, [], 0, 1);
  assert.equal(candidateFetches, 2, "求职范围不同的候选不得复用");
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

test("jobs-store 校招：SQL 下推校招超集预筛（job_type/url/正文/公司 信号）", async () => {
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql, params) => { calls.push({ sql, params }); return []; });
  await searchJobsStore({ ...filters, jobType: "校招", keyword: "产品经理" }, null, [], 0, 10);
  assert.equal(calls.length, 1);
  assert.match(calls[0].sql, /应届/);
  assert.match(calls[0].sql, /xiaozhao\|campus/);
  assert.match(calls[0].sql, /校园招聘/);
  // 安全剔除「job_type 自报社招」（这些在 JS 里必是社招/实习，绝不会是校招）
  assert.match(calls[0].sql, /job_type is null or job_type !~\* '\(社招/);
});

// 校招查询里剔掉实习：recruitmentCategory 的层1（实习）最先短路 → 命中它的岗绝不可能是校招。
// 香港库真实数据验过：深圳+校招 4354 条候选 → 3399 条（-22%），而 total 仍是 2275（结果零变化）。
test("jobs-store 校招：下推剔除实习，且 intern 必须两侧词边界", async () => {
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql, params) => { calls.push({ sql, params }); return []; });
  await searchJobsStore({ ...filters, jobType: "校招", keyword: "产品经理" }, null, [], 0, 10);
  const sql = calls[0].sql;

  assert.match(sql, /and not \(/, "校招下推必须带实习排除");
  // 逐字对齐 recruitmentCategory 层1 的三个来源：job_type / title / url 路径段。
  assert.match(sql, /coalesce\(job_type,''\) ~\* '\(实习\|/);
  assert.match(sql, /coalesce\(title,''\) ~ '\(实习\|shixi\)'/);
  assert.match(sql, /\/\(shixi\|intern\)\(\/\|/, "url 只认路径段");

  // ⚠️ 最关键的一条：intern 必须**两侧**词边界（PG 的 \y），否则 international / internal /
  // internet 会把全职岗当实习剔掉 —— 同款裸子串坑在 crawler 上实锤误标过 27,824 个岗。
  const internClauses = sql.match(/[^']*intern\(ship\)\?s\?[^']*/g) || [];
  assert.ok(internClauses.length >= 2, "应有 job_type / title 两处 intern 判定");
  for (const c of internClauses) {
    assert.ok(
      c.includes("\\yintern(ship)?s?\\y"),
      `intern 判定必须两侧词边界，实际是: ${c}`,
    );
  }
  // 反向：排除段里不许出现没有词边界的裸 intern。
  const notPart = sql.slice(sql.indexOf("and not ("));
  assert.doesNotMatch(
    notPart,
    /[^y(]intern\(ship\)\?s\?[^\\]/,
    "排除段里不许有裸 intern 子串",
  );
});

test("jobs-store 实习：SQL 下推实习超集预筛", async () => {
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql, params) => { calls.push({ sql, params }); return []; });
  await searchJobsStore({ ...filters, jobType: "实习", keyword: "产品经理" }, null, [], 0, 10);
  assert.match(calls[0].sql, /实习\|intern/);
  assert.match(calls[0].sql, /shixi/);
});

// 招聘类型已物化成 jobs.recruitment_category / recruitment_explicit（入库时由 JS 权威规则算好），
// 检索改查这两列 —— 与 job-filter.jobFilterMatch 逐字同义，不再是「正向信号并集」的近似超集。
// ⚠️ 三条不变量，破一条都会静默改坏筛选：
//   ① 选校招/实习 = 有明确依据 且 类型相符（无依据的岗 JS 淘汰，SQL 也必须淘汰）
//   ② 选社招 = 只淘汰「有依据且不是社招」（无依据的 JS 放行降级，SQL 也必须放行）
//   ③ recruitment_category is null =「还没算」≠「不是」→ 必须退回旧超集，否则新岗凭空消失
test("jobs-store 社招：只淘汰「有明确依据且不是社招」的岗", async () => {
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql, params) => { calls.push({ sql, params }); return []; });
  await searchJobsStore({ ...filters, jobType: "社招", keyword: "产品经理" }, null, [], 0, 10);
  const sql = calls[0].sql;
  assert.match(sql, /not \(recruitment_explicit and recruitment_category <> '社招'\)/);
  // 社招兜底路不下推任何信号（默认态·大头）：不该出现校招/实习的信号词。
  assert.doesNotMatch(sql, /应届|xiaozhao/);
});

test("jobs-store 招聘类型下推：查物化列，且 NULL 必须退回旧超集（新岗不能凭空消失）", async () => {
  for (const [jobType, want] of [["校招", "校招"], ["实习", "实习"]]) {
    const calls = [];
    const { searchJobsStore } = loadJobsStore(async (sql, params) => { calls.push({ sql, params }); return []; });
    await searchJobsStore({ ...filters, jobType, keyword: "产品经理" }, null, [], 0, 10);
    const sql = calls[0].sql;
    assert.match(
      sql,
      new RegExp(`recruitment_explicit and recruitment_category = '${want}'`),
      `${jobType} 应走物化列精确过滤`,
    );
    assert.match(
      sql,
      /recruitment_category is null and/,
      `${jobType} 必须保留 NULL 兜底路 —— 否则回填未覆盖/分类降级的新岗会从结果里消失`,
    );
    // 兜底路仍是旧的信号超集（宁可放宽不可收紧）。
    if (jobType === "校招") assert.match(sql, /应届/);
    if (jobType === "实习") assert.match(sql, /shixi/);
  }
});

test("jobs-store 命中页回补展示列：候选省传 canonical_jd_url，page 再补齐并合并", async () => {
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql) => {
    calls.push({ sql });
    if (/select id, content_hash/i.test(sql)) {
      return [{ id: "j1", deadline: "2025-12-31", canonical_jd_url: "https://x/canon" }];
    }
    return [job({ id: "j1", title: "产品经理" })];
  });
  const r = await searchJobsStore({ ...filters, keyword: "产品经理" }, null, [], 0, 10);
  const cand = calls.find((c) => !/content_hash/.test(c.sql));
  assert.doesNotMatch(cand.sql, /canonical_jd_url/); // 候选不拉最肥的展示列
  assert.equal(calls.length, 2); // 候选 + 命中页回补
  assert.equal(r.jobs[0].deadline, "2025-12-31"); // 回补生效
  assert.equal(r.jobs[0].canonical_jd_url, "https://x/canon");
});

// ── 候选缓存（FTS 与扫描两条路径共用）────────────────────────────────────────
// 候选取数是这个接口服务端耗时的绝大头（香港库实测 4354 行 ≈ 4.8MB；无筛选态 2.8 万行、
// 首次 TTFB 19s）。翻页是在 JS 里 slice 的 → 第 2 页的候选 SQL 与第 1 页逐字节相同，
// 不缓存就是把同一批行重拉一遍。下面钉死「该复用时复用、不该复用时绝不复用」。

const isCandidateSql = (sql) => /from jobs where status = 'active'/.test(sql);

test("同一筛选条件翻页复用候选缓存，候选 SQL 只发一次", async () => {
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql) => {
    calls.push(sql);
    return [];
  });
  const f = { ...filters, city: "深圳" };
  await searchJobsStore(f, null, [], 0, 60, null);
  await searchJobsStore(f, null, [], 60, 60, null); // 第 2 页：offset 只影响 JS slice
  assert.equal(calls.filter(isCandidateSql).length, 1, "第 2 页必须吃缓存，不该重发候选查询");
});

test("筛选条件不同 → 缓存 key 不同，绝不互相串味", async () => {
  const calls = [];
  const { searchJobsStore } = loadJobsStore(async (sql, params) => {
    calls.push({ sql, params });
    return [];
  });
  await searchJobsStore({ ...filters, city: "深圳" }, null, [], 0, 60, null);
  await searchJobsStore({ ...filters, city: "北京" }, null, [], 0, 60, null);
  const candidates = calls.filter((c) => isCandidateSql(c.sql));
  assert.equal(candidates.length, 2, "换城市必须另发一次查询");
  assert.notDeepEqual(candidates[0].params, candidates[1].params);
});

test("并发同一查询只打一次库（in-flight 去重）", async () => {
  let hits = 0;
  const { searchJobsStore } = loadJobsStore(async (sql) => {
    if (isCandidateSql(sql)) hits += 1;
    await new Promise((r) => setTimeout(r, 5));
    return [];
  });
  const f = { ...filters, city: "广州" };
  await Promise.all([
    searchJobsStore(f, null, [], 0, 60, null),
    searchJobsStore(f, null, [], 0, 60, null),
    searchJobsStore(f, null, [], 0, 60, null),
  ]);
  assert.equal(hits, 1, "三个并发请求应共享同一次取数");
});

test("超行数预算时淘汰最旧的一份，而不是把缓存整体清空", async () => {
  const calls = [];
  const bulk = (n, city) =>
    Array.from({ length: n }, (_, i) => job({ id: `${city}-${i}`, location: city }));
  const { searchJobsStore } = loadJobsStore(async (sql, params) => {
    calls.push(sql);
    if (!isCandidateSql(sql)) return [];
    return bulk(40000, String(params[1] || "").replace(/%/g, "") || "x");
  });
  // 预算 60000 行：A(4 万) 装得下；B(4 万) 进来后 A 必须被挤掉；再查 B 仍应命中缓存。
  const A = { ...filters, city: "深圳" };
  const B = { ...filters, city: "北京" };
  await searchJobsStore(A, null, [], 0, 1, null);
  await searchJobsStore(B, null, [], 0, 1, null);
  const before = calls.filter(isCandidateSql).length;
  await searchJobsStore(B, null, [], 0, 1, null); // 最近写入的 B 应还在
  assert.equal(calls.filter(isCandidateSql).length, before, "B 应命中缓存");
  await searchJobsStore(A, null, [], 0, 1, null); // A 已被挤掉 → 重新取数
  assert.equal(calls.filter(isCandidateSql).length, before + 1, "A 应已被淘汰、需重取");
});

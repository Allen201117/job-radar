const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

// 候选撞取数上限时，total 只是「取到这么多」。这里钉死「什么时候允许用 SQL count 报真实总数、
// 什么时候必须弃权」——弃权比给错数字重要：给错数字比现在（把上限当真实值）更糟。
const ROOT = path.join(__dirname, "..");
const FTS_CAP = 8000;

function loadSearch() {
  // 共享 cache，才能在 search.ts 拿到 client 之前把 jobsQuery 换成桩。
  const cache = new Map();
  const client = loadTs(path.join(ROOT, "lib", "jobs-store", "client.ts"), cache);
  const search = loadTs(path.join(ROOT, "lib", "jobs-store", "search.ts"), cache);
  const { DEFAULT_FILTERS } = loadTs(path.join(ROOT, "lib", "job-filter.ts"), cache);
  const { companyTierPatterns } = loadTs(path.join(ROOT, "lib", "company-tiers.ts"), cache);
  search.__resetScanCache();
  const calls = [];
  const install = ({ candidates, count, hiddenCount }) => {
    client.jobsQuery = async (sql, params) => {
      calls.push({ sql, params });
      // 用户隐藏岗那部分（按主键取，2026-09-23 起从共享计数里拆出来单算）
      if (/^select count\(\*\)/.test(sql) && / and id = any\(/.test(sql)) return [hiddenCount || { total: 0, unclassified: 0 }];
      if (/^select count\(\*\)/.test(sql)) return count ? [count] : [];
      // ④ 的前置存在性查询（选了招聘类型才发）：与计数查询同一份 where，只问「有没有未分类的行」。
      if (/^select exists\(/.test(sql)) return count ? [{ pending: count.unclassified > 0 }] : [];
      if (/^select id, content_hash/.test(sql)) return []; // 命中页回补展示列
      return candidates;
    };
  };
  return { search, DEFAULT_FILTERS, calls, install, companyTierPatterns };
}

const CAMPUS = { title: "后端开发（2027届校招）", recruitment_category: "校招", recruitment_explicit: true };
const countQueries = (calls) => calls.filter((c) => /^select count\(\*\)/.test(c.sql));

function candidateRows(n, overrides = {}) {
  return Array.from({ length: n }, (_, i) => ({
    id: `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
    source_id: "s1",
    company: "某公司",
    title: "后端工程师",
    location: "深圳",
    summary: "负责服务端开发",
    status: "active",
    first_seen_at: "2026-09-01T00:00:00Z",
    posted_at: "2026-09-01T00:00:00Z",
    ...overrides,
  }));
}

test("只用筛选器（条件全部下推）+ 撞上限 → 用 SQL count 报真实总数", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: { total: 15290, unclassified: 0 } });

  const r = await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳", jobType: "社招" },
    null,
    [],
    0,
    60,
  );
  assert.equal(r.capped, true);
  assert.equal(r.total, FTS_CAP, "total 仍是可翻页的条数，翻页逻辑不能被真实总数带偏");
  assert.equal(r.exactTotal, 15290);
  assert.equal(countQueries(calls).length, 1);
});

test("有只能在 JS 里判的条件（关键词）→ 不发计数查询，也不给数字", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: { total: 15290, unclassified: 0 } });

  const r = await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳", keyword: "后端" },
    null,
    [],
    0,
    60,
  );
  assert.equal(r.capped, true);
  assert.equal(r.exactTotal, null);
  assert.equal(countQueries(calls).length, 0, "算不准就别去查，白花一次跨库往返");
});

test("候选里有被 JS 淘汰的行 = 等价性已漂 → 运行时自检兜住，不给数字", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  // 桩不理会 where，硬塞一条外地岗：真实的候选 where 不会返回它，出现了就说明「where ⇒ JS 放行」不成立。
  const rows = candidateRows(FTS_CAP);
  rows[0] = { ...rows[0], location: "北京" };
  install({ candidates: rows, count: { total: 15290, unclassified: 0 } });

  const r = await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳", jobType: "社招" },
    null,
    [],
    0,
    60,
  );
  assert.equal(r.total, FTS_CAP - 1);
  assert.equal(r.exactTotal, null);
  assert.equal(countQueries(calls).length, 0);
});

test("结果集里还有招聘类型未分类的行 → 兜底分支不是充分条件，弃权", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  // 候选必须是 JS 也判为校招的行，否则自检门③ 先弃权，根本走不到 ④（此前这条用例就是被 ③ 挡住的）。
  install({ candidates: candidateRows(FTS_CAP, CAMPUS), count: { total: 15290, unclassified: 7 } });

  const r = await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳", jobType: "校招" },
    null,
    [],
    0,
    60,
  );
  assert.equal(r.exactTotal, null);
  // 2026-09-23：先问「有没有未分类的行」，有就不再跑全表 count——那个数算完也会被 ④ 丢掉
  // （/campus 默认态每次白跑 0.6~2.4s）。存在性查询与计数用同一份 where、同一份参数。
  const ex = calls.find((c) => /^select exists\(/.test(c.sql));
  assert.ok(ex, "选了招聘类型时应先发存在性查询");
  assert.match(ex.sql, / and recruitment_category is null\) as pending$/);
  assert.equal(countQueries(calls).length, 0, "已知要弃权，就别再数");
});

test("选了招聘类型但没有未分类的行 → 照常计数；存在性查询与计数的 where / 参数逐字相同", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP, CAMPUS), count: { total: 15290, unclassified: 0 } });

  const r = await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳", jobType: "校招" },
    null,
    [],
    0,
    60,
  );
  assert.equal(r.exactTotal, 15290);
  const ex = calls.find((c) => /^select exists\(/.test(c.sql));
  const [cnt] = countQueries(calls);
  assert.ok(ex && cnt);
  const whereOf = (sql) => sql.match(/from jobs where (.*?)( and recruitment_category is null\) as pending)?$/)[1];
  assert.equal(whereOf(ex.sql), whereOf(cnt.sql));
  assert.deepEqual(ex.params, cnt.params);
});

test("没选招聘类型 → 不发存在性查询（④ 只对招聘类型生效）", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: { total: 15290, unclassified: 3 } });
  const r = await search.searchJobsStore({ ...DEFAULT_FILTERS, city: "深圳" }, null, [], 0, 60);
  assert.equal(r.exactTotal, 15290);
  assert.equal(calls.filter((c) => /^select exists\(/.test(c.sql)).length, 0);
});

// 2026-09-17 起排除词下推 SQL（appendExcludeWhere，与 scoreJob 同字段集 title+summary）：候选与计数用同一份 where，
// 不再因「SQL 看不到 JD 正文」弃权；口径若漂，运行时自检门③ 仍会兜住。
test("用户设了 exclude_keywords → 候选与计数的 where 都带排除条件，计数照常给确定数字", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: { total: 15290, unclassified: 0 } });

  const r = await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳" },
    { exclude_keywords: ["外包"], target_roles: [], target_keywords: [] },
    [],
    0,
    60,
  );
  assert.equal(r.exactTotal, 15290);
  const [countCall] = countQueries(calls);
  assert.ok(countCall, "应发出计数查询");
  assert.match(countCall.sql, /not \(lower\(coalesce\(title, ''\) \|\| ' ' \|\| coalesce\(summary, ''\)\) like any\(\$\d+::text\[\]\)\)/);
  assert.ok(countCall.params.some((p) => Array.isArray(p) && p.includes("%外包%")));
  const candidateCall = calls.find((c) => /select .* from jobs where/.test(c.sql) && !/count\(\*\)/.test(c.sql));
  assert.ok(candidateCall.params.some((p) => Array.isArray(p) && p.includes("%外包%")), "候选查询也要带排除词");
});

test("被忽略/已投递的岗：总数 = 共享计数 − 隐藏岗落在条件内的条数；共享那条不带任何个人数据", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  const rows = candidateRows(FTS_CAP);
  const ignoredId = rows[3].id;
  install({ candidates: rows, count: { total: 15291, unclassified: 0 }, hiddenCount: { total: 1, unclassified: 0 } });

  const r = await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳" },
    { exclude_keywords: [], target_roles: [], target_keywords: [] },
    [{ id: "a1", user_id: "u", job_id: ignoredId, action: "ignored", created_at: "2026-09-01T00:00:00Z" }],
    0,
    60,
  );
  assert.equal(r.total, FTS_CAP - 1, "被忽略的岗不进结果");
  assert.equal(r.exactTotal, 15290, "15,291 − 1");
  const shared = countQueries(calls).find((c) => !/ id = any\(/.test(c.sql));
  const own = countQueries(calls).find((c) => / and id = any\(\$\d+::uuid\[\]\)$/.test(c.sql));
  assert.ok(shared && own, JSON.stringify(countQueries(calls).map((c) => c.sql)));
  // 共享计数的键（sql + params）里不许有任何个人数据，否则跨用户共享不了。
  assert.ok(!JSON.stringify(shared.params).includes(ignoredId));
  assert.doesNotMatch(shared.sql, /not \(id = any/);
  // 隐藏部分：同一份 where + 只按主键取这个用户的隐藏岗。
  assert.deepEqual(own.params[own.params.length - 1], [ignoredId]);
  assert.deepEqual(own.params.slice(0, -1), shared.params);
  assert.equal(own.sql.replace(/ and id = any\(\$\d+::uuid\[\]\)$/, ""), shared.sql);
});

test("没撞上限 → 根本不查计数，total 本来就是真实值", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(120), count: { total: 999, unclassified: 0 } });

  const r = await search.searchJobsStore({ ...DEFAULT_FILTERS, city: "深圳" }, null, [], 0, 60);
  assert.equal(r.capped, false);
  assert.equal(r.total, 120);
  assert.equal(r.exactTotal, null);
  assert.equal(countQueries(calls).length, 0);
});

test("计数查询自己挂了也不能拖垮搜索", async () => {
  const { search, DEFAULT_FILTERS, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: null });
  const r = await search.searchJobsStore({ ...DEFAULT_FILTERS, city: "深圳" }, null, [], 0, 60);
  assert.equal(r.exactTotal, null, "count 返回空行时按弃权处理");
  assert.equal(r.jobs.length, 60);
});


// ── 候选窗口的排序：决定「装不下时砍掉谁」。之前 FTS 那条查询根本没有 order by，
// 撞上限时拿到的是任意一批 → 「按匹配度」的第一页只是「任意一批里最匹配的」。 ──

const prefsWith = (over = {}) => ({
  target_roles: [],
  target_keywords: [],
  skills: [],
  target_companies: [],
  target_locations: [],
  exclude_keywords: [],
  ...over,
});

/** 取候选那条 SQL（排除计数 / 回补展示列两条）。 */
const candidateSql = (calls) =>
  calls.find((c) => /^select id, source_id/.test(c.sql));

test("按匹配度排：偏好命中的岗优先进窗口，再按新鲜度补满", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: null });

  await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳" },
    prefsWith({ target_roles: ["后端工程师"], target_locations: ["深圳"] }),
    [],
    0,
    60,
  );
  const c = candidateSql(calls);
  // 2026-09-18 起登录 match 的 FTS 路径也走 SQL 粗排（方向 30 + … + 7 天内 10）+ 1000 窗口，
  // 不再一次拉满 FTS_CAP=8000 再 JS 全打分（线上账本 fetch 1.4s + score 1.6s）。
  assert.match(
    c.sql,
    /order by \(\(\(search_doc @@ to_tsquery\('simple', \$\d+\)\) is true\)::int \* 30 \+ .*\) desc, first_seen_at desc, id limit 1000$/,
    "偏好命中优先 + 新鲜度补位（粗排键 + 1000 窗口）",
  );
  // 城市已被筛选锁定 → 粗排键里不该再有城市项（常量项等于没排）。
  assert.doesNotMatch(c.sql, /location ilike any/);
  // 偏好词要真的被展开成 tsquery 传下去，不能是空的。
  const prefQuery = c.params[c.params.length - 1];
  assert.equal(typeof prefQuery, "string");
  assert.ok(prefQuery.includes("后端") || prefQuery.includes("工程"), prefQuery);
});

test("FTS 路径：运维开关 JOBS_MATCH_PRESCORE=off 退回旧的全窗形态", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: null });
  process.env.JOBS_MATCH_PRESCORE = "off";
  try {
    await search.searchJobsStore(
      { ...DEFAULT_FILTERS, city: "深圳" },
      prefsWith({ target_roles: ["后端工程师"] }),
      [],
      0,
      60,
    );
  } finally {
    delete process.env.JOBS_MATCH_PRESCORE;
  }
  const c = candidateSql(calls);
  assert.match(c.sql, /order by \(search_doc @@ to_tsquery\('simple', \$\d+\)\) desc, first_seen_at desc, id limit 8000$/);
});

test("按发布时间排：只按新鲜度截断——窗口内的分页与全集一致", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: null });

  await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳", sortBy: "newest" },
    prefsWith({ target_roles: ["后端工程师"] }),
    [],
    0,
    60,
  );
  const c = candidateSql(calls);
  assert.match(c.sql, /order by first_seen_at desc, id limit/);
  assert.doesNotMatch(c.sql, /to_tsquery\('simple', \$\d+\)\) desc/);
});

// 2026-09-23：有偏好记录、但一个粗排信号都没有（没填岗位名/城市/公司）的登录用户，与匿名同一回事 →
// 同样只取 1000 窗。此前只认 `!prefs`，这类用户「北京 + 实习」反而拉满 8000 行 5.6 MB。
test("FTS 路径：偏好里没有任何粗排信号 + 按匹配度 → 与匿名同用 1000 窗", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(1000), count: null });
  await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "北京", jobType: "实习" },
    prefsWith({ job_scope: "all" }),
    [],
    0,
    60,
  );
  assert.match(candidateSql(calls).sql, /order by first_seen_at desc, id limit 1000$/);
});

test("FTS 路径：没信号但按发布时间排 / 开关 off → 保持 8000 窗（这两种都不能归并成匿名）", async () => {
  for (const [label, filters, env] of [
    ["newest", { city: "北京", sortBy: "newest" }, null],
    ["JOBS_MATCH_PRESCORE=off", { city: "北京" }, "off"],
  ]) {
    const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
    install({ candidates: candidateRows(FTS_CAP), count: null });
    if (env) process.env.JOBS_MATCH_PRESCORE = env;
    try {
      await search.searchJobsStore({ ...DEFAULT_FILTERS, ...filters }, prefsWith(), [], 0, 60);
    } finally {
      delete process.env.JOBS_MATCH_PRESCORE;
    }
    assert.match(candidateSql(calls).sql, /limit 8000$/, label);
  }
});

test("没有偏好时按新鲜度排——此时打分只剩「近 7 天 +10」，这就是正确排序", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: null });

  await search.searchJobsStore({ ...DEFAULT_FILTERS, city: "深圳" }, null, [], 0, 60);
  assert.match(candidateSql(calls).sql, /order by first_seen_at desc, id limit/);
});

test("⚠️ 排序参数绝不能混进计数查询的绑定参数（多一个 PG 直接报错）", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: { total: 15290, unclassified: 0 } });

  const r = await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳", jobType: "社招" },
    prefsWith({ target_roles: ["后端工程师"] }),
    [],
    0,
    60,
  );
  assert.equal(r.exactTotal, 15290, "计数仍要能算出来");
  const cand = candidateSql(calls);
  const cnt = countQueries(calls)[0];
  // 候选查询比计数查询只多「候选专属」的参数：正文门（目标职能数组，2026-09-17 起）+ 偏好 tsquery（最后一个）。
  // 计数用的 where 参数必须是候选参数的**前缀**，多余的一个都不能进计数查询。
  const extras = cand.params.slice(cnt.params.length);
  assert.deepEqual(cand.params.slice(0, cnt.params.length), cnt.params);
  // 候选专属参数 = 粗排用的城市/公司数组 + 排序 tsquery（2026-09-17 起登录 match 不传正文，没有职能数组了）
  assert.ok(extras.length >= 1, "候选查询至少多带排序 tsquery");
  assert.equal(typeof extras[extras.length - 1], "string", "最后一个候选专属参数是排序 tsquery");
  // 计数 SQL 里出现的最大占位符编号不能超过它自己带的参数个数。
  const maxPlaceholder = Math.max(
    0,
    ...[...cnt.sql.matchAll(/\$(\d+)/g)].map((m) => Number(m[1])),
  );
  assert.ok(
    maxPlaceholder <= cnt.params.length,
    `计数 SQL 用到 $${maxPlaceholder} 但只传了 ${cnt.params.length} 个参数`,
  );
});

test("扫描路径（无筛选）同样按偏好优先截断", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(200), count: null });

  await search.searchJobsStore(
    { ...DEFAULT_FILTERS },
    prefsWith({ target_roles: ["产品经理"] }),
    [],
    0,
    60,
  );
  const c = candidateSql(calls);
  // 登录 + match：粗排键 = 方向 30 + 城市 20 + 公司 15 + 7 天内 10（prescoreOrderBy），排序 tsquery 仍是最后一个偏好参数
  assert.match(c.sql, /order by \(\(\(search_doc @@ to_tsquery\('simple', \$\d+\)\) is true\)::int \* 30 \+ .*\) desc, first_seen_at desc/);
  // 每一项都必须 `is true`：NULL 参与求和会让整行排到最前（NULLS FIRST）
  const pieces = (c.sql.match(/::int \* \d+/g) || []).length;
  assert.equal((c.sql.match(/ is true\)::int/g) || []).length, pieces, "每个粗排项都要 is true（NULL 会排到最前）");
  assert.ok(pieces >= 2);
  assert.match(c.sql, /first_seen_at > now\(\) - interval '7 days'/);
  // 候选查询必须带「方向 GIN 命中 OR 7 天内」的收窄条件（2026-09-18：不带它是全表扫，库上 2.3~2.6s；带上走 BitmapOr 493ms），
  // 且引用的占位符就是排序用的那个 tsquery 参数。
  const m = c.sql.match(/where .* and \(search_doc @@ to_tsquery\('simple', \$(\d+)\) or first_seen_at > now\(\) - interval '7 days'\) order by/);
  assert.ok(m, `候选 SQL 缺少方向/7 天收窄条件：${c.sql}`);
  const narrow = c.params[Number(m[1]) - 1];
  assert.equal(typeof narrow, "string", "收窄条件引用的必须是 tsquery 参数");
  // 收窄用的是**未扩展**的原始方向词（每个角色一条 AND 短语），不是排序那个经词表扩展的宽查询：
  // 宽查询上百个 OR 子句会让规划器放弃 GIN 走全表扫（2026-09-18 真实账号 236 子句 → 6.5s）。
  const wide = c.params[c.params.length - 3];
  assert.notEqual(narrow, wide, "收窄 tsquery 不能复用排序的宽查询");
  // 收窄 = 岗位名 ∪ 非泛化扩展 ⊆ 宽查询的词集：子句数不多于宽查询，且泛词（如「产品」单独一词）不在其中。
  assert.ok(narrow.split("|").length <= wide.split("|").length, `收窄 tsquery 子句不该多于宽查询：${narrow}`);
  // 「前缀 + 角色名」的词，接缝 bigram「品经」换成「接缝或职级插词」（产品高级经理，见 tests/fts-seniority-infix）。
  assert.ok(narrow.includes("产品 & 经理 & (品经 |"), `岗位名本身必须保留在收窄条件里：${narrow}`);
  assert.ok(!/\(产品\)/.test(narrow), `泛词「产品」不该进收窄条件：${narrow}`);
  // 收窄条件只进候选查询，不进计数（总数口径不变）。
  for (const q of countQueries(calls)) assert.doesNotMatch(q.sql, /interval '7 days'\)/);
  // 窗口不再是 28000 整窗
  assert.ok(c.params[c.params.length - 2] <= 1000, `登录 match 窗口应 ≤1000，拿到 ${c.params[c.params.length - 2]}`);
  assert.match(c.sql, /null::text as summary/, "登录 match 候选不传正文");
  // limit / offset 的占位符要排在偏好参数之后，编号别串位。
  assert.match(c.sql, /limit \$(\d+) offset \$(\d+)/);
  const [, lim, off] = c.sql.match(/limit \$(\d+) offset \$(\d+)/);
  assert.equal(Number(off), Number(lim) + 1);
  assert.equal(c.params.length, Number(off));
});

test("已被筛选锁定的维度不进优先级词——否则全部候选都算命中，等于没排", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: null });

  // 用户偏好里有「深圳」，而这次搜索就是按深圳筛的 → 候选全在深圳，城市这一维是常量。
  // live 实测踩过：带上它，15,350 个候选 100% 命中；剔除后降到 4,642，装得进 8000 的窗口。
  await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳", company: "腾讯" },
    prefsWith({
      target_roles: ["后端工程师"],
      target_locations: ["深圳"],
      target_companies: ["腾讯"],
    }),
    [],
    0,
    60,
  );
  const c = candidateSql(calls);
  const prefQuery = c.params[c.params.length - 1];
  assert.ok(prefQuery.includes("后端"), "方向词必须留下");
  assert.ok(!/shenzhen|深圳/i.test(prefQuery), `城市已被筛选锁定，不该进优先级词：${prefQuery}`);
  assert.ok(!/腾讯|tencent/i.test(prefQuery), `公司已被筛选锁定，不该进优先级词：${prefQuery}`);
});

test("没按城市/公司筛时，这两维仍有区分度 → 要进优先级词", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: null });

  await search.searchJobsStore(
    { ...DEFAULT_FILTERS, keyword: "后端" },
    prefsWith({ target_locations: ["深圳"], target_companies: ["腾讯"] }),
    [],
    0,
    60,
  );
  // 没有方向词时粗排键只剩城市 / 公司 / 7 天三项：城市、公司以 ilike 数组参数下推（不再拼进 tsquery）。
  const c = candidateSql(calls);
  const flat = c.params.flat().filter((v) => typeof v === "string");
  assert.match(c.sql, /location ilike any\(\$\d+::text\[\]\)\) is true\)::int \* 20/);
  assert.match(c.sql, /company ilike any\(\$\d+::text\[\]\)\) is true\)::int \* 15/);
  assert.ok(flat.some((v) => /深圳|shenzhen/i.test(v)), JSON.stringify(c.params));
  assert.ok(flat.some((v) => /腾讯|tencent/i.test(v)), JSON.stringify(c.params));
});

// ── companyTier 稀疏标签独立浏览：只选标签、不填 city/keyword/company → 落到 scan 路径。
// scan 路径必须像 FTS 路径一样把 companyTier 下推进候选 SQL，否则 sortBy=match 只看
// SCAN_BUDGET(=28000) 条「最新」行，稀疏标签（如初创独角兽/外企/大厂）的命中大多落在窗口外，
// 单靠 JS 事后过滤会把结果筛成近乎空集（不是计数不准，是真的漏岗）。 ──

test("companyTier 单独选中(无 city/keyword/company)→ 落到 scan 路径，仍要把 tier 下推 SQL", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(50), count: null });

  await search.searchJobsStore(
    { ...DEFAULT_FILTERS, companyTier: "初创独角兽" },
    null,
    [],
    0,
    60,
  );
  const c = candidateSql(calls);
  assert.match(
    c.sql,
    /company ilike \$\d+/,
    "scan 路径的候选查询必须包含 companyTier 的 ilike 下推，不能只留给 JS 事后过滤",
  );
});

test("companyTier=中小厂 单独选中也走 scan 路径的负向下推（not ilike all）", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(50), count: null });

  await search.searchJobsStore({ ...DEFAULT_FILTERS, companyTier: "中小厂" }, null, [], 0, 60);
  const c = candidateSql(calls);
  assert.match(c.sql, /company not ilike \$\d+/);
});

test("companyTier 下推：FTS 路径与 scan 路径共用同一份 patterns（parity，不允许各写一套漂移）", async () => {
  // FTS 路径（带 city，触发 tsquery）。
  const ftsRun = loadSearch();
  ftsRun.install({ candidates: candidateRows(50), count: null });
  await ftsRun.search.searchJobsStore(
    { ...ftsRun.DEFAULT_FILTERS, city: "深圳", companyTier: "外企" },
    null,
    [],
    0,
    60,
  );
  const ftsParams = candidateSql(ftsRun.calls).params;

  // scan 路径（无 city/keyword/company）。
  const scanRun = loadSearch();
  scanRun.install({ candidates: candidateRows(50), count: null });
  await scanRun.search.searchJobsStore(
    { ...scanRun.DEFAULT_FILTERS, companyTier: "外企" },
    null,
    [],
    0,
    60,
  );
  const scanParams = candidateSql(scanRun.calls).params;

  // 两条路径都必须把「外企」标签的全部 named patterns 作为绑定参数传下去，且完全一致，
  // 与 lib/company-tiers.companyTierPatterns 的输出同一份数据源（parity 的可验证证据）。
  const { named } = ftsRun.companyTierPatterns(["外企"]);
  for (const pattern of named) {
    assert.ok(ftsParams.includes(pattern), `FTS 路径缺少 tier pattern：${pattern}`);
    assert.ok(scanParams.includes(pattern), `scan 路径缺少 tier pattern：${pattern}`);
  }
});

test("匿名 + 按匹配度排：没有偏好就是纯新鲜度 → 走逐页路径攒够即停，不拉 SCAN_BUDGET 整窗", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(1000) });
  const result = await search.searchJobsStore({ ...DEFAULT_FILTERS, sortBy: "match" }, null, [], 0, 60);
  const candidateCalls = calls.filter((c) => /select .* from jobs where/.test(c.sql) && !/count\(\*\)/.test(c.sql) && !/^select id, content_hash/.test(c.sql));
  assert.ok(candidateCalls.length >= 1);
  for (const c of candidateCalls) {
    const limit = c.params[c.params.length - 2];
    assert.ok(limit <= 1000, `匿名 match 单次取数不该超过一页（拿到 limit=${limit}）`);
  }
  assert.equal(result.jobs.length, 60);
  assert.equal(result.timing.path, "scan");
});

// 2026-09-23：校招 / 实习 + 按新鲜度取（无粗排）→ 预筛拆成「已分类 / 待回填」两支各走索引再合并。
// 实习只占 active 6%，不拆就得按时间回表 2.9 万行才凑满 1000 行（冷缓存 2~4.6s）。
test("扫描路径：校招/实习无粗排 → 两支 union all，各自 order by first_seen_at limit，参数比普通形态多一个", async () => {
  for (const jobType of ["校招", "实习"]) {
    const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
    install({ candidates: candidateRows(200, { recruitment_category: jobType, recruitment_explicit: true }), count: null });
    await search.searchJobsStore({ ...DEFAULT_FILTERS, jobType }, null, [], 0, 60);
    const c = calls.find((x) => /^select \* from \(/.test(x.sql));
    assert.ok(c, `${jobType}：应走 union 形态`);
    const branches = c.sql.match(/\(select id, source_id.*? from jobs where (.*?) order by first_seen_at desc, id limit \$(\d+)\)/g);
    assert.equal(branches.length, 2, c.sql);
    assert.match(branches[0], new RegExp(`\\(recruitment_category is not null and recruitment_explicit and recruitment_category = '${jobType}'\\)`));
    assert.match(branches[1], /\(recruitment_category is null and /);
    for (const b of branches) assert.doesNotMatch(b, / or \(recruitment_category is null/, "每支只带自己那一半预筛");
    const [, lim, off] = c.sql.match(/\) u order by first_seen_at desc, id limit \$(\d+) offset \$(\d+)$/);
    const inner = Number(c.sql.match(/limit \$(\d+)\)/)[1]);
    assert.equal(c.params[inner - 1], c.params[Number(lim) - 1] + c.params[Number(off) - 1], "内层 limit = 外层 limit + offset");
    const used = new Set([...c.sql.matchAll(/\$(\d+)/g)].map((m) => Number(m[1])));
    for (let i = 1; i <= c.params.length; i++) assert.ok(used.has(i), `$${i} 被绑定但 SQL 没引用`);
  }
});

test("扫描路径：社招 / 有粗排 / 按匹配度有信号 → 不走 union（只在按时间翻的校招实习上拆）", async () => {
  for (const [label, filters, prefs] of [
    ["社招", { jobType: "社招" }, null],
    ["有方向词的校招（粗排路径）", { jobType: "校招" }, prefsWith({ target_roles: ["产品经理"] })],
  ]) {
    const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
    install({ candidates: candidateRows(200), count: null });
    await search.searchJobsStore({ ...DEFAULT_FILTERS, ...filters }, prefs, [], 0, 60);
    assert.ok(!calls.some((x) => /union all/.test(x.sql)), label);
  }
});

test("粗排收窄：选了校招/实习时按招聘类型拆成三支（逐行等价），不选时保持原样", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(200), count: null });
  await search.searchJobsStore({ ...DEFAULT_FILTERS, jobType: "实习" }, prefsWith({ target_roles: ["产品经理"] }), [], 0, 60);
  const c = candidateSql(calls);
  const m = c.sql.match(
    /and \(\(search_doc @@ to_tsquery\('simple', \$(\d+)\) and recruitment_category = '实习'\) or \(first_seen_at > now\(\) - interval '7 days' and recruitment_category = '实习'\) or \(recruitment_category is null and \(search_doc @@ to_tsquery\('simple', \$(\d+)\) or first_seen_at > now\(\) - interval '7 days'\)\)\) order by/,
  );
  assert.ok(m, c.sql);
  assert.equal(m[1], m[2], "三支引用的是同一个收窄 tsquery");
  // 外层预筛仍在：7 天支上的类型条件只是冗余提示，候选集由预筛决定。
  assert.match(c.sql, /recruitment_category is not null and recruitment_explicit and recruitment_category = '实习'/);
});

// 2026-09-18 线上实锤：候选 SQL 绑定了一个没被引用的参数（FTS 路径压了收窄用的 tsquery 却没拼收窄条件）
// → PG 报错 → searchJobsStore 的 catch 静默退化到扫描路径。钉死：两条路径的候选 SQL 每个绑定参数都必须被引用，
// 且引用的最大编号不超过参数个数。
for (const [name, filters] of [
  ["FTS 路径（city）", { city: "深圳" }],
  ["FTS 路径（keyword）", { keyword: "后端" }],
  ["扫描路径（无筛选）", {}],
  ["扫描路径（校招，粗排收窄）", { jobType: "校招" }],
]) {
  test(`候选 SQL 的绑定参数与占位符一一对应：${name}`, async () => {
    const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
    install({ candidates: candidateRows(200), count: null });
    await search.searchJobsStore(
      { ...DEFAULT_FILTERS, ...filters },
      prefsWith({ target_roles: ["后端工程师"], target_locations: ["上海"], target_companies: ["腾讯"] }),
      [],
      0,
      60,
    );
    const c = candidateSql(calls);
    const used = new Set([...c.sql.matchAll(/\$(\d+)/g)].map((m) => Number(m[1])));
    for (let i = 1; i <= c.params.length; i++) assert.ok(used.has(i), `$${i} 被绑定但 SQL 没引用：${c.sql}`);
    assert.ok(Math.max(...used) <= c.params.length, "SQL 引用了没绑定的参数");
  });
}

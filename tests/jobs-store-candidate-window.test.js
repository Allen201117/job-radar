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
  search.__resetScanCache();
  const calls = [];
  const install = ({ candidates, count }) => {
    client.jobsQuery = async (sql, params) => {
      calls.push({ sql, params });
      if (/^select count\(\*\)/.test(sql)) return count ? [count] : [];
      if (/^select id, content_hash/.test(sql)) return []; // 命中页回补展示列
      return candidates;
    };
  };
  return { search, DEFAULT_FILTERS, calls, install };
}

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
  const { search, DEFAULT_FILTERS, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: { total: 15290, unclassified: 7 } });

  const r = await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳", jobType: "校招" },
    null,
    [],
    0,
    60,
  );
  assert.equal(r.exactTotal, null);
});

test("用户设了 exclude_keywords（SQL 看不到 JD 正文）→ 弃权", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: { total: 15290, unclassified: 0 } });

  const r = await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳" },
    { exclude_keywords: ["外包"], target_roles: [], target_keywords: [] },
    [],
    0,
    60,
  );
  assert.equal(r.exactTotal, null);
  assert.equal(countQueries(calls).length, 0);
});

test("被忽略/已投递的岗：SQL 侧一并排除，自检按同一口径对账", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  const rows = candidateRows(FTS_CAP);
  const ignoredId = rows[3].id;
  install({ candidates: rows, count: { total: 15290, unclassified: 0 } });

  const r = await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "深圳" },
    { exclude_keywords: [], target_roles: [], target_keywords: [] },
    [{ id: "a1", user_id: "u", job_id: ignoredId, action: "ignored", created_at: "2026-09-01T00:00:00Z" }],
    0,
    60,
  );
  assert.equal(r.total, FTS_CAP - 1, "被忽略的岗不进结果");
  assert.equal(r.exactTotal, 15290);
  const [countCall] = countQueries(calls);
  assert.match(countCall.sql, /not \(id = any\(\$\d+::uuid\[\]\)\)/);
  assert.deepEqual(countCall.params[countCall.params.length - 1], [ignoredId]);
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
  assert.match(
    c.sql,
    /order by \(search_doc @@ to_tsquery\('simple', \$\d+\)\) desc, first_seen_at desc limit/,
    "偏好命中优先 + 新鲜度补位",
  );
  // 偏好词要真的被展开成 tsquery 传下去，不能是空的。
  const prefQuery = c.params[c.params.length - 1];
  assert.equal(typeof prefQuery, "string");
  assert.ok(prefQuery.includes("后端") || prefQuery.includes("工程"), prefQuery);
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
  assert.match(c.sql, /order by first_seen_at desc limit/);
  assert.doesNotMatch(c.sql, /to_tsquery\('simple', \$\d+\)\) desc/);
});

test("没有偏好时按新鲜度排——此时打分只剩「近 7 天 +10」，这就是正确排序", async () => {
  const { search, DEFAULT_FILTERS, calls, install } = loadSearch();
  install({ candidates: candidateRows(FTS_CAP), count: null });

  await search.searchJobsStore({ ...DEFAULT_FILTERS, city: "深圳" }, null, [], 0, 60);
  assert.match(candidateSql(calls).sql, /order by first_seen_at desc limit/);
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
  // 候选查询比计数查询多且仅多一个参数：那就是偏好 tsquery。
  assert.equal(cand.params.length, cnt.params.length + 1);
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
  assert.match(c.sql, /order by \(search_doc @@ to_tsquery\('simple', \$\d+\)\) desc, first_seen_at desc/);
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
  const prefQuery = candidateSql(calls).params[candidateSql(calls).params.length - 1];
  assert.match(prefQuery, /深圳|shenzhen/i);
  assert.match(prefQuery, /腾讯|tencent/i);
});

// 洞察派生的取数契约 —— 三个方向都要守：
//   · 少取：insight-derive 读了某列、取数却没带它 → 那一列恒为空，对应维度静默算不出来；
//   · 多取：把整段职位描述（summary）带回来 → 白搬正文；
//   · 退回取行：香港库那条路是「库里按全部在招岗数好再回传」，不许再变成「取前 N 行」——
//     没有排序的前 N 行是按磁盘位置取的、不是样本（对比数字在 lib/jobs-store/read.ts 的 INSIGHT_FACETS_SQL 上方）。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const ROOT = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");

const derive = read("lib/insight-derive.ts");
const store = read("lib/jobs-store/read.ts");
const route = read("app/api/insights/route.ts");
// 列清单和 SQL 用真加载出来的值（模板里的占位已经展开），不从源码里抠
const READ = loadTs(path.join(ROOT, "lib", "jobs-store", "read.ts"));

const list = (s) => s.split(",").map((c) => c.trim()).filter(Boolean);

// Supabase 兜底取行用的列清单
const selectedColumns = () => list(READ.INSIGHT_DERIVE_COLUMNS);
// 香港库分面聚合从 jobs 里取的列
const facetSourceColumns = () => list(READ.INSIGHT_FACET_SOURCE_COLUMNS);
const facetsSql = () => READ.INSIGHT_FACETS_SQL;

// insight-derive 里对岗位行的属性访问：全部写成 jb.<列名>（文件内约定）。
function columnsReadByDerive() {
  return [...new Set(Array.from(derive.matchAll(/\bjb\.([a-z_]+)\b/g), (m) => m[1]))].sort();
}

test("派生读到的每一列，两条取数路都带了（少取会让维度静默算不出来）", () => {
  const readCols = columnsReadByDerive();
  assert.ok(readCols.length >= 6, "扫描没扫到东西，正则可能失效：" + readCols.join(","));

  const rowCols = new Set(selectedColumns());
  assert.deepEqual(readCols.filter((c) => !rowCols.has(c)), [], "insight-derive 读了这些列，但 INSIGHT_DERIVE_COLUMNS 没取");

  // 分面那条路：status 不回传，它是 where 条件（只数在招岗）
  const facetCols = new Set(facetSourceColumns());
  assert.deepEqual(
    readCols.filter((c) => c !== "status" && !facetCols.has(c)),
    [],
    "insight-derive 读了这些列，但 INSIGHT_FACET_SOURCE_COLUMNS 没取",
  );
  assert.match(facetsSql(), /from jobs where status = 'active' and company = any\(\$1::text\[\]\)/);
});

test("两条取数路都没有派生用不到的列（尤其不带正文）", () => {
  const readCols = new Set(columnsReadByDerive());
  // company 不经 jb. 访问：它是 where 条件用的归属列，兜底取行时留着便于排查。
  assert.deepEqual(selectedColumns().filter((c) => c !== "company" && !readCols.has(c)), [], "兜底取行多取了");
  assert.deepEqual(facetSourceColumns().filter((c) => !readCols.has(c)), [], "分面聚合多取了");
  assert.equal(selectedColumns().includes("summary"), false);
  assert.equal(facetSourceColumns().includes("summary"), false);
  assert.equal(/\bsummary\b/.test(facetsSql()), false);
});

test("分面聚合：取进来的每一列都真的分组回传了，七个分面一个不少", () => {
  const sql = facetsSql();
  const afterCte = sql.slice(sql.indexOf(")\nselect"));
  assert.ok(afterCte.length > 0, "找不到 CTE 之后的部分");
  for (const col of facetSourceColumns()) {
    assert.ok(new RegExp(`\\b${col}\\b`).test(afterCte), `${col} 取进了 CTE 却没有哪个分面用它`);
  }
  const facets = Array.from(afterCte.matchAll(/select '([a-z_]+)'/g), (m) => m[1]).sort();
  assert.deepEqual(facets, ["education", "experience", "first_seen_at", "location", "salary_text", "title", "type"]);
  // 回传那头（facetsFromGroupedRows）认的分面名与 SQL 写的是同一批：SQL 里的七个都收，各进各的分面，多一个不认识的就拒
  const row = (facet, n) => ({ facet, v1: facet === "type" ? "社招" : "x-" + facet, v2: null, v3: null, v4: null, v5: null, n });
  const f = READ.facetsFromGroupedRows(facets.map((name) => row(name, 3)));
  assert.equal(f.total, 3);
  assert.deepEqual(
    [f.byTitle, f.byLocation, f.byExperience, f.byEducation, f.bySalary, f.byFirstSeen].map((slice) => Object.values(slice[0][0])[0]),
    ["x-title", "x-location", "x-experience", "x-education", "x-salary_text", "x-first_seen_at"],
  );
  assert.equal(f.byTypeDate[0][0].recruitment_category, "社招");
  assert.throws(() => READ.facetsFromGroupedRows([...facets.map((name) => row(name, 3)), row("summary", 3)]), /不认识的分面/);
});

test("香港库那条路按全部在招岗聚合，不取行、不封顶", () => {
  const sql = facetsSql();
  assert.equal(/\blimit\b/i.test(sql), false, "分面聚合里出现了 limit —— 又变回按一部分岗位算了");
  assert.equal(/\border by\b/i.test(sql), false);
  assert.ok((sql.match(/group by/g) || []).length >= 7);
  // 旧的取行函数已经没有了；别再加回来给抽屉用
  assert.equal(store.includes("export async function activeJobsByCompanies"), false);

  const fn = store.slice(store.indexOf("export async function activeJobFacetsByCompanies"));
  const body = fn.slice(0, fn.indexOf("\n}\n"));
  assert.match(body, /jobsQueryWithLocalSettings<InsightFacetRow>\(INSIGHT_FACETS_SQL, \[companies\], \{/);

  // 路由：香港库走分面；封顶常量只出现在 Supabase 兜底那一支
  const start = route.indexOf("async function loadDeriveFacets");
  assert.ok(start >= 0, "找不到 loadDeriveFacets");
  const loader = route.slice(start, route.indexOf("\n}\n", start));
  const hk = loader.slice(0, loader.indexOf("await supabase"));
  assert.match(hk, /await activeJobFacetsByCompanies\(candidates\)/);
  assert.equal(hk.includes("DERIVE_JOB_CAP"), false, "香港库那条路不该有取数上限");
  assert.match(hk, /sampleCapped: false/);
  assert.match(route, /deriveCompanyInsightsFromFacets\(jobFacets\.facets,/);
});

// 大公司的在招行散在整张表里，数据不在缓存时不带预读参数要好几秒（实测数字在 read.ts 的 FACETS_IO_CONCURRENCY 上方）。
// 这里钉两件事：参数真的带上了；它是事务级的、不会留在还回池子的连接上。
function loadStoreWithFakePool(onQuery) {
  const cache = new Map();
  const client = loadTs(path.join(ROOT, "lib", "jobs-store", "client.ts"), cache);
  const readMod = loadTs(path.join(ROOT, "lib", "jobs-store", "read.ts"), cache);
  const log = [];
  const errorListeners = new Set(); // 借出的连接上此刻挂着的 'error' 监听
  const prevPool = globalThis.__jobsPool;
  globalThis.__jobsPool = {
    connect: async () => ({
      on: (event, fn) => event === "error" && errorListeners.add(fn),
      removeListener: (event, fn) => event === "error" && errorListeners.delete(fn),
      query: async (sql, params) => {
        // 事务期间必须有人接着 'error'：没人接的话，连接中途断掉会让整个进程当未捕获异常退出
        if (errorListeners.size !== 1) throw new Error("查询期间 client 上的 error 监听数 = " + errorListeners.size);
        log.push(params ? [sql, params] : [sql]);
        return onQuery(sql, params) || { rows: [] };
      },
      release: (destroy) => log.push(["release", destroy, errorListeners.size]),
    }),
  };
  return { client, readMod, log, restore: () => { globalThis.__jobsPool = prevPool; } };
}

test("分面聚合带着事务级的预读参数跑，跑完连接上不留痕迹", async () => {
  const facetRows = ["title", "location", "experience", "education", "salary_text", "first_seen_at", "type"].map(
    (facet) => ({ facet, v1: null, v2: null, v3: null, v4: null, v5: null, n: 4 }),
  );
  const s = loadStoreWithFakePool((sql) => (sql.startsWith("with j as materialized") ? { rows: facetRows } : null));
  try {
    const facets = await s.readMod.activeJobFacetsByCompanies(["甲公司", "甲公司 校招"]);
    assert.equal(facets.total, 4);
    assert.deepEqual(s.log.map((x) => x[0]), [
      "begin read only",
      "set local effective_io_concurrency = 64",
      s.readMod.INSIGHT_FACETS_SQL,
      "commit",
      "release",
    ]);
    assert.deepEqual(s.log[2][1], [["甲公司", "甲公司 校招"]]);
    assert.equal(s.log[4][1], false, "正常跑完的连接还回池子");
    assert.equal(s.log[4][2], 0, "还回池子前把自己挂的 error 监听摘掉（否则每借一次多一个）");
    // 没有候选名：不连库
    s.log.length = 0;
    assert.equal((await s.readMod.activeJobFacetsByCompanies([])).total, 0);
    assert.deepEqual(s.log, []);
  } finally {
    s.restore();
  }
});

test("分面聚合出错：回滚、销毁这条连接、把错抛给调用方（由路由记日志走兜底）", async () => {
  const s = loadStoreWithFakePool((sql) => {
    if (sql.startsWith("with j as materialized")) throw new Error("canceling statement due to statement timeout");
    return null;
  });
  try {
    await assert.rejects(() => s.readMod.activeJobFacetsByCompanies(["甲公司"]), /statement timeout/);
    assert.deepEqual(s.log.map((x) => x[0]).slice(-2), ["rollback", "release"]);
    assert.equal(s.log[s.log.length - 1][1], true, "出过错的连接不许还回池子");
    assert.equal(s.log[s.log.length - 1][2], 0);
    // 参数名 / 值只许是写死的常量：拼进 SQL 之前先验形状，连接都不开
    s.log.length = 0;
    await assert.rejects(() => s.client.jobsQueryWithLocalSettings("select 1", [], { "x; drop table jobs": 1 }), /不合法/);
    await assert.rejects(() => s.client.jobsQueryWithLocalSettings("select 1", [], { work_mem: 1.5 }), /不合法/);
    assert.deepEqual(s.log, []);
  } finally {
    s.restore();
  }
});

test("Supabase 兜底取数 = 同一份列清单去掉那张表没有的列", () => {
  // 那张表停在切库之前的结构，没有招聘类型两列：带上它们整条 select 报 42703，兜底一行都取不到。
  const m = /export const INSIGHT_DERIVE_COLUMNS_NOT_IN_SUPABASE = \[([^\]]*)\]/.exec(store);
  assert.ok(m, "找不到 INSIGHT_DERIVE_COLUMNS_NOT_IN_SUPABASE");
  const absent = m[1].split(",").map((c) => c.trim().replace(/["']/g, "")).filter(Boolean).sort();
  assert.deepEqual(absent, ["recruitment_category", "recruitment_explicit"]);
  const selected = selectedColumns();
  for (const c of absent) assert.ok(selected.includes(c), c + " 不在取数列表里，这张名单成了摆设");

  // 兜底那条 select 用派生出来的清单，不手抄列名（手抄的那份漏过 experience / education）
  assert.match(route, /INSIGHT_DERIVE_COLUMNS_NOT_IN_SUPABASE\.includes\(/);
  const fn = route.slice(route.indexOf("async function loadDeriveFacets"));
  const body = fn.slice(0, fn.indexOf("\n}\n"));
  assert.match(body, /\.select\(SUPABASE_DERIVE_COLUMNS\)/);
  assert.equal(/\.select\(\s*["'`]/.test(body), false, "兜底 select 里又手抄了列名");
  // 兜底是取行：取满上限要如实标出来
  assert.match(body, /sampleCapped: rows\.length >= DERIVE_JOB_CAP/);
});

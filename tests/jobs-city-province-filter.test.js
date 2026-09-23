const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

// /jobs 城市筛选填省 → 按全省地级市解析，与 /today 同一份判定（2026-09-23）。
// 改前：筛「广东」的候选 SQL 按原词查 search_doc，只取到字面写着「广东」的岗（线上 3,434 个，而「深圳」一城 23,394 个）；
// 珠三角 / 长三角 / 「北京市」同一个洞。计数口径的风险在「省目标的 SQL 只是超集」，下面最后几条钉它。
const ROOT = path.join(__dirname, "..");
const lib = (...p) => path.join(ROOT, "lib", ...p);

const {
  DEFAULT_FILTERS,
  cityFilterHasTargets,
  cityFtsTerms,
  cityNeedsLocationRecheck,
  citySqlLikeTokens,
  jobFilterTier,
  locationMatchesCityFilter,
} = loadTs(lib("job-filter.ts"));

test("省目标按全省解析：地级市命中，同名区 / 外省地名不算", () => {
  for (const loc of ["深圳", "佛山", "东莞市", "广东省·肇庆市", "广州-天河区"]) {
    assert.equal(locationMatchesCityFilter(loc, ["广东"]), true, loc);
  }
  assert.equal(locationMatchesCityFilter("广东省深圳市", ["广东省"]), true, "带「省」后缀同样按省解析");
  // 地名 ilike 超集会放进来、但必须被判掉的写法（全库实测）
  assert.equal(locationMatchesCityFilter("大连市-中山区", ["广东"]), false);
  assert.equal(locationMatchesCityFilter("安徽省·马鞍山市", ["辽宁"]), false);
  assert.equal(locationMatchesCityFilter("天津-河北区", ["河北"]), false, "改前按子串把它算进河北");
  assert.equal(locationMatchesCityFilter("内蒙古自治区·乌海市·海南区", ["海南"]), false, "改前算进海南");
  assert.equal(locationMatchesCityFilter("北京", ["广东"]), false);
});

test("城市 / 城市群 / 别名照旧（省以外的判定一字不动）", () => {
  assert.equal(locationMatchesCityFilter("Shenzhen", ["深圳"]), true, "拼音别名双向");
  assert.equal(locationMatchesCityFilter("深圳", ["珠三角"]), true);
  assert.equal(locationMatchesCityFilter("上海", ["深圳"]), false);
  assert.equal(locationMatchesCityFilter("佛山", ["深圳", "广东"]), true, "多值 OR：城市与省混填");
  assert.equal(locationMatchesCityFilter("深圳", []), true, "一个可判目标都没有 → 不淘汰（同改前）");
  assert.equal(cityFilterHasTargets([]), false);
  assert.equal(cityFilterHasTargets(["广东"]), true);
});

test("jobFilterMatch：省目标下地级市精确命中、空地点降级、外省淘汰", () => {
  const f = { ...DEFAULT_FILTERS, city: "广东" };
  const job = (location) => ({ id: "1", title: "产品经理", company: "某公司", location, summary: "" });
  assert.equal(jobFilterTier(job("佛山"), f), "exact");
  assert.equal(jobFilterTier(job(""), f), "related", "城市未知 ≠ 不符合");
  assert.equal(jobFilterTier(job("大连市-中山区"), f), null);
});

test("全文候选门的 OR 组：省→省内全部地名，城市群→成员城市，普通城市与改前逐字相同", () => {
  const gd = cityFtsTerms(["广东"]);
  for (const name of ["广东", "广州", "深圳", "佛山", "东莞", "惠州", "中山"]) assert.ok(gd.includes(name), name);
  assert.deepEqual(cityFtsTerms(["深圳"]), ["深圳"], "普通城市的 tsquery 不能变（计划/缓存 key 都跟着它）");
  assert.deepEqual(cityFtsTerms(["上海", "杭州"]), ["上海", "杭州"]);
  const prd = cityFtsTerms(["珠三角"]);
  assert.ok(prd.includes("广州") && prd.includes("深圳"), "改前按原词「珠三角」查，全库命中 0");
  assert.deepEqual(cityFtsTerms(["北京市"]), ["北京市", "北京"], "改前「北京市」只命中字面带「市」的 34 个岗");
});

test("SQL ilike 词：省目标用省内地名（locationMatchesCityFilter 的超集），城市照旧全别名", () => {
  const gd = citySqlLikeTokens(["广东"]);
  assert.ok(gd.includes("佛山") && gd.includes("中山"));
  assert.ok(!gd.includes("shenzhen"), "省目标不再带省会拼音：/today 同口径");
  assert.ok(citySqlLikeTokens(["深圳"]).includes("shenzhen"));
  assert.equal(cityNeedsLocationRecheck(["深圳", "上海"]), false);
  assert.equal(cityNeedsLocationRecheck(["深圳", "广东"]), true);
});

// ── 候选 SQL 与真实总数（桩掉 jobsQuery）───────────────────────────────────────────────────────
function loadSearch() {
  const cache = new Map();
  const client = loadTs(lib("jobs-store", "client.ts"), cache);
  const search = loadTs(lib("jobs-store", "search.ts"), cache);
  search.__resetScanCache();
  const calls = [];
  const install = ({ candidates, countRows, ownRows }) => {
    client.jobsQuery = async (sql, params) => {
      calls.push({ sql, params });
      // 用户隐藏岗那部分（2026-09-23 起从共享计数里拆出来按主键单算）
      if (/^select (location, )?count\(\*\)/.test(sql) && / and id = any\(/.test(sql)) return ownRows || [];
      if (/^select (location, )?count\(\*\)/.test(sql)) return countRows;
      if (/^select exists\(/.test(sql)) return [{ pending: false }];
      if (/^select id, content_hash/.test(sql)) return [];
      return candidates;
    };
  };
  return { search, calls, install };
}

function rows(n, location, start = 0) {
  return Array.from({ length: n }, (_, i) => ({
    id: `00000000-0000-4000-8000-${String(start + i).padStart(12, "0")}`,
    source_id: "s1",
    company: "某公司",
    title: "后端工程师",
    location,
    summary: "负责服务端开发",
    status: "active",
    first_seen_at: "2026-09-01T00:00:00Z",
    posted_at: "2026-09-01T00:00:00Z",
  }));
}

const countSql = (calls) => calls.filter((c) => /^select (location, )?count\(\*\)/.test(c.sql));

test("筛「广东」：tsquery 带省内地名、where 带地名 ilike", async () => {
  const { search, calls, install } = loadSearch();
  install({ candidates: rows(10, "佛山"), countRows: [] });
  await search.searchJobsStore({ ...DEFAULT_FILTERS, city: "广东" }, null, [], 0, 60);
  const cand = calls.find((c) => /^select id, source_id/.test(c.sql));
  assert.ok(cand, "发了候选查询");
  assert.match(cand.params[0], /\(佛山\)/, "tsquery 的城市 OR 组含佛山");
  assert.ok(cand.params.includes("%佛山%"), "location ilike 含佛山");
});

test("省目标撞上限：按 location 分组计数，只加同一判定放行的组（空地点降级算进去）", async () => {
  const { search, calls, install } = loadSearch();
  // 1000 窗（匿名 + 全下推）撞满，其中 3 行是地名 ilike 放进来的外省岗
  install({
    candidates: [...rows(997, "深圳"), ...rows(3, "大连市-中山区", 997)],
    countRows: [
      { location: "深圳", total: 22000, unclassified: 0 },
      { location: "佛山", total: 2000, unclassified: 0 },
      { location: "大连市-中山区", total: 17, unclassified: 0 },
      { location: null, total: 40, unclassified: 0 },
      { location: "", total: 2, unclassified: 0 },
    ],
  });
  const r = await search.searchJobsStore({ ...DEFAULT_FILTERS, city: "广东" }, null, [], 0, 60);
  assert.equal(r.capped, true);
  assert.equal(r.total, 997, "外省那 3 行被 JS 判掉");
  assert.equal(r.exactTotal, 24042, "22000 + 2000 + 空地点 42；大连市-中山区 17 不算");
  const q = countSql(calls);
  assert.equal(q.length, 1);
  assert.match(q[0].sql, /group by location$/);
});

test("省目标：候选里还有城市以外的淘汰 → 照样弃权给「N+」，城市复核不能变成放行口子", async () => {
  const { search, install } = loadSearch();
  // 一行外省（城市判掉，③ 扣得掉）+ 两行批量门店副本被折叠成一行（③ 扣不掉）→ 必须弃权。
  const body = "负责门店房源带看、客户维护与签约，协助店长完成月度业绩目标，熟悉本地二手房市场优先考虑。".repeat(2);
  const cands = rows(1000, "深圳");
  cands[5] = { ...cands[5], location: "大连市-中山区" };
  cands[6] = { ...cands[6], company: "我爱我家", summary: body };
  cands[7] = { ...cands[7], company: "我爱我家", summary: body };
  install({ candidates: cands, countRows: [{ location: "深圳", total: 5000, unclassified: 0 }] });
  const r = await search.searchJobsStore({ ...DEFAULT_FILTERS, city: "广东" }, null, [], 0, 60);
  assert.equal(r.capped, true);
  assert.equal(r.total, 998, "外省 1 行判掉 + 门店副本折叠 1 行");
  assert.equal(r.exactTotal, null);
});

test("普通城市的计数查询不变：不分组、单行 count(*)", async () => {
  const { search, calls, install } = loadSearch();
  install({ candidates: rows(1000, "深圳"), countRows: [{ total: 23394, unclassified: 0 }] });
  const r = await search.searchJobsStore({ ...DEFAULT_FILTERS, city: "深圳" }, null, [], 0, 60);
  assert.equal(r.exactTotal, 23394);
  const q = countSql(calls);
  assert.equal(q.length, 1);
  assert.match(q[0].sql, /^select count\(\*\)/);
  assert.doesNotMatch(q[0].sql, /group by/);
});

test("登录用户没筛城市、偏好填省：粗排的城市项展开成省内地名", async () => {
  const { search, calls, install } = loadSearch();
  install({ candidates: rows(10, "佛山"), countRows: [] });
  const prefs = { target_roles: ["后端工程师"], target_locations: ["广东"], target_keywords: [], target_companies: [] };
  await search.searchJobsStore({ ...DEFAULT_FILTERS }, prefs, [], 0, 60);
  const withCityArray = calls.find((c) => c.params.some((p) => Array.isArray(p) && p.includes("%佛山%")));
  assert.ok(withCityArray, "粗排 location ilike any(...) 含佛山");
});

// ── 打分与校招「对你有货」同口径 ─────────────────────────────────────────────────────────────
test("scoreJob：目标城市填省，省内地级市拿城市分，同名区不拿", () => {
  const { scoreJob } = loadTs(lib("scoring.ts"));
  const prefs = { target_roles: [], target_keywords: [], target_companies: [], target_locations: ["广东"] };
  const job = (location) => ({ id: "j", title: "运营", company: "某公司", location, summary: "", first_seen_at: null });
  const locReason = (r) => r.match_reasons.some((m) => m.type === "location");
  assert.equal(locReason(scoreJob(job("佛山"), prefs, [])), true);
  assert.equal(locReason(scoreJob(job("广东省·肇庆市"), prefs, [])), true, "改前唯一能拿分的写法仍能拿");
  assert.equal(locReason(scoreJob(job("大连市-中山区"), prefs, [])), false);
  const hebei = { ...prefs, target_locations: ["河北"] };
  assert.equal(locReason(scoreJob(job("天津-河北区"), hebei, [])), false, "改前按子串给了分");
  const city = { ...prefs, target_locations: ["深圳"] };
  assert.equal(locReason(scoreJob(job("深圳市南山区"), city, [])), true, "城市目标照旧");
});

test("校招「对你有货」：填省的用户，省内城市选项都算对口", () => {
  const { selectFitIndexes } = loadTs(lib("campus-facets.ts"));
  const options = { cityOptions: ["佛山", "大连", "深圳", "东莞"], educationOptions: [], functionOptions: [], gradClassOptions: [] };
  const fit = selectFitIndexes([], ["广东"], options);
  assert.equal(fit.cityRequested, true);
  assert.deepEqual(fit.cities, [0, 2, 3]);
  assert.deepEqual(selectFitIndexes([], ["深圳"], options).cities, [2], "城市目标照旧");
  assert.equal(selectFitIndexes([], [], options).cityRequested, false);
});

test("省目标 + 用户隐藏岗：共享计数与隐藏部分各自按地点复核再相减（外省的隐藏岗不能多减）", async () => {
  const { search, calls, install } = loadSearch();
  const cands = [...rows(997, "深圳"), ...rows(3, "大连市-中山区", 997)];
  const ignoredId = cands[10].id;
  install({
    candidates: cands,
    countRows: [
      { location: "深圳", total: 22000, unclassified: 0 },
      { location: "佛山", total: 2000, unclassified: 0 },
      { location: "大连市-中山区", total: 17, unclassified: 0 },
      { location: null, total: 40, unclassified: 0 },
      { location: "", total: 2, unclassified: 0 },
    ],
    // 隐藏岗里 1 个在深圳、5 个在大连：大连那组本来就不算进广东，不能再减一遍
    ownRows: [
      { location: "深圳", total: 1, unclassified: 0 },
      { location: "大连市-中山区", total: 5, unclassified: 0 },
    ],
  });
  const r = await search.searchJobsStore(
    { ...DEFAULT_FILTERS, city: "广东" },
    { job_scope: "domestic", target_roles: [], target_keywords: [], target_locations: [], target_companies: [], exclude_keywords: [] },
    [{ id: "a1", user_id: "u", job_id: ignoredId, action: "ignored", created_at: "2026-09-01T00:00:00Z" }],
    0,
    60,
  );
  assert.equal(r.total, 996, "外省 3 行 + 被忽略 1 行");
  assert.equal(r.exactTotal, 24041, "24042 − 深圳那 1 个隐藏岗");
  const q = countSql(calls);
  const shared = q.find((c) => !/ id = any\(/.test(c.sql));
  const own = q.find((c) => / id = any\(/.test(c.sql));
  assert.ok(shared && own);
  assert.match(shared.sql, /group by location$/);
  assert.match(own.sql, / and id = any\(\$\d+::uuid\[\]\) group by location$/, "隐藏条件必须在 group by 之前");
  assert.ok(!JSON.stringify(shared.params).includes(ignoredId), "共享计数的键里不许有个人数据");
});

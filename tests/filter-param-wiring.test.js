// 契约:每个「参与筛选」的 filter key 都必须端到端接通——
//   ① 客户端 filtersToParams(hooks/useJobFilters.ts) 用 p.set("<key>", …) 把它序列化进 /api/jobs/search 查询串
//   ② GET 路由(app/api/jobs/search/route.ts) 用 p.get("<key>") 或 bool("<key>") 把它从查询串解析回 filters
// 否则 UI 收得到、服务端收不到 → 筛选静默失效(2026-09-15 companyTier 正因两处漏接而全链失灵)。
// 这道门不依赖任何人记得改代码:新增 SQL_PUSHED/JS_ONLY key 忘了接线即红。
// 注:检查的是「序列化/解析这个调用点」而非「key 名在文件里出现过」——后者会被别处的
//     白名单数组(如单删 chip 的 companyTier)误判为已接通。
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { loadTs } = require("./_load-ts");
const { SQL_PUSHED_FILTER_KEYS, JS_ONLY_FILTER_KEYS } = loadTs(
  path.join(__dirname, "..", "lib", "job-filter.ts")
);

const read = (rel) => fs.readFileSync(path.join(__dirname, "..", rel), "utf8");
const CLIENT = read("hooks/useJobFilters.ts");
const ROUTE = read("app/api/jobs/search/route.ts");
// 参与筛选的 key = SQL 下推 ∪ 只能 JS 判(NON_FILTERING 的 sortBy 只管排序,不在此列)。
const FILTERING_KEYS = [...SQL_PUSHED_FILTER_KEYS, ...JS_ONLY_FILTER_KEYS];

test("每个筛选 key 都被客户端序列化进查询串(filtersToParams 的 p.set)", () => {
  for (const key of FILTERING_KEYS) {
    assert.ok(
      CLIENT.includes(`set("${key}"`),
      `hooks/useJobFilters.ts 未 p.set("${key}", …) → 该筛选到不了服务端`
    );
  }
});

test("每个筛选 key 都被搜索路由从查询串解析回 filters(p.get / bool)", () => {
  for (const key of FILTERING_KEYS) {
    assert.ok(
      ROUTE.includes(`get("${key}"`) || ROUTE.includes(`bool("${key}"`),
      `app/api/jobs/search/route.ts 未 p.get("${key}") / bool("${key}") → 该筛选被服务端丢弃`
    );
  }
});

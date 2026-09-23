const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");
const { titleCityLocation, deriveCountryCode } = require("../lib/geo.js");

const ROOT = path.join(__dirname, "..");

// ============================================================
// location 为空时从标题认城市（2026-09-23）。背景：康龙化成「有机合成研究员-西安」、万物云
// 「福州-项目管理岗（实习生）」这类岗 location 为空，/today 当「城市未知」放给所有城市的用户。
// 判据与五条「宁可漏判」取舍写在 crawler/geo.py 的 title_city_location 上方。
// ============================================================

// 跨语言一致性：与 crawler/test_geo.py 的 TitleCityLocationTest 共读同一份夹具。
test("titleCityLocation: 与 crawler/geo.py 共读同一份夹具，逐条一致", () => {
  const doc = require("./fixtures/title-city-cases.json");
  assert.ok(doc.cases.length > 30, "夹具被清空了？");
  for (const c of doc.cases) {
    assert.equal(titleCityLocation(c.title), c.expected, `${c.title} (${c.note})`);
  }
});

test("titleCityLocation: 认出的城市填进 location 后一定判 CN", () => {
  for (const title of ["有机合成研究员-西安", "博士管培生-连云港/苏州", "售前工程师-黔西南州"]) {
    assert.equal(deriveCountryCode(titleCityLocation(title)), "CN", title);
  }
});

// app 写入链（lib/jobs-store/write.ts）必须与 crawler/normalizer 同口径物化：只换掉数据库那一层，
// 断言真实发出的 insert 绑定值，而不是对源码做正则。
function loadWriteWithFakeDb() {
  const calls = [];
  const cache = new Map();
  cache.set(path.join(ROOT, "lib", "jobs-store", "client.ts"), {
    exports: {
      jobsQuery: async (sql, vals) => {
        calls.push({ sql, vals });
        if (/^\s*select id, status from jobs/.test(sql)) return [];
        return [{ id: "00000000-0000-0000-0000-000000000001" }];
      },
    },
  });
  const mod = loadTs(path.join(ROOT, "lib", "jobs-store", "write.ts"), cache);
  return { mod, calls };
}

function insertValue(call, col) {
  const cols = /insert into jobs \(([^)]*)\) values \(([\s\S]*)\) returning /.exec(call.sql);
  assert.ok(cols, "解析不出 insert 语句");
  const names = cols[1].split(",").map((s) => s.trim());
  const slots = cols[2].split(",").map((s) => s.trim());
  const i = names.indexOf(col);
  assert.ok(i >= 0, `insert 列表里没有 ${col}`);
  const m = /^\$(\d+)$/.exec(slots[i]);
  assert.ok(m, `${col} 不是占位符而是字面量 ${slots[i]}`);
  return call.vals[Number(m[1]) - 1];
}

async function insertedRow(job) {
  const { mod, calls } = loadWriteWithFakeDb();
  await mod.upsertJob({ company: "万物云", jd_url: "https://example.com/jobs/1", ...job });
  const call = calls.find((c) => /^\s*insert into jobs/.test(c.sql));
  assert.ok(call, "没有发出 insert");
  return { location: insertValue(call, "location"), country_code: insertValue(call, "country_code") };
}

test("write.ts: location 为空时物化标题城市，并据此派生 country_code", async () => {
  assert.deepEqual(await insertedRow({ title: "福州-项目管理岗（实习生）", location: null }), {
    location: "福州",
    country_code: "CN",
  });
  assert.deepEqual(await insertedRow({ title: "福州-项目管理岗（实习生）", location: "  " }), {
    location: "福州",
    country_code: "CN",
  });
});

test("write.ts: adapter 给了地点绝不被标题覆盖；标题说不清的保持为空", async () => {
  assert.equal((await insertedRow({ title: "泉州-项目管理岗", location: "厦门" })).location, "厦门");
  assert.equal((await insertedRow({ title: "城市经理（销售方向）-全国", location: null })).location, null);
});

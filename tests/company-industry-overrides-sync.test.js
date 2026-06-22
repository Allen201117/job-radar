const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { COMPANY_OVERRIDES } = require("../lib/company-industry");
const json = require("../lib/data/company-industry-overrides.json");

// 漂移守卫：lib/data/company-industry-overrides.json 是 COMPANY_OVERRIDES 的生成产物，
// 供爬虫 Python(crawler/company_industry.py) 读取。改了 COMPANY_OVERRIDES 却忘了重生成 JSON
// → 此测试红，提示跑 `node scripts/gen-company-overrides-json.js`。
test("company-industry JSON 与 JS 模块同步（忘重生成则报错）", () => {
  assert.deepEqual(
    json,
    COMPANY_OVERRIDES,
    "lib/data/company-industry-overrides.json 与 COMPANY_OVERRIDES 不一致 → 跑 node scripts/gen-company-overrides-json.js",
  );
});

// JSON 自身结构合法：每条是 [公司名, 行业] 字符串二元组。
test("overrides JSON 结构合法（[name, industry] 二元组）", () => {
  assert.ok(Array.isArray(json) && json.length > 0);
  for (const row of json) {
    assert.ok(Array.isArray(row) && row.length === 2, `非法条目: ${JSON.stringify(row)}`);
    assert.equal(typeof row[0], "string");
    assert.equal(typeof row[1], "string");
  }
});

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const {
  DEFAULT_FILTERS,
  filtersFromSearchParams,
  filtersToSearchParams,
  hasJobFilterSearchParams,
} = loadTs(path.join(__dirname, "..", "lib", "job-filter.ts"));

test("/jobs URL 与完整筛选对象可双向还原", () => {
  const filters = {
    ...DEFAULT_FILTERS,
    city: "深圳,广州",
    jobType: "校招",
    keyword: "产品",
    company: "腾讯",
    education: "本科",
    experience: "fresh",
    postedWithin: "7",
    jobFunction: "产品",
    jobRole: "产品经理",
    companyTier: "大厂,外企",
    sortBy: "newest",
    salaryOnly: true,
    showApplied: true,
  };
  const params = filtersToSearchParams(filters);
  assert.equal(params.get("q"), "产品");
  assert.equal(params.get("keyword"), null, "分享链接沿用已有 q，不另造重复参数");
  assert.deepEqual(filtersFromSearchParams(params), filters);
});

test("URL 筛选存在时可覆盖个人偏好；无参数则不触发覆盖", () => {
  assert.equal(hasJobFilterSearchParams(new URLSearchParams()), false);
  assert.equal(hasJobFilterSearchParams(new URLSearchParams("city=%E6%B7%B1%E5%9C%B3")), true);
  assert.deepEqual(filtersFromSearchParams(new URLSearchParams("q=%E4%BA%A7%E5%93%81&sortBy=unexpected")), {
    ...DEFAULT_FILTERS,
    keyword: "产品",
    sortBy: "match",
  });
});

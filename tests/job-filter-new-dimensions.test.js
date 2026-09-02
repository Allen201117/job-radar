const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const {
  DEFAULT_FILTERS,
  jobFilterMatch,
  matchesExperienceBand,
  matchesJobFunction,
  matchesPostedWithin,
} = loadTs(path.join(__dirname, "..", "lib", "job-filter.ts"));

function job(overrides = {}) {
  return {
    id: "job-1",
    company: "示例公司",
    title: "产品经理",
    location: "上海",
    job_type: "社招",
    summary: "",
    experience: "",
    posted_at: "2026-09-01T12:00:00.000Z",
    first_seen_at: "2026-09-01T12:00:00.000Z",
    last_seen_at: "2026-09-01T12:00:00.000Z",
    jd_url: "https://example.com/job-1",
    ...overrides,
  };
}

test("岗位职能：多选按分类结果 OR 匹配，空选不收窄", () => {
  const product = job({ title: "产品经理" });
  assert.equal(matchesJobFunction(product, "产品,研发"), true);
  assert.equal(matchesJobFunction(product, "研发,设计"), false);
  assert.equal(matchesJobFunction(product, ""), true);
});

test("工作经验：已解析年限按区间匹配，解析不出只可进入应届无经验", () => {
  assert.equal(matchesExperienceBand(job({ experience: "3-5年工作经验" }), "3-5"), true);
  assert.equal(matchesExperienceBand(job({ experience: "5年以上相关经验" }), "3-5"), false);
  assert.equal(matchesExperienceBand(job({ title: "行政专员", experience: "经验不限" }), "0-3"), false);
  assert.equal(matchesExperienceBand(job({ title: "行政专员", experience: "经验不限" }), "fresh"), true);
  assert.equal(matchesExperienceBand(job({ experience: "10年以上经验" }), "10+"), true);
});

test("发布时间：空值与窗口外岗位不通过，窗口内岗位通过", () => {
  const now = Date.now;
  Date.now = () => new Date("2026-09-02T12:00:00.000Z").getTime();
  try {
    assert.equal(matchesPostedWithin(job({ posted_at: "2026-09-01T12:00:00.000Z" }), "1"), true);
    assert.equal(matchesPostedWithin(job({ posted_at: "2026-08-31T11:59:59.000Z" }), "1"), false);
    assert.equal(matchesPostedWithin(job({ posted_at: null }), "7"), false);
    assert.equal(matchesPostedWithin(job({ posted_at: "not-a-date" }), "7"), false);
    assert.equal(matchesPostedWithin(job({ posted_at: null }), ""), true);
  } finally {
    Date.now = now;
  }
});

test("新维度：jobFilterMatch 对明确不命中的岗位返回 null", () => {
  const base = { ...DEFAULT_FILTERS };
  assert.equal(jobFilterMatch(job({ title: "后端开发工程师" }), { ...base, jobFunction: "产品" }), null);
  assert.equal(jobFilterMatch(job({ experience: "5年以上经验" }), { ...base, experience: "0-3" }), null);
  assert.equal(jobFilterMatch(job({ posted_at: null }), { ...base, postedWithin: "3" }), null);
});

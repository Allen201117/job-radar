const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const read = (rel) => fs.readFileSync(path.resolve(__dirname, rel), "utf8");

const todayLoading = read("../app/today/loading.tsx");
const jobsLoading = read("../app/jobs/loading.tsx");
const savedLoading = read("../app/saved/loading.tsx");

test("today loading copy matches real page", () => {
  assert.ok(todayLoading.includes("今天值得处理的官方岗位"), "today loading missing title");
  assert.ok(todayLoading.includes("今日机会"), "today loading missing eyebrow");
  assert.ok(todayLoading.includes("count={3}"), "today loading should have 3 metric skeletons");
});

test("jobs loading copy matches real page and avoids refresh/discovery wording", () => {
  assert.ok(jobsLoading.includes("探索完整官方岗位库"), "jobs loading missing title");
  assert.ok(jobsLoading.includes("搜索岗位"), "jobs loading missing eyebrow");
  assert.ok(!jobsLoading.includes("刷新"), "jobs loading must not say 刷新");
  assert.ok(!jobsLoading.includes("发掘"), "jobs loading must not say 发掘");
});

test("saved loading uses 值得投, not 已收藏", () => {
  assert.ok(savedLoading.includes("值得投"), "saved loading missing 值得投");
  assert.ok(!savedLoading.includes("已收藏"), "saved loading must not say 已收藏");
});

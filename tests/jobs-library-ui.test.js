const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

test("空结果不保留加载更多入口", () => {
  const hook = read("hooks/useJobFilters.ts");
  const client = read("app/jobs/jobs-client.tsx");
  assert.match(hook, /server\.total > 0 && server\.jobs\.length < server\.total/);
  assert.match(client, /capped && total > 0 \? "还有更多，可继续加载"/);
});

test("排序在筛选条直接可见，校招锁定时经验只给应届选项", () => {
  const filters = read("components/JobFilters.tsx");
  assert.match(filters, /import \{ Segmented \} from "@\/components\/ui"/);
  assert.equal((filters.match(/ariaLabel="岗位排序"/g) || []).length, 2);
  assert.match(filters, /const CAMPUS_EXPERIENCE = EXPERIENCE\.slice\(0, 2\)/);
  // 吸顶条与「更多」弹窗两处「经验」都要按锁定切换选项，漏一处就会在校招专区露出「3~5年」。
  assert.equal((filters.match(/lockedJobType \? CAMPUS_EXPERIENCE : EXPERIENCE/g) || []).length, 2);
});

test("发布时间排序在每个已取回页面内复用职位库公司的散列规则", () => {
  const search = read("lib/jobs-store/search.ts");
  assert.match(search, /const JOB_LIBRARY_SPREAD = \{ cap: 2, window: 6 \}/);
  assert.equal((search.match(/spreadByCompany\(ranked\.slice\(offset, offset \+ limit\), JOB_LIBRARY_SPREAD\)/g) || []).length, 2);
});

test("职位库文案说明精确匹配与待补详情", () => {
  const client = read("app/jobs/jobs-client.tsx");
  assert.match(client, /精确匹配 \$\{exactCount\} 个/);
  assert.match(client, /详情待补充 \$\{relatedMissingInfo\} 个/);
  assert.match(client, /以下是同类职能、或详情还没补全的岗位/);
});

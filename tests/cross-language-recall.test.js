const test = require("node:test");
const assert = require("node:assert/strict");
const {
  jobMatchesChinaKeyword,
  keywordMatchTier,
} = require("../lib/china-keyword-expansion");

// 跨语言召回：P2-B 接入的外企 ATS（greenhouse/lever/workday）岗位多为英文标题，
// 中文泛词（数据/工程师/软件）此前匹配不到 → 岗位抓回来了却搜不到。补双语锚词修复。
// 硬约束：不得牺牲 P1 精度（泛词不乱召不同职能；兄弟组排除不被破坏）。

test("数据 → 命中英文 Data 岗（此前漏）", () => {
  assert.equal(jobMatchesChinaKeyword({ title: "Data Scientist" }, "数据"), true);
  assert.equal(jobMatchesChinaKeyword({ title: "Data Engineer" }, "数据"), true);
  assert.equal(jobMatchesChinaKeyword({ title: "Senior Data Analyst" }, "数据"), true);
});

test("工程师/软件 → 命中英文 Engineer 岗（此前漏）", () => {
  assert.equal(jobMatchesChinaKeyword({ title: "Backend Engineer" }, "工程师"), true);
  assert.equal(jobMatchesChinaKeyword({ title: "Senior Software Engineer" }, "工程师"), true);
  assert.equal(jobMatchesChinaKeyword({ title: "Software Engineer" }, "软件"), true);
  assert.equal(jobMatchesChinaKeyword({ title: "Machine Learning Developer" }, "工程师"), true);
});

test("精度保留：泛词不乱召不同职能", () => {
  assert.equal(jobMatchesChinaKeyword({ title: "Product Manager" }, "工程师"), false);
  assert.equal(jobMatchesChinaKeyword({ title: "Sales Manager" }, "数据"), false);
  assert.equal(jobMatchesChinaKeyword({ title: "HR Business Partner" }, "工程师"), false);
});

test("中文标题仍命中（不回退）", () => {
  assert.equal(jobMatchesChinaKeyword({ title: "数据分析师" }, "数据"), true);
  assert.equal(jobMatchesChinaKeyword({ title: "后端工程师" }, "工程师"), true);
  assert.equal(jobMatchesChinaKeyword({ title: "算法工程师" }, "算法"), true);
});

test("P1 兄弟组精度不被破坏：前端岗不进后端 related", () => {
  assert.equal(keywordMatchTier({ title: "Frontend Engineer", summary: "" }, "后端"), null);
});

test("P1 related 层仍可兜泛标题同职能岗（新 engineer 组 function=null 不污染兄弟排除）", () => {
  // “高级工程师”无具体子方向词、无摘要 → 对 query 后端 应仍能进 related（研发同职能兜底）。
  // 若 engineer 组误设 function=研发 会把它当兄弟组排除掉 → 这条会变 null（回归）。
  assert.equal(keywordMatchTier({ title: "高级工程师", summary: "" }, "后端"), "related");
});

test("复合 query 仍精确：数据工程师", () => {
  assert.equal(jobMatchesChinaKeyword({ title: "Data Engineer" }, "数据工程师"), true);
  assert.equal(jobMatchesChinaKeyword({ title: "Marketing Analyst" }, "数据工程师"), false);
});

// 2026-09-18：纯拉丁长词（≥4 字母）改走词边界。此前 ≥4 字母的拉丁词是裸子串 →
// product ⊂ production（全库 active 标题 2,166 例、1,430 例被判成产品经理 exact）、search ⊂ research 1,968、
// intern ⊂ international/internal 675、quant ⊂ quantum 71、sales ⊂ salesforce 97、doctor ⊂ postdoctoral 44。
test("纯拉丁长词走词边界：production 不再命中 产品经理", () => {
  assert.equal(keywordMatchTier({ title: "Production Technician I", summary: "" }, "产品经理"), null);
  assert.equal(keywordMatchTier({ title: "Manager Production", summary: "" }, "产品经理"), null);
  assert.equal(jobMatchesChinaKeyword({ title: "Sr. Production Planner." }, "产品经理"), false);
  assert.equal(jobMatchesChinaKeyword({ title: "Research Scientist" }, "搜索"), false);
  assert.equal(jobMatchesChinaKeyword({ title: "Senior Internal Auditor" }, "实习"), false);
  assert.equal(jobMatchesChinaKeyword({ title: "Ant International-Product Manager" }, "实习"), false);
  assert.equal(jobMatchesChinaKeyword({ title: "Senior Quantum Engineer" }, "量化"), false);
  assert.equal(jobMatchesChinaKeyword({ title: "Senior Salesforce Developer" }, "销售"), false);
  assert.equal(jobMatchesChinaKeyword({ title: "Postdoctoral Fellow" }, "医生"), false);
});

test("纯拉丁长词词边界：真岗仍命中（多词短语保持子串、复数与登记过的派生词放行）", () => {
  assert.equal(keywordMatchTier({ title: "Product Manager", summary: "" }, "产品经理"), "exact");
  assert.equal(keywordMatchTier({ title: "Senior Product Owner", summary: "" }, "产品经理"), "exact");
  assert.equal(jobMatchesChinaKeyword({ title: "Data Products Lead" }, "产品经理"), true); // 复数
  assert.equal(jobMatchesChinaKeyword({ title: "Engineering Manager" }, "工程师"), true); // 派生词 engineering
  assert.equal(jobMatchesChinaKeyword({ title: "Quantitative Researcher" }, "量化"), true); // quantitative
  assert.equal(jobMatchesChinaKeyword({ title: "Database Engineer" }, "数据"), true); // database 沿用旧口径
  assert.equal(jobMatchesChinaKeyword({ title: "Senior Auditor" }, "财务"), true); // auditor
  assert.equal(jobMatchesChinaKeyword({ title: "Back-end Engineer" }, "后端"), true); // 带连字符的复合词仍子串
  assert.equal(jobMatchesChinaKeyword({ title: "产品product经理" }, "产品经理"), true); // CJK 也是词边界
});

test("纯拉丁长词词边界：解除误认领后真岗回到本方向 exact", () => {
  // 旧实现里 salesforce ⊂ sales 让销售组「认领」了这个岗，产品经理查询被兄弟组排除。
  assert.equal(keywordMatchTier({ title: "Salesforce Product Owner", summary: "" }, "产品经理"), "exact");
  assert.equal(keywordMatchTier({ title: "Data Science Postdoctoral Fellow", summary: "" }, "数据分析"), "exact");
});

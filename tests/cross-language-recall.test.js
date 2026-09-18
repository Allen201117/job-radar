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

// 2026-09-18 /today 44 画像真库对拍抓到的误报：「产品经理」词组含短拉丁词 pm（国内组与海外词库都有），
// containsTerm 对 ≤3 字母的拉丁词走词边界正则，而海外倒班岗标题里的排班时间 "2 PM-" / "6:00 PM)" 的
// PM 正好是独立 token → 判成「方向精确命中 产品经理」。全库 active 实测：标题含独立 pm token 的 480 条里
// 63 条是「小时数 + am/pm」的时间写法，全被判 exact，全是仓储/产线/客服倒班岗。
// 修法钉在 containsTerm：am/pm 前面紧跟「独立的 1~2 位小时数（可带 :mm）」时不算命中。
// ⚠️ 别拿 "Production Associate (11:00 PM" 当样例：它另有一条根因（长词 product 走裸子串、被 production 包住），不归本条管。
// ⚠️ 判据必须是**独立**的小时数：「T0 PM」（量化 T0 策略的 PM）里 0 前面是字母，不是时间，仍要命中。
test("时间型 AM/PM 不算 产品经理 命中（倒班岗排班时间）", () => {
  const timeTitles = [
    "Data Center Team Lead- Builds-B Shift (Mon-Fri 2 PM- 10:30PM)",
    "W/E Days Supervisor (Fri-Sun: 5:45 AM-6:00 PM)",
    "11 PM Closing Expert",
    "3rd Shift Molding Supervisor (11 PM",
    "Supply Handler (6:00 am- 6:30 pm)",
    "Customs Brokerage Rep III: M-F: 8:30 am to 5 pm CDT",
  ];
  for (const title of timeTitles) {
    assert.equal(jobMatchesChinaKeyword({ title }, "产品经理"), false, title);
    assert.equal(keywordMatchTier({ title }, "产品经理", { includeOverseasLexicon: true }), null, title);
  }
});

test("岗位缩写 PM 仍精确命中 产品经理（不能因时间规则误杀）", () => {
  const roleTitles = [
    "Senior PM, Growth",
    "Technical PM",
    "PM - Platform",
    "PM(J16657)",
    "T0 PM",
    "搜索策略pm（J84612）",
    "Digital PM Analyst, Assistant Vice President",
  ];
  for (const title of roleTitles) {
    assert.equal(jobMatchesChinaKeyword({ title }, "产品经理"), true, title);
    assert.equal(keywordMatchTier({ title }, "产品经理", { includeOverseasLexicon: true }), "exact", title);
  }
});

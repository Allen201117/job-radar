const assert = require("node:assert/strict");
const test = require("node:test");

const {
  expandChinaKeywordTerms,
  expandChinaCityTargets,
  ftsCandidateTerms,
  CHINA_KEYWORD_GROUPS,
  KEYWORD_GROUP_FUNCTIONS,
  normalizeChinaCity,
  normalizeChinaJobFields,
  normalizeChinaJobType,
  jobMatchesChinaKeyword,
  keywordMatchTier,
  keywordMatchUnits,
} = require("../lib/china-keyword-expansion");

test("非互联网方向会扩展到生产库职位标题使用的同义词", () => {
  // 每一行模拟用户实际会填写的方向词；预期词均为生产库岗位标题可见写法。
  for (const [query, expectedTerms] of [
    ["银行柜员", ["柜员", "teller"]],
    ["银行信贷", ["信贷", "personal banker"]],
    ["保险理赔", ["理赔", "underwriter"]],
    ["投资经理", ["投资经理", "portfolio manager"]],
    ["中学数学教师", ["教师", "主讲"]],
    ["教研培训", ["教研", "课程研发"]],
    ["临床护士", ["护士", "nurse"]],
    ["临床医生", ["医生", "physician"]],
    ["临床研究", ["临床监查", "cra"]],
    ["药师", ["药师", "pharmacist"]],
    ["医药代表", ["医药代表", "msl"]],
    ["机械工程师", ["机械设计", "mechanical engineer"]],
    ["工艺工程师", ["工艺工程", "manufacturing engineer"]],
    ["电气自动化", ["电气工程", "plc"]],
    ["质量工程师", ["质量工程", "sqe"]],
    ["生产管理", ["生产管理", "operator"]],
    ["土木工程师", ["土建", "施工"]],
    ["工程造价", ["造价", "quantity surveyor"]],
    ["客户服务", ["客服", "customer support"]],
    ["门店零售", ["店长", "retail"]],
  ]) {
    const terms = expandChinaKeywordTerms(query).map((term) => term.toLowerCase());
    for (const expected of expectedTerms) assert.ok(terms.includes(expected), `${query} 应扩展出 ${expected}`);
  }
});

test("关键词组与职能桶按索引严格对齐", () => {
  assert.equal(KEYWORD_GROUP_FUNCTIONS.length, CHINA_KEYWORD_GROUPS.length);
});

test("追加非互联网方向组不影响现有互联网方向的精确匹配", () => {
  for (const [query, title] of [
    ["产品经理", "资深产品经理"],
    ["算法", "推荐算法工程师"],
    ["前端", "前端开发工程师"],
    ["数据分析", "数据分析师"],
  ]) {
    const job = { title };
    assert.equal(jobMatchesChinaKeyword(job, query), true, `${query} 应继续命中 ${title}`);
    assert.equal(keywordMatchTier(job, query), "exact", `${query} 对 ${title} 应保持 exact`);
  }
});

test("新方向组让不同标题写法进入真实推荐链路", () => {
  // 这些标题不与用户词字面相同；tier 非空才会通过 eligibility 的 role_mismatch 硬门。
  for (const [query, title, expectedTier] of [
    ["银行柜员", "综合柜员岗"],
    // 学段组追加后，这条从 related 升级为 exact；保留断言以防未来又退回硬匹配「中学数学」。
    ["中学数学教师", "高中数学主讲教师", "exact"],
    ["土木工程师", "施工员"],
  ]) {
    assert.equal(keywordMatchTier({ title }, query), expectedTier || "related", `${query} 应召回 ${title}`);
  }
});

test("学段组把中学数学教师的真实标题写法提升为 exact", () => {
  const units = keywordMatchUnits("中学数学教师");
  assert.equal(units.length, 3);
  assert.ok(units.some((unit) => unit.includes("高中") && unit.includes("初中")), "学段应独立成 OR 单元");
  assert.ok(units.some((unit) => unit.includes("数学")), "学科残差应保留为 AND 单元");

  for (const title of ["高中数学主讲教师-苏州分校-26校招", "初中数学教研"]) {
    assert.equal(keywordMatchTier({ title }, "中学数学教师"), "exact", title);
  }
});

test("关键词匹配跳过中文假朋友但保留同标题里的真施工", () => {
  assert.equal(keywordMatchTier({ title: "SAP MM系统实施工程师" }, "土木工程师"), null);
  assert.equal(keywordMatchTier({ title: "土建造价工程师" }, "土木工程师"), "exact");
  assert.equal(
    jobMatchesChinaKeyword({ title: "土建施工与系统实施工程" }, "土木"),
    true,
    "同一标题既有真施工又有实施工时，不能被整体否定",
  );
  assert.equal(keywordMatchTier({ title: "资深产品经理" }, "产品经理"), "exact");
  assert.equal(keywordMatchTier({ title: "推荐算法工程师" }, "算法"), "exact");
});

test("中文连写词：词库外的具体词不得被丢弃（否则查询退化成搜泛词）", () => {
  // 「天线工程师」只有「工程师」命中预置组，「天线」在词库外。若按「整串含组词=已覆盖」处理，
  // 「天线」会被整个丢掉 → 查询等价于搜「工程师」→ 匹配上 Software Engineer / 销售工程师。
  const units = keywordMatchUnits("天线工程师");
  assert.equal(units.length, 2, "应拆成 [工程师组] AND [天线]");
  assert.ok(units.some((u) => u.includes("天线")), "词库外的「天线」必须自成 AND 单元");

  assert.ok(!jobMatchesChinaKeyword({ title: "Software Engineer", summary: "coding" }, "天线工程师"));
  assert.ok(!jobMatchesChinaKeyword({ title: "销售工程师", summary: "负责销售" }, "天线工程师"));
  assert.ok(jobMatchesChinaKeyword({ title: "天线工程师", summary: "负责天线设计" }, "天线工程师"));

  // 两段都在词库内时行为不变（不产生多余的残差单元）
  assert.equal(keywordMatchUnits("硬件工程师").length, 2);
  // 扣完组词只剩单字的碎片不成单元：「大数据工程师」不应因残差「大」而过严
  assert.ok(jobMatchesChinaKeyword({ title: "大数据工程师", summary: "数据平台" }, "大数据工程师"));
});

test("expands Chinese algorithm keywords to English terms", () => {
  const terms = expandChinaKeywordTerms("算法 实习 北京");

  assert.ok(terms.includes("算法"));
  assert.ok(terms.includes("机器学习"));
  assert.ok(terms.includes("machine learning"));
  assert.ok(terms.includes("algorithm"));
  assert.ok(terms.includes("intern"));
});

test("expands English analyst keywords to Chinese terms", () => {
  const terms = expandChinaKeywordTerms("data analyst intern");

  assert.ok(terms.includes("数据分析"));
  assert.ok(terms.includes("商业分析"));
  assert.ok(terms.includes("data analyst"));
  assert.ok(terms.includes("实习"));
});

test("matches English jobs from Chinese user keywords and Chinese jobs from English keywords", () => {
  assert.equal(
    jobMatchesChinaKeyword(
      { title: "Machine Learning Intern", summary: "Build ranking models" },
      "算法",
    ),
    true,
  );

  assert.equal(
    jobMatchesChinaKeyword(
      { title: "商业分析实习生", summary: "SQL 数据分析" },
      "business analyst",
    ),
    true,
  );
});

test("normalizes common China city aliases", () => {
  assert.equal(normalizeChinaCity("北京市"), "北京");
  assert.equal(normalizeChinaCity("Shanghai"), "上海");
  assert.equal(normalizeChinaCity("Hong Kong"), "香港");
  assert.equal(normalizeChinaCity("全国多地"), "全国");
});

test("expands province and region filters to their main matching cities without changing normalization", () => {
  assert.deepEqual(expandChinaCityTargets("陕西"), ["西安"]);
  assert.deepEqual(expandChinaCityTargets("长三角"), ["上海", "杭州", "南京", "苏州"]);
  assert.equal(normalizeChinaCity("陕西"), "陕西", "省份不能被归一为某一座岗位城市");
});

test("normalizes China job types from title, source type, URL and summary", () => {
  assert.equal(
    normalizeChinaJobType({ title: "2026校园招聘-算法工程师" }),
    "校招",
  );
  assert.equal(
    normalizeChinaJobType({ title: "暑期实习-数据分析", url: "/campus/intern" }),
    "暑期实习",
  );
  assert.equal(
    normalizeChinaJobType({ title: "管理培训生", summary: "graduate program" }),
    "管培生",
  );
  assert.equal(
    normalizeChinaJobType({ title: "投研研究员", summary: "行业研究" }),
    "研究岗",
  );
});

test("normalizes job fields without dropping original official URLs", () => {
  const job = normalizeChinaJobFields({
    title: "Data Analyst Intern",
    location: "Shanghai",
    summary: "SQL analytics internship",
    jd_url: "https://talent.baidu.com/jobs/detail/INTERN/abc",
  });

  assert.equal(job.location, "上海");
  assert.equal(job.job_type, "实习");
  assert.equal(job.jd_url, "https://talent.baidu.com/jobs/detail/INTERN/abc");
});

test("bilingual: Chinese keyword matches English foreign-company jobs", () => {
  assert.ok(jobMatchesChinaKeyword({ title: "Machine Learning Engineer", location: "Beijing" }, "人工智能"));
  assert.ok(jobMatchesChinaKeyword({ title: "Senior Product Manager" }, "pm"));
  assert.ok(jobMatchesChinaKeyword({ title: "Frontend Engineer" }, "前端"));
  assert.ok(jobMatchesChinaKeyword({ title: "Backend Developer (Golang)" }, "后端"));
  assert.ok(jobMatchesChinaKeyword({ title: "Data Scientist" }, "数据分析"));
});

test("short latin codes use word boundaries (no false positives)", () => {
  // 'ai' should not match inside 'Maintenance'; 'go' not inside 'Google'
  assert.equal(jobMatchesChinaKeyword({ title: "Maintenance Technician" }, "ai"), false);
  assert.equal(jobMatchesChinaKeyword({ title: "Google Product role" }, "go"), false);
  // but real standalone codes still match
  assert.ok(jobMatchesChinaKeyword({ title: "AI Engineer" }, "ai"));
});

test("short terms only match titles; long synonyms in the same unit can still match the body", () => {
  const unrelatedEngineer = { title: "客户端开发工程师", summary: "负责单元测试与质量保障" };
  assert.equal(jobMatchesChinaKeyword(unrelatedEngineer, "测试工程师"), false);
  assert.equal(jobMatchesChinaKeyword({ title: "测试工程师", summary: "负责单元测试" }, "测试工程师"), true);
  assert.equal(
    jobMatchesChinaKeyword({ title: "高级工程师", summary: "负责测试开发与自动化平台" }, "测试工程师"),
    true,
    "同一概念单元内的长词仍可正文命中",
  );
});

test("short custom terms cannot match content but can still match a company or title", () => {
  assert.equal(jobMatchesChinaKeyword({ title: "前端工程师", company: "字节跳动" }, "字节"), true);
  assert.equal(
    jobMatchesChinaKeyword({ title: "销售经理", summary: "负责新材料产品的市场推广" }, "材料"),
    false,
  );
  assert.equal(
    jobMatchesChinaKeyword({ title: "财务专员", summary: "熟悉工艺流程成本核算" }, "工艺"),
    false,
  );
  assert.equal(jobMatchesChinaKeyword({ title: "材料工程师" }, "材料"), true);
});

test("ftsCandidateTerms: 命中组的跨语言同义词，全部 >=2 字，不并入同职能兄弟组（供 FTS 收窄预筛）", () => {
  const pm = ftsCandidateTerms("产品");
  assert.ok(pm.includes("产品"));
  assert.ok(pm.includes("产品经理"));
  assert.ok(pm.includes("product manager") || pm.includes("product")); // 跨语言：命中英文标题
  assert.ok(pm.every((t) => t.length >= 2)); // 1 字过滤掉
  // 「前端」只取前端组(含跨语言 react/frontend)，**不**拉同职能(研发)的后端/算法等兄弟组 → 候选紧、搜索快且精准
  const fe = ftsCandidateTerms("前端");
  assert.ok(fe.includes("前端"));
  assert.ok(fe.some((t) => ["frontend", "react", "vue", "front end"].includes(t)));
  assert.ok(!fe.includes("后端") && !fe.includes("算法"));
  assert.deepEqual(ftsCandidateTerms(""), []);
});

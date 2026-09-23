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

test("normalizeRolePhrases：斜杠=或、去填充后缀、去办公室修饰，剥空了保留原样", () => {
  const { normalizeRolePhrases } = require("../lib/china-keyword-expansion.js");
  assert.deepEqual(normalizeRolePhrases(["项目专员/助理"]), ["项目专员", "助理"]);
  assert.deepEqual(normalizeRolePhrases(["英文相关", "技术岗位"]), ["英文", "技术"]);
  assert.deepEqual(normalizeRolePhrases(["办公室文员", "仓库文员"]), ["文员", "仓库文员"]);
  assert.deepEqual(normalizeRolePhrases(["产品经理"]), ["产品经理"]);
  assert.deepEqual(normalizeRolePhrases(["岗位", "  "]), ["岗位"]);   // 只剩填充词 → 保留原样
  assert.deepEqual(normalizeRolePhrases("AI 产品经理"), ["AI 产品经理"]);
});

// 角色簇门：只靠领域锚点（数据 / 产品 / 品牌 / 财务）命中标题、而标题的角色词属于另一个角色簇 →
// 不算同角色精确匹配。下面每条都是 2026-09-17 真实库对拍里被独立裁判判「不是同一个角色」的岗，
// 全部 roleTier=exact 混进了 top-25 主清单（不是「拓展看看」，用户真会看到）。
test("角色簇门：领域锚点命中标题但角色属于别的簇 → 不算 exact", () => {
  const job = (title) => ({ title, company: "某公司", summary: null });
  for (const [query, title] of [
    ["数据分析师", "大数据开发负责人"],
    ["数据分析师", "零部件数据工程师"],
    ["数据分析师", "大模型训练数据工程师（数据算子与流水线方向）"],
    ["AI 产品经理", "AI产品运营-AI工具运营"],
    ["AI 产品经理", "大模型MaaS网关产品运营专家"],
    ["品牌营销", "品牌设计-个护BG"],
    ["产品经理", "产品运营专家"],
    ["审计", "财务科技（ERP方向）- 全栈开发工程师"],
  ]) {
    assert.notEqual(keywordMatchTier(job(title), query), "exact", `${query} 不该精确匹配 ${title}`);
  }
});

test("角色簇门不误杀：查询自己的角色词在标题里 → 照常 exact", () => {
  const job = (title) => ({ title, company: "某公司", summary: null });
  for (const [query, title] of [
    ["数据分析师", "数据分析师"],
    ["数据分析师", "商业分析师"],
    ["数据分析师", "数据分析专家-商业分析"],
    ["AI 产品经理", "AI产品经理"],
    ["产品经理", "产品经理-电商"],
    ["产品经理", "高级产品专家"], // 组里只有锚点命中，但没有任何别的角色簇来认领 → 不拦
    ["数据", "Data Engineer"], // ④ 查询只写领域词 = 要整个领域，不替他划掉任何角色
    ["产品", "产品运营专家"],
    ["品牌营销", "品牌营销经理"],
    ["品牌营销", "市场部品牌公关"],
    ["审计", "审计经理"],
    ["财务分析", "财务分析师"],
    ["前端开发工程师", "前端开发工程师"],
    ["算法工程师", "推荐算法工程师"],
    // 下面三条是这道门**自己误杀过**的真岗（2026-09-17 对拍：品牌营销画像 top-25 里三个 same_role
    // 被剔掉）。反向计数必须一起钉，否则「准确率涨了」只是把好岗一起杀掉换来的。
    ["品牌营销", "商务管理 -品牌中心"],
    ["品牌营销", "海外市场商务专员"],
    ["品牌营销", "蔚来公司品牌传播（先进制造及质量方向）"],
  ]) {
    assert.equal(keywordMatchTier(job(title), query), "exact", `${query} 应精确匹配 ${title}`);
  }
});

test("领域锚点表只许放领域词：角色词进表会让对应角色簇失去认领能力", () => {
  const { GROUP_DOMAIN_ANCHORS } = require("../lib/china-keyword-expansion");
  // 「设计」「运营」「销售」「全栈」「大数据」是角色词，正是它们把上面那些岗认领走的。
  // 谁把它们挪进锚点表，这条修法当场失效 → 钉死。
  const forbidden = ["设计", "运营", "销售", "全栈", "大数据", "数据工程", "会计", "审计", "财务分析"];
  for (const [idx, anchors] of GROUP_DOMAIN_ANCHORS) {
    for (const a of anchors) {
      assert.ok(!forbidden.includes(a), `${a} 是角色词，不能当领域锚点`);
      // 锚点必须真属于它声明的那个组，否则是拼错了（错字会静默失效、不报错）。
      assert.ok(
        CHINA_KEYWORD_GROUPS[idx].some((t) => String(t).toLowerCase() === a.toLowerCase()),
        `组 ${idx} 里没有 ${a}`,
      );
    }
  }
});

// 2026-09-18 学生画像走查补词表：11 行业校招走查里 9 个方向几乎搜不到（投行分析师/药物研发/
// 临床研究/门店管培/编导/仓储运营/售后服务/工程管理/造价），全量库内对拍（336510 条 distinct
// active 标题）逐条核实后补充。每条同义词都在 lib/china-keyword-expansion.js 对应组的注释里
// 带库内命中数；这里只钉行为，不重复列证据。
test("投行分析师方向：新增投行/并购组能精确命中国内券商真实标题（不靠「分析师」三字）", () => {
  const job = (title) => ({ title });
  for (const title of [
    "投行业务岗（先进制造方向）",
    "承做业务岗（并购组）",
    "债券承做岗(009759)",
    "投资银行部",
    "Investment Banking Analyst",
  ]) {
    assert.equal(keywordMatchTier(job(title), "投行分析师"), "exact", `投行分析师 应精确匹配 ${title}`);
  }
  // 与既有「投资交易」组（买方投研/交易）分属不同角色簇，互不精确命中。
  assert.notEqual(jobMatchesChinaKeyword({ title: "证券研究员" }, "投行分析师"), true);
});

test("药物研发方向：新增药学角色词命中 CDMO/合成研究员真实标题，且不再被 21 组泛锚点误挡", () => {
  const job = (title) => ({ title });
  for (const title of [
    "2026届-博士-有机合成研究员-北京总部",
    "制剂分析研究员-北京",
    "药理毒理总监级",
    "原料药合成实验员(J11081)",
    "药物化学研究员(J16619)",
    "CMC Director",
  ]) {
    assert.equal(keywordMatchTier(job(title), "药物研发"), "exact", `药物研发 应精确匹配 ${title}`);
  }
});

test("临床研究方向：医学经理/临床运营纳入同一角色簇", () => {
  const job = (title) => ({ title });
  assert.equal(keywordMatchTier(job("医学经理(J22026)"), "临床研究"), "exact");
  assert.equal(keywordMatchTier(job("临床运营部：临床项目总监"), "临床研究"), "exact");
});

test("造价方向：预算员纳入建筑工程角色簇", () => {
  assert.equal(keywordMatchTier({ title: "2027届校招一公司预算员" }, "造价"), "exact");
});

test("仓储运营方向：仓储/仓库/仓管纳入供应链组，且「数据仓库」假朋友不被误吃", () => {
  const job = (title) => ({ title });
  assert.equal(jobMatchesChinaKeyword(job("仓库管理员"), "仓储"), true);
  assert.equal(jobMatchesChinaKeyword(job("仓储主管"), "仓储"), true);
  // 「数据仓库」是数据工程概念，不该被供应链组的「仓库」词抢成"已被供应链认领"，
  // 否则会把它从「数据分析」这类查询的候选里挤掉（2026-09-18 全量对拍实测发现）。
  assert.equal(jobMatchesChinaKeyword(job("Data Warehouse Engineer"), "数据分析"), true);
  assert.equal(jobMatchesChinaKeyword(job("数据仓库开发工程师-国际化业务"), "数据分析"), true);
});

test("售后服务/门店管培方向：残差后缀词修复后不再要求字面二次出现", () => {
  const job = (title) => ({ title });
  // 「售后工程师/售后运营」不含"服务"二字，此前会被残差 AND 单元挡住。
  assert.equal(keywordMatchTier(job("2027-国内售后工程师（惠州）"), "售后服务"), "exact");
  assert.equal(keywordMatchTier(job("售后运营培训生-东南亚"), "售后服务"), "exact");
  // 「储备店长」不含"管培"二字，此前会被残差 AND 单元挡住。
  assert.equal(keywordMatchTier(job("特步-储备店长（云南）"), "门店管培"), "exact");
});

test("编导方向：新增内容制作组命中真实标题，且不收裸「剪辑」「主播」「策划」避免跨领域噪音", () => {
  const job = (title) => ({ title });
  for (const title of ["米哈游 视频编导", "阿里巴巴 动漫制片", "游戏动画导演（2027届）", "视频剪辑专员(J25948)"]) {
    assert.equal(jobMatchesChinaKeyword(job(title), "编导"), true, `编导 应命中 ${title}`);
  }
  // 反例：这两类此前调研过、因跨领域噪音（AI 剪辑软件研发/电商直播带货）未收录，标题不应仅凭
  // 裸出现就被本组认领为"编导"角色（它们各自另有更贴切的方向，这里只断言不属于本组精确匹配）。
  assert.notEqual(jobMatchesChinaKeyword({ title: "客户端开发工程师（PC端基础剪辑）" }, "编导"), true);
});

test("泛锚点组（工程师/研发/软件）在具体方向组已命中时不再独立成 AND 单元（2026-09-18 修复）", () => {
  // 根因回归：「机械工程师」此前被拆成 [21组] AND [36组] AND 残差["机械"] 三层 AND，
  // 纯英文标题因为不含中文字"机械"被挡在外面。修复后只剩 36 组一层。
  assert.equal(
    jobMatchesChinaKeyword({ title: "Principal Mechanical Engineer, Industrial Robotics Group" }, "机械工程师"),
    true,
  );
  // AI 领域组(24)的复合 AND 语义必须保留（不在 GENERIC_ENGINE_FALLBACK_INDEXES 里）。
  assert.equal(jobMatchesChinaKeyword({ title: "资深产品经理" }, "AI 产品经理"), false);
  assert.equal(jobMatchesChinaKeyword({ title: "AI产品经理" }, "AI 产品经理"), true);
  // 只写泛词、没有具体方向组命中时，21/22 组仍独立生效（不能连这条也删掉）。
  assert.equal(jobMatchesChinaKeyword({ title: "天线工程师" }, "天线工程师"), true);
  assert.equal(jobMatchesChinaKeyword({ title: "纯销售岗，无工程内容" }, "天线工程师"), false);
});

test("CMC/制剂登记为药学组的领域锚点，不误杀产品经理等其它角色查询（2026-09-18 修复）", () => {
  // 这两个标题的真实角色是"产品经理/医学经理"而非"药学研发"，只是标题里带了 CMC/制剂 当限定语。
  assert.equal(jobMatchesChinaKeyword({ title: "CMC Lead, Launch Product, Small Molecules" }, "产品经理"), true);
});

// 2026-09-23 走查：「ic验证」「风控」画像推荐页只剩 5 / 1 张。库里同城同阶段的真岗是有的，只是叫法不同
// （芯片验证 / 数字验证；信用风险 / 市场风险 / 风险管理），查询只剩字面一个词，全被方向门拒掉。
// 两个方向都钉：新叫法要命中，看着像但不是同一个角色的也要挡住（证据见 CHINA_KEYWORD_GROUPS 索引 48/49 注释）。
test("芯片验证方向：ic验证 能认出芯片/数字/逻辑验证等真实叫法，不吃芯片设计和非芯片的验证岗", () => {
  for (const title of [
    "芯片验证工程师（上海）",
    "数字验证工程师-2027届校招",
    "逻辑验证工程师-27届",
    "芯片/处理器验证工程师",
    "SoC验证工程师-互联芯片",
    "Design Verification Engineer",
    "2027校招-GPGPU芯片验证工程师",
    "数字IC验证工程师（2027届）",
  ]) {
    assert.equal(keywordMatchTier({ title }, "ic验证"), "exact", `ic验证 应精确命中「${title}」`);
  }
  for (const title of [
    "芯片设计工程师",
    "硬件工程师",
    "小米汽车-热管理设计验证高级工程师/专家",
    "电芯验证工程师-国际工程研究院",
    "DS MSAT技术转移和工艺验证工程师",
    "系统验证工程师（风机）",
  ]) {
    assert.notEqual(keywordMatchTier({ title }, "ic验证"), "exact", `ic验证 不该精确命中「${title}」`);
  }
});

test("风控方向：风控 能认出券商/银行的「XX风险」岗名，不吃裸「风险」的非风控岗", () => {
  for (const title of [
    "信用风险实习生",
    "市场风险管理岗",
    "操作风险岗(J11318)",
    "全面风险管理岗(J19194)",
    "风险管理实习生",
    "风险控制岗（招商资管）",
    "【2027】风险分析员岗(J19682)",
  ]) {
    assert.equal(keywordMatchTier({ title }, "风控"), "exact", `风控 应精确命中「${title}」`);
  }
  for (const title of [
    "反入侵安全专家（风险检测/处置）",
    "阿里云智能-IDC风险运营专家-杭州",
    "市场营销专员",
  ]) {
    assert.notEqual(keywordMatchTier({ title }, "风控"), "exact", `风控 不该精确命中「${title}」`);
  }
  // 反方向：「风控」在标题里常是业务域——风控组不许凭它把别的角色的岗认领走（对拍实测误杀过这一条）
  assert.equal(keywordMatchTier({ title: "账号风控产品实习生" }, "产品经理"), "exact");
  assert.equal(keywordMatchTier({ title: "风控平台产品经理（AI Native 方向）" }, "产品经理"), "exact");
});

// 公司 → 行业 确定性分类器（求职雷达「行业-公司-岗位」三层认知的地基，见记忆
// job-radar-industry-company-position-model）。岗位的行业从其**公司**派生：打分时
// 现算（job.company 本就带），零跨库、零迁移、零 API、可单测；算不出 → null → 放行（不误杀）。
//
// 设计：
//   1. 输出 = 下方 INDUSTRY_CATEGORIES 之一（须与 lib/industries.ts 的 INDUSTRIES 对齐）或 null。
//   2. 先查「大厂名映射」（substring，治名字不带行业词的品牌，如 农夫山泉/字节）→ 再走「关键词规则」。
//   3. 用户自填行业（candidate_profiles.industries 自由文本）经 canonicalizeUserIndustry 归一到同一类目空间再比对。
//   4. 保守：岗位行业未知 或 用户没填目标行业 → 不设门（放行），不拿缺数据误杀（沿用项目「信息不足放行」原则）。

// 须与 lib/industries.ts 的 INDUSTRIES 同口径（那是 .ts、node --test 不可 require，故此处镜像；改一处同步另一处）。
const INDUSTRY_CATEGORIES = [
  "互联网/科技",
  "金融",
  "消费/零售",
  "制造/工业",
  "汽车/出行",
  "医疗/医药",
  "能源/化工",
  "地产/建筑",
  "物流/供应链",
  "传媒/文娱",
  "教育",
];

function normalizeCompany(value) {
  return String(value || "").toLowerCase().replace(/\s+/g, " ").trim();
}

// 大厂/知名品牌名 → 行业（substring 命中，优先于关键词规则）。
// 治「名字不含行业词」的品牌（农夫山泉/字节/蔚来…）+ 纠正关键词会误判的（京东含『东』无意义、比亚迪是车不是泛制造）。
// 按 DB 实际产出（偏 车厂/制造/央企 + 外企）挑高频高价值公司；覆盖不全无妨——未命中走关键词、再不行 null 放行。
const COMPANY_OVERRIDES = [
  // 互联网/科技
  ["字节跳动", "互联网/科技"], ["抖音", "互联网/科技"], ["腾讯", "互联网/科技"], ["阿里巴巴", "互联网/科技"],
  ["阿里云", "互联网/科技"], ["蚂蚁集团", "金融"], ["百度", "互联网/科技"], ["美团", "互联网/科技"],
  ["快手", "互联网/科技"], ["拼多多", "互联网/科技"], ["京东", "互联网/科技"], ["网易", "互联网/科技"],
  ["小红书", "互联网/科技"], ["哔哩哔哩", "互联网/科技"], ["bilibili", "互联网/科技"], ["微博", "互联网/科技"],
  ["携程", "互联网/科技"], ["华为", "互联网/科技"], ["小米", "互联网/科技"], ["大疆", "互联网/科技"],
  ["海康威视", "互联网/科技"], ["商汤", "互联网/科技"], ["旷视", "互联网/科技"], ["科大讯飞", "互联网/科技"],
  ["apple", "互联网/科技"], ["microsoft", "互联网/科技"], ["google", "互联网/科技"], ["amazon", "互联网/科技"],
  ["meta", "互联网/科技"], ["nvidia", "互联网/科技"], ["amd", "互联网/科技"], ["intel", "互联网/科技"],
  // 汽车/出行
  ["比亚迪", "汽车/出行"], ["蔚来", "汽车/出行"], ["理想汽车", "汽车/出行"], ["小鹏", "汽车/出行"],
  ["吉利", "汽车/出行"], ["长城汽车", "汽车/出行"], ["广汽", "汽车/出行"], ["上汽", "汽车/出行"],
  ["一汽", "汽车/出行"], ["长安汽车", "汽车/出行"], ["奇瑞", "汽车/出行"], ["滴滴", "汽车/出行"],
  ["宁德时代", "能源/化工"], ["tesla", "汽车/出行"], ["特斯拉", "汽车/出行"],
  // 消费/零售
  ["农夫山泉", "消费/零售"], ["养生堂", "消费/零售"], ["蒙牛", "消费/零售"], ["伊利", "消费/零售"],
  ["海天", "消费/零售"], ["双汇", "消费/零售"], ["光明乳业", "消费/零售"], ["安踏", "消费/零售"],
  ["李宁", "消费/零售"], ["名创优品", "消费/零售"], ["欧莱雅", "消费/零售"], ["宝洁", "消费/零售"],
  ["联合利华", "消费/零售"], ["百事", "消费/零售"], ["可口可乐", "消费/零售"], ["雀巢", "消费/零售"],
  // 金融
  ["招商银行", "金融"], ["工商银行", "金融"], ["建设银行", "金融"], ["中国银行", "金融"],
  ["农业银行", "金融"], ["平安", "金融"], ["中国人寿", "金融"], ["太平洋保险", "金融"],
  ["微众银行", "金融"], ["陆金所", "金融"], ["华夏银行", "金融"],
  // 医疗/医药
  ["恒瑞", "医疗/医药"], ["药明康德", "医疗/医药"], ["迈瑞", "医疗/医药"], ["复星医药", "医疗/医药"],
  ["智飞", "医疗/医药"], ["百济神州", "医疗/医药"], ["pfizer", "医疗/医药"], ["novartis", "医疗/医药"],
  ["roche", "医疗/医药"], ["astrazeneca", "医疗/医药"],
  // 能源/化工
  ["隆基", "能源/化工"], ["中石油", "能源/化工"], ["中石化", "能源/化工"], ["国家电网", "能源/化工"],
  ["协鑫", "能源/化工"], ["万华化学", "能源/化工"],
  // 制造/工业
  ["富士康", "制造/工业"], ["立讯精密", "制造/工业"], ["三一", "制造/工业"], ["潍柴", "制造/工业"],
  ["中联重科", "制造/工业"], ["徐工", "制造/工业"], ["siemens", "制造/工业"], ["西门子", "制造/工业"],
  ["abb", "制造/工业"], ["施耐德", "制造/工业"], ["博世", "汽车/出行"],
  // 物流/供应链
  ["顺丰", "物流/供应链"], ["货拉拉", "物流/供应链"], ["中通", "物流/供应链"], ["圆通", "物流/供应链"],
  ["菜鸟", "物流/供应链"], ["京东物流", "物流/供应链"], ["满帮", "物流/供应链"],
  // 地产/建筑
  ["万科", "地产/建筑"], ["保利", "地产/建筑"], ["中建", "地产/建筑"], ["碧桂园", "地产/建筑"],
  ["龙湖", "地产/建筑"],
  // 传媒/文娱
  ["爱奇艺", "传媒/文娱"], ["芒果", "传媒/文娱"], ["阅文", "传媒/文娱"], ["米哈游", "互联网/科技"],
  // 教育
  ["新东方", "教育"], ["好未来", "教育"], ["学而思", "教育"],
];

// 行业关键词规则（公司名含该词 → 行业）。顺序敏感：更具体/易误判的在前。
// 命中即返回，故把「汽车/医药/金融」等强信号放在「制造/科技」等泛信号之前，避免被泛词抢先。
const INDUSTRY_KEYWORD_RULES = [
  ["金融", /银行|证券|保险|基金|信托|期货|资管|财险|寿险|金融|支付|消费金融|小额贷|bank|securities|insurance|capital/i],
  ["医疗/医药", /医药|制药|药业|药品|生物医药|生物科技|医疗|医院|健康|基因|诊断|器械|pharma|biotech|medical|health/i],
  ["汽车/出行", /汽车|整车|车业|新能源车|乘用车|商用车|车联网|出行|motors|automotive/i],
  ["能源/化工", /能源|电力|电网|石油|石化|化工|化学|新能源|光伏|风电|储能|电池|燃气|煤业|核电|energy|power|chemical|petro/i],
  ["物流/供应链", /物流|快递|供应链|仓储|货运|运输|冷链|logistics|express|supply\s*chain/i],
  ["地产/建筑", /地产|置业|房产|建筑|建设|建工|工程局|装饰|幕墙|real\s*estate|construction|properties/i],
  ["教育", /教育|学校|培训|学院|课程|留学|education|academy/i],
  ["传媒/文娱", /传媒|影视|文化|娱乐|院线|音乐|动漫|文娱|出版|media|entertainment/i],
  ["消费/零售", /食品|饮料|乳业|乳品|零售|商超|百货|便利店|美妆|化妆品|日化|服饰|服装|鞋业|家居|家电|餐饮|连锁|消费|快消|retail|consumer|foods?|beverage/i],
  ["制造/工业", /制造|机械|重工|工业|装备|设备|电子|半导体|芯片|集成电路|材料|钢铁|有色|精密|模具|纺织|轻工|manufactur|industrial|electronics|semiconductor/i],
  ["互联网/科技", /互联网|科技|网络|信息技术|软件|数码|智能|大数据|云计算|游戏|网游|人工智能|物联网|tech|software|digital|internet|\bai\b|cloud/i],
];

// 公司 → 行业类目（或 null=判不出）。
function classifyCompanyIndustry(company) {
  const text = normalizeCompany(company);
  if (!text) return null;
  for (const [name, cat] of COMPANY_OVERRIDES) {
    if (text.includes(normalizeCompany(name))) return cat;
  }
  for (const [cat, rule] of INDUSTRY_KEYWORD_RULES) {
    if (rule.test(text)) return cat;
  }
  return null;
}

// 用户自填行业（自由文本，如「互联网」「快消」「生物医药」）→ 归一到 INDUSTRY_CATEGORIES 之一（或 null）。
// 用别名/子串映射，让用户的口语化输入对齐分类器类目空间。
const USER_INDUSTRY_ALIASES = [
  ["互联网/科技", /互联网|科技|信息技术|软件|计算机|it|tech|游戏|人工智能|\bai\b|大数据|云/i],
  ["金融", /金融|银行|证券|保险|基金|投资|fintech|finance/i],
  ["消费/零售", /消费|零售|快消|fmcg|电商|食品|饮料|美妆|服装|retail|consumer/i],
  ["制造/工业", /制造|工业|机械|电子|半导体|芯片|材料|硬件|manufactur|industrial/i],
  ["汽车/出行", /汽车|车|出行|新能源车|automotive/i],
  ["医疗/医药", /医疗|医药|生物|制药|健康|器械|pharma|bio|medical|health/i],
  ["能源/化工", /能源|电力|化工|化学|新能源|光伏|电池|energy|chemical/i],
  ["地产/建筑", /地产|房地产|建筑|建设|工程|real\s*estate|construction/i],
  ["物流/供应链", /物流|供应链|快递|运输|logistics|supply/i],
  ["传媒/文娱", /传媒|文娱|影视|文化|娱乐|内容|media|entertainment/i],
  ["教育", /教育|培训|edu/i],
];

function canonicalizeUserIndustry(value) {
  const text = normalizeCompany(value);
  if (!text) return null;
  // 已是规范类目则直接用。
  if (INDUSTRY_CATEGORIES.includes(value)) return value;
  for (const [cat, rule] of USER_INDUSTRY_ALIASES) {
    if (rule.test(text)) return cat;
  }
  return null;
}

// 把用户自填行业数组归一成规范类目集合（去 null/去重）。
function userTargetIndustryCategories(userIndustries) {
  const out = new Set();
  for (const raw of userIndustries || []) {
    const cat = canonicalizeUserIndustry(raw);
    if (cat) out.add(cat);
  }
  return out;
}

// 跨行业门判定：用户岗位是否「行业相容」。
// 放行（返回 true）当：用户没填可识别行业 / 岗位行业判不出（缺数据不误杀）/ 行业落在用户目标集合内。
// 拦截（返回 false）仅当：用户有明确目标行业 且 岗位行业已知 且 不在目标集合内（治「同职能跨行业」误命中）。
function jobIndustryAllowed(company, userIndustries) {
  const targets = userTargetIndustryCategories(userIndustries);
  if (targets.size === 0) return true;
  const jobCat = classifyCompanyIndustry(company);
  if (!jobCat) return true;
  return targets.has(jobCat);
}

module.exports = {
  INDUSTRY_CATEGORIES,
  classifyCompanyIndustry,
  canonicalizeUserIndustry,
  userTargetIndustryCategories,
  jobIndustryAllowed,
};

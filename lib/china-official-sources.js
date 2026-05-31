const {
  expandChinaKeywordTerms,
  normalizeChinaCity,
  normalizeChinaJobType,
} = require("./china-keyword-expansion");

const CHINA_PRIORITY_SOURCES = [
  {
    source_name: "腾讯",
    company: "腾讯",
    url: "https://careers.tencent.com/",
    hosts: ["careers.tencent.com"],
  },
  {
    source_name: "阿里巴巴",
    company: "阿里巴巴",
    url: "https://talent.alibaba.com/",
    hosts: ["talent.alibaba.com"],
  },
  {
    source_name: "字节跳动",
    company: "字节跳动",
    url: "https://jobs.bytedance.com/",
    hosts: ["jobs.bytedance.com"],
  },
  {
    source_name: "美团",
    company: "美团",
    url: "https://zhaopin.meituan.com/",
    hosts: ["zhaopin.meituan.com"],
  },
  {
    source_name: "京东",
    company: "京东",
    url: "https://zhaopin.jd.com/",
    hosts: ["zhaopin.jd.com"],
  },
  {
    source_name: "百度",
    company: "百度",
    url: "https://talent.baidu.com/jobs/social-list",
    hosts: ["talent.baidu.com"],
  },
  {
    source_name: "华为",
    company: "华为",
    url: "https://career.huawei.com/",
    hosts: ["career.huawei.com"],
  },
  {
    source_name: "中国移动",
    company: "中国移动",
    url: "https://job.10086.cn/",
    hosts: ["job.10086.cn"],
  },
  {
    source_name: "招商银行",
    company: "招商银行",
    url: "https://career.cmbchina.com/",
    hosts: ["career.cmbchina.com"],
  },
  {
    source_name: "Siemens 中国",
    company: "Siemens",
    url: "https://jobs.siemens.com.cn/siemens/position/index",
    hosts: ["jobs.siemens.com.cn", "jobs.siemens.com"],
    source_type: "foreign_company_china",
  },
  {
    source_name: "快手",
    company: "快手",
    url: "https://zhaopin.kuaishou.cn/",
    hosts: ["zhaopin.kuaishou.cn"],
  },
  {
    source_name: "小红书",
    company: "小红书",
    url: "https://job.xiaohongshu.com/",
    hosts: ["job.xiaohongshu.com", "jobs.xiaohongshu.com"],
  },
  {
    source_name: "网易",
    company: "网易",
    url: "https://hr.163.com/",
    hosts: ["hr.163.com"],
  },
  {
    source_name: "携程",
    company: "携程",
    url: "https://careers.ctrip.com/",
    hosts: ["careers.ctrip.com"],
  },
  {
    source_name: "滴滴",
    company: "滴滴",
    url: "https://talent.didiglobal.com/",
    hosts: ["talent.didiglobal.com"],
  },
  {
    source_name: "B站",
    company: "B站",
    url: "https://jobs.bilibili.com/",
    hosts: ["jobs.bilibili.com"],
  },
  {
    source_name: "小米",
    company: "小米",
    url: "https://xiaomi.jobs.f.mioffice.cn/",
    hosts: ["xiaomi.jobs.f.mioffice.cn", "xiaomi.jobs.feishu.cn"],
  },
  {
    source_name: "联想",
    company: "联想",
    url: "https://jobs.lenovo.com/",
    hosts: ["jobs.lenovo.com"],
  },
  {
    source_name: "OPPO",
    company: "OPPO",
    url: "https://careers.oppo.com/",
    hosts: ["careers.oppo.com"],
  },
  {
    source_name: "vivo",
    company: "vivo",
    url: "https://hr.vivo.com/",
    hosts: ["hr.vivo.com"],
  },
  {
    source_name: "比亚迪",
    company: "比亚迪",
    url: "https://job.byd.com/",
    hosts: ["job.byd.com"],
  },
  {
    source_name: "宁德时代",
    company: "宁德时代",
    url: "https://talent.catl.com/",
    hosts: ["talent.catl.com"],
  },
  {
    source_name: "理想汽车",
    company: "理想汽车",
    url: "https://www.lixiang.com/employ",
    hosts: ["www.lixiang.com", "lixiang.com"],
  },
  {
    source_name: "蔚来",
    company: "蔚来",
    url: "https://nio.jobs.feishu.cn/",
    hosts: ["nio.jobs.feishu.cn"],
  },
  {
    source_name: "小鹏汽车",
    company: "小鹏汽车",
    url: "https://xiaopeng.jobs.feishu.cn/",
    hosts: ["xiaopeng.jobs.feishu.cn"],
  },
  {
    source_name: "大疆",
    company: "大疆",
    url: "https://we.dji.com/zh-CN/career",
    hosts: ["we.dji.com"],
  },
  {
    source_name: "海尔",
    company: "海尔",
    url: "https://maker.haier.net/client/job/index",
    hosts: ["maker.haier.net"],
  },
  {
    source_name: "美的",
    company: "美的",
    url: "https://careers.midea.com/",
    hosts: ["careers.midea.com"],
  },
  {
    source_name: "格力",
    company: "格力",
    url: "https://zhaopin.gree.com/",
    hosts: ["zhaopin.gree.com"],
  },
  {
    source_name: "商汤",
    company: "商汤",
    url: "https://www.sensetime.com/cn/join-index",
    hosts: ["www.sensetime.com", "sensetime.com"],
  },
  {
    source_name: "寒武纪",
    company: "寒武纪",
    url: "https://www.cambricon.com/joinus/job",
    hosts: ["www.cambricon.com", "cambricon.com"],
  },
  {
    source_name: "地平线",
    company: "地平线",
    url: "https://horizon.jobs.feishu.cn/",
    hosts: ["horizon.jobs.feishu.cn"],
  },
  {
    source_name: "中金",
    company: "中金",
    url: "https://career.cicc.com/",
    hosts: ["career.cicc.com"],
  },
  {
    source_name: "中信证券",
    company: "中信证券",
    url: "https://careers.citics.com/",
    hosts: ["careers.citics.com"],
  },
  {
    source_name: "华泰证券",
    company: "华泰证券",
    url: "https://job.htsc.com.cn/",
    hosts: ["job.htsc.com.cn"],
  },
  {
    source_name: "国泰君安",
    company: "国泰君安",
    url: "https://career.gtja.com/",
    hosts: ["career.gtja.com"],
  },
  {
    source_name: "SHLAB",
    company: "shlab",
    url: "https://www.shlab.org.cn/joinus",
    hosts: ["www.shlab.org.cn"],
    source_type: "official_campus",
  },
  {
    source_name: "鹏城实验室",
    company: "鹏城实验室",
    url: "https://www.pcl.ac.cn/html/943/",
    hosts: ["www.pcl.ac.cn", "pcl.ac.cn"],
  },
  {
    source_name: "之江实验室",
    company: "之江实验室",
    url: "https://www.zhejianglab.com/career",
    hosts: ["www.zhejianglab.com", "zhejianglab.com"],
  },
  {
    source_name: "北京智源人工智能研究院",
    company: "北京智源人工智能研究院",
    url: "https://www.baai.ac.cn/join",
    hosts: ["www.baai.ac.cn", "baai.ac.cn"],
  },
].map((source) => ({
  source_type: "official_careers",
  detected_platform: "official_careers",
  confidence: 0.82,
  reason: "优先中国官方招聘源，等待审核或专用 parser",
  parser_supported: false,
  ...source,
}));

function buildChinaPrioritySourceCandidates({ query, company } = {}) {
  const companyFilter = normalizeCompany(company);
  const sources = companyFilter
    ? CHINA_PRIORITY_SOURCES.filter((source) =>
        normalizeCompany(source.company).includes(companyFilter) ||
        normalizeCompany(source.source_name).includes(companyFilter) ||
        companyFilter.includes(normalizeCompany(source.company)),
      )
    : CHINA_PRIORITY_SOURCES;

  return sources.map((source) => ({
    source_name: source.source_name,
    company: source.company,
    title: String(query || "").trim() || `${source.source_name} 官方招聘源`,
    url: source.url,
    source_type: source.source_type,
    detected_platform: source.detected_platform,
    confidence: source.confidence,
    status: "pending",
    reason: source.reason,
    parser_supported: source.parser_supported,
  }));
}

function buildChinaDiscoveryQueries({ query, company, city, jobType } = {}) {
  const normalized = normalizeDiscoveryInput({ query, city, jobType });
  const keyword = compactWords([
    normalized.role,
    normalized.jobType,
    normalized.city,
  ]);
  const companyName = String(company || "").trim();
  const queries = [];

  queries.push(
    compactWords([keyword, "招聘 官网"]),
    compactWords([keyword, "校招 官网"]),
    compactWords([keyword, "职位详情"]),
    compactWords([keyword, "社招 官网"]),
    compactWords([keyword, "官方招聘"]),
    compactWords([keyword, "人才招聘"]),
    compactWords([keyword, "校园招聘"]),
    compactWords([keyword, "社会招聘"]),
    compactWords([keyword, "加入我们"]),
    compactWords([keyword, "招聘信息"]),
  );

  if (companyName) {
    queries.push(
      compactWords([companyName, keyword, "招聘 官网"]),
      compactWords([companyName, keyword, "官方招聘"]),
      compactWords([companyName, keyword, "校招 社招"]),
    );
  }

  const expansionTerms = expandChinaKeywordTerms(normalized.role || query)
    .filter((term) => /[\u4e00-\u9fff]/.test(term))
    .filter((term) => !normalizeCompact(keyword).includes(normalizeCompact(term)))
    .slice(0, 4);
  for (const term of expansionTerms) {
    queries.push(compactWords([term, normalized.jobType, normalized.city, "官方招聘"]));
  }

  queries.push(
    compactWords([keyword, "中国 公司 官方招聘"]),
    compactWords([keyword, "央企 国企 银行 券商 官方招聘"]),
    compactWords([keyword, "外企 中国 官方招聘"]),
  );

  return Array.from(new Set(queries.filter(Boolean))).slice(0, 18);
}

function getKnownChinaOfficialSource(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }

  const host = parsed.hostname.toLowerCase();
  return (
    CHINA_PRIORITY_SOURCES.find((source) =>
      source.hosts.some((knownHost) => host === knownHost || host.endsWith(`.${knownHost}`)),
    ) || null
  );
}

function normalizeCompany(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\s+/g, "")
    .trim();
}

function compactWords(parts) {
  return parts
    .filter(Boolean)
    .map((part) => String(part).trim())
    .filter(Boolean)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeDiscoveryInput({ query, city, jobType } = {}) {
  const rawQuery = compactWords([query]);
  const normalizedCity = normalizeChinaCity(city || rawQuery);
  const normalizedJobType =
    normalizeChinaJobType({ title: jobType || rawQuery }) || String(jobType || "").trim();
  const role = removeKnownDiscoveryFields(rawQuery, {
    city: normalizedCity,
    jobType: normalizedJobType,
  });

  return {
    role: role || rawQuery,
    city: normalizedCity && normalizedCity !== rawQuery ? normalizedCity : String(city || "").trim(),
    jobType: normalizedJobType,
  };
}

function removeKnownDiscoveryFields(value, { city, jobType }) {
  let text = ` ${String(value || "").trim()} `;
  const removable = [
    city,
    ...jobTypeAliases(jobType),
    ...cityAliases(city),
  ]
    .filter(Boolean)
    .sort((a, b) => String(b).length - String(a).length);

  for (const term of removable) {
    text = text.replace(new RegExp(`(^|\\s)${escapeRegExp(term)}(?=\\s|$)`, "ig"), " ");
  }

  return text.replace(/\s+/g, " ").trim();
}

function jobTypeAliases(jobType) {
  switch (jobType) {
    case "实习":
      return ["实习", "intern", "internship"];
    case "暑期实习":
      return ["暑期实习", "summer intern", "summer internship", "实习"];
    case "日常实习":
      return ["日常实习", "daily intern", "off-cycle intern", "实习"];
    case "校招":
      return ["校招", "校园招聘", "应届", "毕业生", "campus", "new grad"];
    case "社招":
      return ["社招", "社会招聘", "experienced", "professional"];
    case "管培生":
      return ["管培生", "管理培训生", "graduate program"];
    case "研究岗":
      return ["投研", "研究岗", "行业研究", "equity research", "investment research"];
    default:
      return [jobType].filter(Boolean);
  }
}

function cityAliases(city) {
  switch (city) {
    case "北京":
      return ["北京", "北京市", "beijing"];
    case "上海":
      return ["上海", "上海市", "shanghai"];
    case "深圳":
      return ["深圳", "深圳市", "shenzhen"];
    case "广州":
      return ["广州", "广州市", "guangzhou"];
    case "杭州":
      return ["杭州", "杭州市", "hangzhou"];
    case "香港":
      return ["香港", "hong kong"];
    default:
      return [city].filter(Boolean);
  }
}

function normalizeCompact(value) {
  return String(value || "").toLowerCase().replace(/\s+/g, "");
}

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

module.exports = {
  CHINA_PRIORITY_SOURCES,
  buildChinaDiscoveryQueries,
  buildChinaPrioritySourceCandidates,
  getKnownChinaOfficialSource,
};

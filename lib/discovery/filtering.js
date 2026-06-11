const { getKnownChinaOfficialSource } = require("../china-official-sources");
const { normalizeChinaCity } = require("../china-keyword-expansion");

const THIRD_PARTY_JOB_HOSTS = [
  "linkedin.com",
  "indeed.com",
  "zhipin.com",
  "liepin.com",
  "zhaopin.com",
  "51job.com",
  "jobs.51job.com",
  "lagou.com",
  "kanzhun.com",
  "maimai.cn",
  "nowcoder.com",
  "leetcode.cn",
  "leetcode.com",
  "recruit.net",
  "bebee.com",
  "wondercv.com",
  "superjianli.com",
  "shixiseng.com",
  "yinhangzhaopin.com",
  "yingjiesheng.com",
  "dajie.com",
  "jobui.com",
  "saramin.co.kr",
  "glassdoor.com",
  "monster.com",
];
const CONTENT_ARTICLE_HOSTS = [
  "zhihu.com",
  "zhuanlan.zhihu.com",
  "weixin.qq.com",
  "mp.weixin.qq.com",
  "sohu.com",
  "baijiahao.baidu.com",
  "163.com",
  "jianshu.com",
];
const CAMPUS_REPOST_HOSTS = [
  "ncss.cn",
  "job.ncss.cn",
  "career.tsinghua.edu.cn",
  "scc.pku.edu.cn",
  "career.pku.edu.cn",
  "job.xjtu.edu.cn",
];
const DB_DETECTED_PLATFORMS = new Set([
  "official_careers",
  "greenhouse",
  "lever",
  "workday",
  "ashby",
  "smartrecruiters",
  "unknown",
]);

const GENERIC_CAREERS_LABELS = new Set([
  "www",
  "jobs",
  "careers",
  "career",
  "talent",
  "recruiting",
  "recruitment",
]);

function classifyDiscoveryUrl(url) {
  const normalized = normalizeUrl(url);
  const parsed = parseUrl(normalized);

  if (!parsed) {
    return makeClassification({
      detectedPlatform: "unknown",
      dbDetectedPlatform: "unknown",
      sourceType: "unknown",
      company: null,
      confidence: 0,
      reason: "Invalid URL",
      officialSignal: null,
      matchedKeywords: [],
      rejectReason: "Invalid URL",
      parserSupported: false,
      parserName: null,
      slug: null,
      rejected: true,
    });
  }

  const knownChinaSource = getKnownChinaOfficialSource(normalized);
  const blocked = knownChinaSource ? null : getBlockedUrlClassification(parsed);
  if (blocked) {
    return makeClassification({
      detectedPlatform: blocked.detectedPlatform,
      dbDetectedPlatform: "unknown",
      sourceType: blocked.sourceType,
      company: deriveCompanyFromHostname(parsed.hostname),
      confidence: 0,
      reason: blocked.reason,
      officialSignal: null,
      matchedKeywords: extractMatchedKeywords(parsed),
      rejectReason: blocked.reason,
      parserSupported: false,
      parserName: null,
      slug: null,
      rejected: true,
    });
  }

  const chinaAts = detectChinaAtsPlatform(parsed);
  if (chinaAts) {
    const sourceType = inferOfficialSourceType(parsed);
    const parserSupported = chinaAts.platform === "moka";
    return makeClassification({
      detectedPlatform: chinaAts.platform,
      dbDetectedPlatform: "official_careers",
      sourceType,
      company: chinaAts.company,
      confidence: 0.82,
      reason: parserSupported
        ? "China official ATS URL detected, Moka parser supported when public job data is exposed"
        : "China official ATS URL detected, parser not yet supported",
      officialSignal: `china_ats:${chinaAts.platform}`,
      matchedKeywords: extractMatchedKeywords(parsed),
      rejectReason: null,
      parserSupported,
      parserName: parserSupported ? "moka" : null,
      slug: chinaAts.slug,
    });
  }

  if (knownChinaSource) {
    const parserName = getKnownChinaParserName(knownChinaSource, parsed);
    return makeClassification({
      detectedPlatform: knownChinaSource.detected_platform,
      dbDetectedPlatform: knownChinaSource.detected_platform,
      sourceType: inferOfficialSourceType(parsed),
      company: knownChinaSource.company,
      confidence: 0.85,
      reason: "Known China official careers source, parser pending or source-specific",
      officialSignal: "known_china_official_source",
      matchedKeywords: extractMatchedKeywords(parsed),
      rejectReason: null,
      parserSupported: Boolean(parserName),
      parserName,
      slug: null,
    });
  }

  if (isGreenhouseUrl(parsed)) {
    const slug = extractGreenhouseSlug(parsed);
    const isDetail = hasGreenhouseJobId(parsed);
    return makeClassification({
      detectedPlatform: "greenhouse",
      dbDetectedPlatform: "greenhouse",
      sourceType: "official_ats",
      company: slug,
      confidence: isDetail ? 0.95 : 0.85,
      reason: isDetail
        ? "Supported Greenhouse job detail URL"
        : "Supported Greenhouse job board URL",
      officialSignal: "official_ats:greenhouse",
      matchedKeywords: extractMatchedKeywords(parsed),
      rejectReason: null,
      parserSupported: Boolean(slug),
      parserName: "greenhouse",
      slug,
    });
  }

  if (parsed.hostname === "jobs.lever.co") {
    const slug = parsed.pathname.split("/").filter(Boolean)[0] || null;
    const isDetail = parsed.pathname.split("/").filter(Boolean).length >= 2;
    return makeClassification({
      detectedPlatform: "lever",
      dbDetectedPlatform: "lever",
      sourceType: "official_ats",
      company: slug,
      confidence: isDetail ? 0.95 : 0.85,
      reason: isDetail
        ? "Supported Lever job detail URL"
        : "Supported Lever job board URL",
      officialSignal: "official_ats:lever",
      matchedKeywords: extractMatchedKeywords(parsed),
      rejectReason: null,
      parserSupported: Boolean(slug),
      parserName: "lever",
      slug,
    });
  }

  if (parsed.hostname.includes("myworkdayjobs.com")) {
    return makeClassification({
      detectedPlatform: "workday",
      dbDetectedPlatform: "workday",
      sourceType: "official_ats",
      company: deriveCompanyFromHostname(parsed.hostname),
      confidence: 0.75,
      reason: "Looks like a Workday official ATS URL, parser not yet supported",
      officialSignal: "official_ats:workday",
      matchedKeywords: extractMatchedKeywords(parsed),
      rejectReason: null,
      parserSupported: false,
      parserName: null,
      slug: null,
    });
  }

  if (parsed.hostname === "jobs.ashbyhq.com") {
    const slug = parsed.pathname.split("/").filter(Boolean)[0] || null;
    return makeClassification({
      detectedPlatform: "ashby",
      dbDetectedPlatform: "ashby",
      sourceType: "official_ats",
      company: slug,
      confidence: 0.75,
      reason: "Looks like an Ashby official ATS URL, parser not yet supported",
      officialSignal: "official_ats:ashby",
      matchedKeywords: extractMatchedKeywords(parsed),
      rejectReason: null,
      parserSupported: false,
      parserName: null,
      slug,
    });
  }

  if (parsed.hostname.endsWith("smartrecruiters.com")) {
    return makeClassification({
      detectedPlatform: "smartrecruiters",
      dbDetectedPlatform: "smartrecruiters",
      sourceType: "official_ats",
      company:
        parsed.pathname.split("/").filter(Boolean)[0] ||
        deriveCompanyFromHostname(parsed.hostname),
      confidence: 0.75,
      reason: "Looks like a SmartRecruiters official ATS URL, parser not yet supported",
      officialSignal: "official_ats:smartrecruiters",
      matchedKeywords: extractMatchedKeywords(parsed),
      rejectReason: null,
      parserSupported: false,
      parserName: null,
      slug: null,
    });
  }

  if (looksLikeOfficialCareers(parsed)) {
    const parserName = isChinaHost(parsed) && looksLikeJobDetailPageUrl(normalized)
      ? "generic_official_detail"
      : null;
    return makeClassification({
      detectedPlatform: "official_careers",
      dbDetectedPlatform: "official_careers",
      sourceType: inferOfficialSourceType(parsed),
      company: deriveCompanyFromHostname(parsed.hostname),
      confidence: parserName ? 0.72 : 0.65,
      reason: parserName
        ? "Looks like an official company careers detail page, generic parser supported"
        : "Looks like an official company careers page, parser not yet supported",
      officialSignal: "career_keyword",
      matchedKeywords: extractMatchedKeywords(parsed),
      rejectReason: null,
      parserSupported: Boolean(parserName),
      parserName,
      slug: null,
    });
  }

  return makeClassification({
    detectedPlatform: "unknown",
    dbDetectedPlatform: "unknown",
    sourceType: "unknown",
    company: deriveCompanyFromHostname(parsed.hostname),
    confidence: 0.25,
    reason: "URL type is unknown and needs manual review",
    officialSignal: null,
    matchedKeywords: extractMatchedKeywords(parsed),
    rejectReason: null,
    parserSupported: false,
    parserName: null,
    slug: null,
  });
}

function makeClassification(classification) {
  return {
    detectedPlatform: classification.detectedPlatform,
    dbDetectedPlatform:
      classification.dbDetectedPlatform || toDbDetectedPlatform(classification.detectedPlatform),
    sourceType: classification.sourceType,
    company: classification.company || null,
    confidence: classification.confidence,
    reason: classification.reason,
    officialSignal: classification.officialSignal || null,
    matchedKeywords: classification.matchedKeywords || [],
    rejectReason: classification.rejectReason || null,
    parserSupported: classification.parserSupported,
    parserName: classification.parserName || null,
    slug: classification.slug || null,
    ...(classification.rejected ? { rejected: true } : {}),
  };
}

function toDbDetectedPlatform(platform) {
  return DB_DETECTED_PLATFORMS.has(platform) ? platform : "official_careers";
}

function getBlockedUrlClassification(parsed) {
  if (hostMatches(parsed.hostname, THIRD_PARTY_JOB_HOSTS)) {
    return {
      detectedPlatform: "third_party_job_board",
      sourceType: "third_party_job_board",
      reason: "Blocked third-party job board",
    };
  }

  if (hostMatches(parsed.hostname, CONTENT_ARTICLE_HOSTS)) {
    return {
      detectedPlatform: "content_article",
      sourceType: "content_article",
      reason: "Blocked content repost or SEO aggregation page",
    };
  }

  if (isUniversityCareerRepostUrl(parsed)) {
    return {
      detectedPlatform: "campus_repost",
      sourceType: "campus_repost",
      reason: "Blocked university career-center repost page",
    };
  }

  const text = `${parsed.hostname} ${parsed.pathname}`.toLowerCase();
  if (/\/(article|articles|news|blog|blogs|post|posts|publication|publications|report|reports|digest)\b/.test(parsed.pathname.toLowerCase())) {
    return {
      detectedPlatform: "content_article",
      sourceType: "content_article",
      reason: "Blocked content repost or SEO aggregation page",
    };
  }

  if (/\b(job|jobs|career|careers|zhaopin|招聘)\b/.test(text) && /seo|article|post|news|blog/.test(text)) {
    return {
      detectedPlatform: "content_article",
      sourceType: "content_article",
      reason: "Blocked content repost or SEO aggregation page",
    };
  }

  return null;
}

function isUniversityCareerRepostUrl(parsed) {
  const host = parsed.hostname.toLowerCase();
  const path = decodeURIComponent(parsed.pathname).toLowerCase();

  if (hostMatches(host, CAMPUS_REPOST_HOSTS)) return true;
  if (host.endsWith(".edu.cn") || host === "edu.cn") {
    return /(job|jobs|career|careers|employment|recruit|recruitment|jobfair|jy|jyzx|就业|招聘|宣讲|双选)/.test(
      `${host} ${path}`,
    );
  }

  return false;
}

function detectChinaAtsPlatform(parsed) {
  const host = parsed.hostname;
  const segments = parsed.pathname.split("/").filter(Boolean);

  if (hostMatches(host, ["mokahr.com"])) {
    const slug = segments[1] || segments[0] || deriveCompanyFromHostname(host);
    return {
      platform: "moka",
      slug,
      company: slug,
    };
  }

  if (hostMatches(host, ["italent.cn", "zhiye.com"])) {
    const slug = segments[0] || deriveCompanyFromHostname(host);
    return {
      platform: "beisen",
      slug,
      company: slug,
    };
  }

  if (hostMatches(host, ["feishu.cn", "feishu-boe.cn", "larksuite.com"]) && looksLikeOfficialCareers(parsed)) {
    const slug = segments[0] || deriveCompanyFromHostname(host);
    return {
      platform: "feishu_recruit",
      slug,
      company: slug,
    };
  }

  return null;
}

function getKnownChinaParserName(source, parsed) {
  const host = parsed.hostname;
  if (host === "talent.baidu.com" && /^\/jobs\/(social-list|campus-list|intern-list|detail)/.test(parsed.pathname)) {
    return "baidu";
  }
  if (host === "zhaopin.jd.com" && /^\/web\/job/.test(parsed.pathname)) {
    return "jd";
  }
  if (host === "jobs.apple.com" && /^\/en-us\/(search|details)/.test(parsed.pathname)) {
    return "apple";
  }
  if (source && looksLikeJobDetailPageUrl(parsed.href)) {
    return "generic_official_detail";
  }
  return source?.adapter_name || null;
}

function inferOfficialSourceType(parsed) {
  const matched = extractMatchedKeywords(parsed).join(" ");
  if (/campus|campus_apply|campus-recruitment|校招|校园招聘|graduate|student/.test(matched)) {
    return "official_campus";
  }
  if (/social|social-recruitment|社招|社会招聘/.test(matched)) {
    return "official_social_recruiting";
  }
  return "official_company_career";
}

function extractMatchedKeywords(parsed) {
  const text = decodeURIComponent(
    `${parsed.hostname} ${parsed.pathname} ${parsed.search} ${parsed.hash}`,
  ).toLowerCase();
  const keywords = [
    "campus_apply",
    "campus-recruitment",
    "social-recruitment",
    "campus",
    "校招",
    "校园招聘",
    "social",
    "社招",
    "社会招聘",
    "careers",
    "career",
    "joinus",
    "join-us",
    "join_us",
    "join",
    "recruitment",
    "recruiting",
    "recruit",
    "jobs",
    "job",
    "talent",
    "zhaopin",
    "招聘",
    "internship",
    "intern",
    "实习",
  ];

  const matched = [];
  for (const keyword of keywords) {
    if (!text.includes(keyword)) continue;
    if (matched.some((existing) => existing.includes(keyword))) continue;
    matched.push(keyword);
  }
  return matched;
}

function isGreenhouseUrl(parsed) {
  return (
    parsed.hostname === "job-boards.greenhouse.io" ||
    parsed.hostname === "boards.greenhouse.io" ||
    parsed.hostname.endsWith(".greenhouse.io")
  );
}

function extractGreenhouseSlug(parsed) {
  const pathSegments = parsed.pathname.split("/").filter(Boolean);
  if (
    parsed.hostname === "job-boards.greenhouse.io" ||
    parsed.hostname === "boards.greenhouse.io"
  ) {
    return pathSegments[0] || parsed.searchParams.get("for") || null;
  }

  return parsed.searchParams.get("for") || pathSegments[0] || null;
}

function hasGreenhouseJobId(parsed) {
  const pathSegments = parsed.pathname.split("/").filter(Boolean);
  return pathSegments.includes("jobs") && pathSegments.length >= 3;
}

function looksLikeOfficialCareers(parsed) {
  const text = `${parsed.hostname} ${parsed.pathname}`.toLowerCase();
  return /\b(careers?|jobs?|openings?|positions?|recruiting|recruitment|recruit|joinus|join-us|join_us|join|talent|campus|zhaopin)\b|招聘|校招|社招|实习/.test(
    text.replace(/[._/-]+/g, " "),
  );
}

function looksLikeHiringCandidateUrl(url) {
  const parsed = parseUrl(normalizeUrl(url));
  if (!parsed) return false;

  const text = `${parsed.hostname} ${parsed.pathname}`.toLowerCase();
  return /\b(careers?|jobs?|openings?|positions?|recruiting|recruitment|recruit|joinus|join-us|join_us|join|talent|roles?|internships?)\b/.test(
    text.replace(/[._/-]+/g, " "),
  );
}

function looksLikeJobDetailPageUrl(url) {
  const parsed = parseUrl(url);
  if (!parsed) return false;
  const path = parsed.pathname.toLowerCase();
  if (!path || path === "/") return false;
  if (/\/(search|list|jobs?|careers?|career|campus|social|position|positions|recruit|recruitment|joinus|join-us|index)\/?$/.test(path)) {
    return false;
  }
  if (/(search|keyword|query|page)=/.test(parsed.search.toLowerCase()) && !/(id|jobid|job_id|postid|positionid|position_id|requementid|requirementid)=/.test(parsed.search.toLowerCase())) {
    return false;
  }
  return /\b(detail|job|jobs|position|positions|opening|openings|recruit|joinus|join-us|career|careers)\b|招聘|职位|岗位/.test(
    decodeURIComponent(path).replace(/[._/-]+/g, " "),
  );
}

function isBannedJobPlatformUrl(url) {
  const parsed = parseUrl(normalizeUrl(url));
  if (!parsed) return true;

  return Boolean(getBlockedUrlClassification(parsed));
}

function shouldRecordDiscoveryCandidate(url, classification) {
  if (!classification || classification.rejected) return false;
  if (classification.detectedPlatform === "unknown") {
    return looksLikeHiringCandidateUrl(url);
  }
  return classification.confidence >= 0.5;
}

function hasChinaOfficialSignal(url, classification, { city, query } = {}) {
  if (!classification || classification.rejected) return false;
  const parsed = parseUrl(normalizeUrl(url));
  if (!parsed) return false;

  if (classification.officialSignal === "known_china_official_source") return true;
  if (String(classification.officialSignal || "").startsWith("china_ats:")) return true;

  const host = parsed.hostname.toLowerCase();
  const text = decodeURIComponent(`${host} ${parsed.pathname} ${parsed.search}`)
    .toLowerCase()
    .replace(/[._/-]+/g, " ");

  if (host.endsWith(".cn") || host.endsWith(".com.cn") || host.includes("china")) return true;
  if (/中国|中华|北京|上海|深圳|广州|杭州|南京|苏州|成都|武汉|西安|香港|shanghai|beijing|shenzhen|guangzhou|hangzhou|nanjing|suzhou|chengdu|wuhan|xian|hong kong/.test(text)) {
    return true;
  }

  const normalizedCity = normalizeChinaCity(city || query || "");
  const cityTerms = citySignalTerms(normalizedCity);
  return cityTerms.some((term) => text.includes(term));
}

function deriveCompanyFromHostname(hostname) {
  const labels = String(hostname || "")
    .toLowerCase()
    .split(".")
    .filter(Boolean);

  if (labels.length === 0) return null;
  if (labels.length === 1) return labels[0];

  const first = labels[0];
  if (GENERIC_CAREERS_LABELS.has(first) && labels[1]) {
    return labels[1];
  }

  return first;
}

function isChinaHost(parsed) {
  const host = parsed.hostname.toLowerCase();
  const text = decodeURIComponent(`${host} ${parsed.pathname} ${parsed.search}`);
  return host.endsWith(".cn") || host.endsWith(".com.cn") || host.includes("china") || /[\u4e00-\u9fff]/.test(text);
}

function citySignalTerms(city) {
  switch (city) {
    case "北京":
      return ["北京", "beijing"];
    case "上海":
      return ["上海", "shanghai"];
    case "深圳":
      return ["深圳", "shenzhen"];
    case "广州":
      return ["广州", "guangzhou"];
    case "杭州":
      return ["杭州", "hangzhou"];
    case "南京":
      return ["南京", "nanjing"];
    case "苏州":
      return ["苏州", "suzhou"];
    case "成都":
      return ["成都", "chengdu"];
    case "武汉":
      return ["武汉", "wuhan"];
    case "西安":
      return ["西安", "xian", "xi an"];
    case "香港":
      return ["香港", "hong kong"];
    default:
      return city ? [String(city).toLowerCase()] : [];
  }
}

function hostMatches(hostname, hosts) {
  return hosts.some(
    (host) => hostname === host || hostname.endsWith(`.${host}`),
  );
}

function normalizeUrl(url) {
  return decodeHtmlEntities(String(url || "").trim());
}

function parseUrl(url) {
  try {
    const parsed = new URL(url);
    parsed.hostname = parsed.hostname.toLowerCase();
    return parsed;
  } catch {
    return null;
  }
}

function decodeHtmlEntities(value) {
  return String(value || "")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

// NOTE: unused (no callers); preserved during split, flagged for separate cleanup.
function compactWords(parts) {
  return parts
    .filter(Boolean)
    .map((part) => String(part).trim())
    .filter(Boolean)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

module.exports = {
  classifyDiscoveryUrl,
  isBannedJobPlatformUrl,
  looksLikeJobDetailPageUrl,
  shouldRecordDiscoveryCandidate,
  hasChinaOfficialSignal,
  // shared internals consumed by sibling discovery modules:
  decodeHtmlEntities,
  parseUrl,
  deriveCompanyFromHostname,
  toDbDetectedPlatform,
};

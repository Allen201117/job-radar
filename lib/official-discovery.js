const { isHighQualityJdUrl } = require("./live-search");

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
const {
  buildChinaDiscoveryQueries,
  getKnownChinaOfficialSource,
} = require("./china-official-sources");
const {
  normalizeChinaCity,
  normalizeChinaJobFields,
  normalizeChinaJobType,
  normalizeChinaLocation,
} = require("./china-keyword-expansion");

const GENERIC_CAREERS_LABELS = new Set([
  "www",
  "jobs",
  "careers",
  "career",
  "talent",
  "recruiting",
  "recruitment",
]);

function buildDiscoveryQueries({ query, company, city, jobType } = {}) {
  return buildChinaDiscoveryQueries({ query, company, city, jobType });
}

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

function extractDuckDuckGoResultUrls(html) {
  const urls = [];
  const seen = new Set();
  const text = String(html || "");
  const hrefPattern = /href=(["'])(.*?)\1/gi;
  let match;

  while ((match = hrefPattern.exec(text))) {
    const href = decodeHtmlEntities(match[2]);
    const resolved = resolveDuckDuckGoHref(href);
    if (!resolved || seen.has(resolved)) continue;
    seen.add(resolved);
    urls.push(resolved);
  }

  return urls;
}

function extractBingResultUrls(html) {
  const urls = [];
  const seen = new Set();
  const text = String(html || "");
  const resultBlocks = text.match(
    /<li[^>]*class=(["'])[^"']*\bb_algo\b[^"']*\1[\s\S]*?<\/li>/gi,
  );
  const searchableText = resultBlocks ? resultBlocks.join("\n") : "";
  const hrefPattern = /href=(["'])(.*?)\1/gi;
  let match;

  while ((match = hrefPattern.exec(searchableText))) {
    const href = decodeHtmlEntities(match[2]);
    const resolved = resolveBingHref(href);
    if (!resolved || seen.has(resolved)) continue;
    seen.add(resolved);
    urls.push(resolved);
  }

  return urls;
}

function summarizeDiscoveryOutcome({
  totalExtractedUrls,
  blockedCount,
  candidatesFound,
  candidatesParsed,
  candidatesPending,
  candidatesFailed = 0,
  parserSupportedCandidates = null,
  qualityGateFailures = 0,
  jobsCreated,
  jobsUpdated,
  providers,
  errors,
}) {
  const providerFailures = (providers || []).filter(
    (provider) => provider.status === "provider_failed",
  );
  const hasProviderFailures = providerFailures.length > 0;
  const hasProviderRateLimit = (providers || []).some(isProviderRateLimited);
  const hasProviderDisabled = (providers || []).some(isProviderDisabled);
  const hasWrittenJobs = jobsCreated > 0 || jobsUpdated > 0;
  const errorMessage = (errors || []).filter(Boolean).join("\n").slice(0, 4000);
  const supportedCandidateCount =
    parserSupportedCandidates === null || parserSupportedCandidates === undefined
      ? null
      : Number(parserSupportedCandidates) || 0;

  if (hasWrittenJobs) {
    return {
      status:
        hasProviderFailures || candidatesFailed > 0 || qualityGateFailures > 0
          ? "partial_success"
          : "success",
      failureReason:
        qualityGateFailures > 0 || candidatesFailed > 0
          ? "quality_gate_failed"
          : hasProviderRateLimit
            ? "provider_rate_limited"
            : hasProviderFailures
              ? "provider_failed"
              : null,
      errorMessage: errorMessage || null,
    };
  }

  if (hasProviderRateLimit) {
    return {
      status: "failed",
      failureReason: "provider_rate_limited",
      errorMessage: errorMessage || "Baidu Qianfan rate limited the realtime discovery request.",
    };
  }

  if (hasProviderDisabled) {
    return {
      status: "failed",
      failureReason: "provider_disabled",
      errorMessage:
        errorMessage ||
        "Baidu Qianfan web search is disabled by BAIDU_QIANFAN_SEARCH_DISABLED.",
    };
  }

  if (hasProviderFailures && totalExtractedUrls === 0) {
    return {
      status: "failed",
      failureReason: "provider_failed",
      errorMessage: errorMessage || "All search providers failed before returning URLs.",
    };
  }

  if (totalExtractedUrls === 0) {
    return {
      status: "failed",
      failureReason: "provider_no_results",
      errorMessage: "Search provider returned no extractable results.",
    };
  }

  if (candidatesFound === 0) {
    return {
      status: "failed",
      failureReason: "all_results_rejected",
      errorMessage:
        "Search provider returned URLs, but every result was rejected by source-quality filters.",
    };
  }

  if (qualityGateFailures > 0 || candidatesFailed > 0) {
    return {
      status: "partial_success",
      failureReason: "quality_gate_failed",
      errorMessage:
        errorMessage || "Supported parsers found candidates, but the job detail quality gate rejected them.",
    };
  }

  if (candidatesFound > 0 && candidatesPending === candidatesFound) {
    if (supportedCandidateCount === 0) {
      return {
        status: "partial_success",
        failureReason: "parser_missing",
        errorMessage:
          "Official candidates were recorded, but no supported parser can produce high-quality job detail URLs yet.",
      };
    }

    return {
      status: "partial_success",
      failureReason: "candidates_pending",
      errorMessage:
        "Discovered candidates are pending review or unsupported parsers; no jobs were written.",
    };
  }

  if (candidatesFound > 0 && candidatesParsed === 0) {
    return {
      status: "partial_success",
      failureReason: "quality_gate_failed",
      errorMessage:
        errorMessage || "Supported parsers produced no jobs with high-quality detail URLs.",
    };
  }

  return {
    status: hasProviderFailures ? "partial_success" : "success",
    failureReason: hasProviderFailures ? "provider_failed" : null,
    errorMessage: errorMessage || null,
  };
}

function isProviderRateLimited(provider) {
  return Boolean(
    provider?.diagnostics?.rate_limited ||
      provider?.http_status === 429 ||
      /429|rate\s*limit|too many requests|限流|频率/i.test(String(provider?.error || "")),
  );
}

function isProviderDisabled(provider) {
  return Boolean(
    provider?.diagnostics?.disabled ||
      provider?.diagnostics?.disabled_by_env ||
      /disabled/i.test(String(provider?.error || "")),
  );
}

function buildShanghaiDayWindow(now = new Date()) {
  const date = now instanceof Date ? now : new Date(now);
  const offsetMs = 8 * 60 * 60 * 1000;
  const shanghaiTime = new Date(date.getTime() + offsetMs);
  const startShanghaiUtc = Date.UTC(
    shanghaiTime.getUTCFullYear(),
    shanghaiTime.getUTCMonth(),
    shanghaiTime.getUTCDate(),
  );
  const start = new Date(startShanghaiUtc - offsetMs);
  const end = new Date(start.getTime() + 24 * 60 * 60 * 1000);
  return {
    start: start.toISOString(),
    end: end.toISOString(),
  };
}

function buildDiscoveryDailyBudgetStatus({
  callsToday = 0,
  maxDailySearchCalls = 40,
  now = new Date(),
} = {}) {
  const maxCalls = Math.max(1, Number(maxDailySearchCalls) || 40);
  const usedCalls = Math.max(0, Number(callsToday) || 0);
  const window = buildShanghaiDayWindow(now);
  const remainingCalls = Math.max(0, maxCalls - usedCalls);

  return {
    allowed: usedCalls < maxCalls,
    calls_today: usedCalls,
    max_daily_search_calls: maxCalls,
    remaining_calls: remainingCalls,
    failure_reason: usedCalls >= maxCalls ? "daily_search_budget_exhausted" : null,
    window_start: window.start,
    window_end: window.end,
  };
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

function looksLikeHiringCandidateUrl(url) {
  const parsed = parseUrl(normalizeUrl(url));
  if (!parsed) return false;

  const text = `${parsed.hostname} ${parsed.pathname}`.toLowerCase();
  return /\b(careers?|jobs?|openings?|positions?|recruiting|recruitment|recruit|joinus|join-us|join_us|join|talent|roles?|internships?)\b/.test(
    text.replace(/[._/-]+/g, " "),
  );
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

function hostMatches(hostname, hosts) {
  return hosts.some(
    (host) => hostname === host || hostname.endsWith(`.${host}`),
  );
}

function isChinaHost(parsed) {
  const host = parsed.hostname.toLowerCase();
  const text = decodeURIComponent(`${host} ${parsed.pathname} ${parsed.search}`);
  return host.endsWith(".cn") || host.endsWith(".com.cn") || host.includes("china") || /[\u4e00-\u9fff]/.test(text);
}

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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

function resolveDuckDuckGoHref(href) {
  if (!href) return null;

  try {
    const parsed = new URL(href, "https://duckduckgo.com");
    const wrapped = parsed.searchParams.get("uddg");
    const value = wrapped || parsed.href;
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol)) return null;
    if (!wrapped && url.hostname.endsWith("duckduckgo.com")) return null;
    return stripTrackingHash(url.href);
  } catch {
    return null;
  }
}

function resolveBingHref(href) {
  if (!href) return null;

  try {
    const parsed = new URL(href, "https://www.bing.com");
    if (parsed.hostname.endsWith("bing.com")) {
      const wrapped = parsed.searchParams.get("u");
      if (!wrapped) return null;
      const decoded = decodeBingWrappedUrl(wrapped);
      if (!decoded) return null;
      const url = new URL(decoded);
      if (!["http:", "https:"].includes(url.protocol)) return null;
      return stripTrackingHash(url.href);
    }

    if (!["http:", "https:"].includes(parsed.protocol)) return null;
    return stripTrackingHash(parsed.href);
  } catch {
    return null;
  }
}

function decodeBingWrappedUrl(value) {
  const raw = String(value || "").replace(/^a1/i, "");
  const normalized = raw.replace(/-/g, "+").replace(/_/g, "/");

  try {
    const decoded = Buffer.from(normalized, "base64").toString("utf8");
    if (/^https?:\/\//i.test(decoded)) return decoded;
  } catch {}

  try {
    const decoded = decodeURIComponent(value);
    if (/^https?:\/\//i.test(decoded)) return decoded;
  } catch {}

  return null;
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

function compactWords(parts) {
  return parts
    .filter(Boolean)
    .map((part) => String(part).trim())
    .filter(Boolean)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

function stripTrackingHash(url) {
  const parsed = new URL(url);
  parsed.hash = "";
  return parsed.href;
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

function createProviderDiagnostic({
  providerName,
  query,
  status,
  httpStatus,
  rawResultsCount,
  extractedUrlsCount,
  results = [],
  error,
  diagnostics,
}) {
  return {
    provider_name: providerName,
    name: providerName,
    query,
    status,
    http_status: httpStatus ?? null,
    raw_results_count: rawResultsCount || 0,
    rawResultsCount: rawResultsCount || 0,
    extracted_urls_count: extractedUrlsCount || 0,
    extracted_urls: extractedUrlsCount || 0,
    results: Array.isArray(results) ? results : [],
    error: error || null,
    diagnostics: diagnostics || {},
  };
}

function buildRawResultsAudit({ providers = [], limitPerQuery = 10 } = {}) {
  const audit = [];

  for (const provider of providers || []) {
    const providerName = provider?.provider_name || provider?.name || "";
    const queryDiagnostics = Array.isArray(provider?.diagnostics?.queries)
      ? provider.diagnostics.queries
      : [provider];

    for (const queryDiagnostic of queryDiagnostics) {
      const query = queryDiagnostic?.query || provider?.query || "";
      const rows = Array.isArray(queryDiagnostic?.results)
        ? queryDiagnostic.results
        : [];

      for (const result of rows.slice(0, limitPerQuery)) {
        const classification = classifyDiscoveryUrl(result?.url);
        audit.push({
          provider_name: result?.provider_name || queryDiagnostic?.provider_name || providerName,
          query: result?.provider_query || query,
          title: result?.title || "",
          url: result?.url || "",
          snippet: result?.snippet || "",
          classification: classification.sourceType,
          detected_platform: classification.detectedPlatform,
          reject_reason: classification.rejectReason || null,
          official_signal: classification.officialSignal || null,
          confidence: classification.confidence,
        });
      }
    }
  }

  return audit;
}

function buildSourceCandidateRecord({
  query,
  fallbackCompany,
  fallbackTitle,
  url,
  classification,
  providerResult,
  status,
}) {
  const provider = providerResult || {};
  const reason = {
    provider_name: provider.provider_name || null,
    provider_query: provider.provider_query || null,
    title: provider.title || null,
    snippet: provider.snippet || null,
    query,
    url,
    company_guess: classification.company || fallbackCompany || null,
    source_type: classification.sourceType,
    detected_platform: classification.detectedPlatform,
    db_detected_platform: classification.dbDetectedPlatform,
    confidence: classification.confidence,
    status,
    reason: classification.reason,
    matched_keywords: classification.matchedKeywords || [],
    official_signal: classification.officialSignal || null,
    reject_reason: classification.rejectReason || null,
    parser_supported: Boolean(classification.parserSupported),
    parser_name: classification.parserName || null,
    classification,
  };

  return {
    query,
    company: classification.company || fallbackCompany,
    title: fallbackTitle,
    url,
    source_type: classification.sourceType,
    detected_platform: classification.dbDetectedPlatform || toDbDetectedPlatform(classification.detectedPlatform),
    confidence: classification.confidence,
    status,
    reason: JSON.stringify(reason),
  };
}

function buildSourceCandidateStatusReason({
  previousReason,
  status,
  statusReason,
  updatedAt = new Date().toISOString(),
} = {}) {
  const base = parseReasonJson(previousReason);
  return JSON.stringify({
    ...base,
    status,
    status_update: statusReason,
    status_updated_at: updatedAt,
  });
}

function parseReasonJson(reason) {
  if (!reason) return {};
  if (typeof reason === "object") return reason;
  try {
    const parsed = JSON.parse(String(reason));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed
      : { previous_reason: String(reason) };
  } catch {
    return { previous_reason: String(reason) };
  }
}

async function validateJobQualityGate(job, { sourceName, fetchPage } = {}) {
  if (!String(job?.title || "").trim()) {
    return { ok: false, reason: "missing_title", http_status: null, page_contains_title: false };
  }
  if (!String(job?.company || "").trim()) {
    return { ok: false, reason: "missing_company", http_status: null, page_contains_title: false };
  }
  if (!String(job?.jd_url || "").trim()) {
    return { ok: false, reason: "missing_jd_url", http_status: null, page_contains_title: false };
  }

  const source = String(sourceName || job?.__sourceName || "").trim();
  if (source && !isHighQualityJdUrl(job.jd_url, source)) {
    return {
      ok: false,
      reason: "jd_url_is_not_supported_detail_page",
      http_status: null,
      page_contains_title: false,
    };
  }
  if (!source && !looksLikeJobDetailPageUrl(job.jd_url)) {
    return {
      ok: false,
      reason: "jd_url_is_not_supported_detail_page",
      http_status: null,
      page_contains_title: false,
    };
  }

  const fetcher = fetchPage || globalThis.fetch;
  if (typeof fetcher !== "function") {
    return {
      ok: false,
      reason: "detail_page_fetch_unavailable",
      http_status: null,
      page_contains_title: false,
    };
  }

  let response;
  try {
    response = await fetcher(job.jd_url, {
      method: "GET",
      headers: {
        Accept: "text/html,application/xhtml+xml",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
      },
      signal:
        typeof AbortSignal !== "undefined" && AbortSignal.timeout
          ? AbortSignal.timeout(8000)
          : undefined,
    });
  } catch (error) {
    return {
      ok: false,
      reason: `detail_page_fetch_failed:${error instanceof Error ? error.message : String(error)}`,
      http_status: null,
      page_contains_title: false,
    };
  }

  if (!response?.ok || response.status !== 200) {
    return {
      ok: false,
      reason: `detail_page_http_${response?.status || "unknown"}`,
      http_status: response?.status || null,
      page_contains_title: false,
    };
  }

  const html = await response.text();
  const pageContainsTitle = pageContainsJobTitle(html, job.title);
  if (!pageContainsTitle) {
    return {
      ok: false,
      reason: "detail_page_missing_title",
      http_status: response.status,
      page_contains_title: false,
    };
  }

  return {
    ok: true,
    reason: null,
    http_status: response.status,
    page_contains_title: true,
  };
}

function pageContainsJobTitle(html, title) {
  const normalizedHtml = normalizeTitleText(stripHtmlForTitleMatch(html));
  const normalizedTitle = normalizeTitleText(title);
  if (!normalizedTitle) return false;
  if (normalizedHtml.includes(normalizedTitle)) return true;

  const fragments = String(title || "")
    .split(/[\s,，、/|;；()（）-]+/)
    .map(normalizeTitleText)
    .filter((fragment) => fragment.length >= 2);
  if (fragments.length === 0) return false;

  const required = fragments.length <= 2 ? fragments.length : Math.max(2, Math.ceil(fragments.length * 0.6));
  return fragments.filter((fragment) => normalizedHtml.includes(fragment)).length >= required;
}

function extractGenericOfficialDetailJob({
  url,
  html,
  classification,
  providerResult,
  query,
  city,
  jobType,
} = {}) {
  if (!url || !looksLikeJobDetailPageUrl(url)) return null;

  const title = pickGenericJobTitle(html, providerResult);
  if (!title) return null;

  const summary = compactText(
    extractMetaContent(html, "description") ||
      extractMetaProperty(html, "og:description") ||
      providerResult?.snippet ||
      extractMainTextSnippet(html),
  ).slice(0, 800);
  const company = compactText(
    classification?.company || extractCompanyFromTitle(title) || deriveCompanyFromUrl(url),
  );
  const cleanTitle = cleanGenericJobTitle(title, company);
  if (!company || !cleanTitle) return null;

  const location =
    normalizeChinaLocation(city || extractLocationFromText(`${title} ${summary} ${query || ""}`)) ||
    null;

  return normalizeChinaJobFields({
    company,
    title: cleanTitle,
    location,
    job_type:
      normalizeChinaJobType({
        title: cleanTitle,
        sourceType: jobType || classification?.sourceType,
        url,
        summary,
      }) ||
      jobType ||
      null,
    summary: summary || providerResult?.snippet || null,
    jd_url: url,
    apply_url: url,
    salary_text: null,
    posted_at: null,
    content_hash: makeDiscoveryContentHash([company, cleanTitle, location || "", summary || "", url]),
    status: "active",
  });
}

function extractMokaJobsFromHtml({ url, html, classification } = {}) {
  if (!url || !html) return [];

  const rows = extractMokaJobRowsFromHtml(html);
  return extractMokaJobsFromRows({ url, rows, classification });
}

function extractMokaJobsFromRows({ url, rows, classification } = {}) {
  if (!url || !Array.isArray(rows)) return [];

  const jobs = [];
  const seen = new Set();
  const company = classification?.company || deriveCompanyFromUrl(url);

  for (const row of rows) {
    const id = firstString(row.id, row.jobId, row.jobID, row.uuid, row.jobUuid);
    const title = firstString(row.title, row.jobTitle, row.name, row.positionName);
    if (!id || !title) continue;

    const jdUrl = buildMokaDetailUrl(url, id);
    if (seen.has(jdUrl)) continue;
    seen.add(jdUrl);

    const location = firstString(
      row.location,
      row.city,
      row.workCity,
      row.locationName,
      formatMokaLocations(row.locations),
    );
    const summary = compactText(
      firstString(row.description, row.jobDescription, row.detail, row.requirement, row.duty),
    ).slice(0, 800);
    const department = firstString(
      row.departmentName,
      row.department?.name,
      row.department,
      row.zhineng?.name,
      row.zhinengName,
      row.commitment,
    );

    jobs.push(
      normalizeChinaJobFields({
        company,
        title,
        location: normalizeChinaLocation(location),
        job_type:
          normalizeChinaJobType({
            title,
            sourceType: `${classification?.sourceType || ""} ${department}`,
            url: jdUrl,
            summary,
          }) || department || null,
        summary: summary || null,
        jd_url: jdUrl,
        apply_url: jdUrl,
        salary_text: null,
        posted_at: firstString(row.updatedAt, row.publishTime, row.createdAt) || null,
        content_hash: makeDiscoveryContentHash([company, title, location, summary, jdUrl]),
        status: "active",
      }),
    );
  }

  return jobs;
}

function formatMokaLocations(locations) {
  if (!Array.isArray(locations)) return "";

  return locations
    .map((location) => {
      if (!location) return "";
      if (typeof location === "string") return location;
      return compactText(
        [
          location.country,
          location.province,
          location.city,
          location.area,
          location.address,
        ]
          .filter(Boolean)
          .join(" "),
      );
    })
    .filter(Boolean)
    .join("、");
}

function buildMokaBoardUrl({ originalUrl, slug, mode, siteId }) {
  const pathname = mode === "social" ? "apply" : "campus_apply";
  const parsed = new URL(originalUrl || `https://app.mokahr.com/${pathname}/${slug}`);
  parsed.hostname = "app.mokahr.com";
  parsed.pathname = `/${pathname}/${slug}${siteId ? `/${siteId}` : ""}`;
  parsed.search = "";
  parsed.hash = "";
  return parsed.href;
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

function stripHtmlForTitleMatch(value) {
  return decodeHtmlEntities(String(value || ""))
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ");
}

function normalizeTitleText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/&nbsp;/g, " ")
    .replace(/[\s"'`~!@#$%^&*_=+[{\]}\\|;:,.<>/?，。、；：“”‘’（）()【】《》-]+/g, "")
    .trim();
}

function pickGenericJobTitle(html, providerResult) {
  const h1 = firstHtmlTagText(html, "h1");
  if (h1 && !isGenericCareersHeading(h1)) return h1;

  const ogTitle = extractMetaProperty(html, "og:title");
  if (ogTitle && !isGenericCareersHeading(ogTitle)) return ogTitle;

  const metaTitle = extractMetaContent(html, "title");
  if (metaTitle && !isGenericCareersHeading(metaTitle)) return metaTitle;

  const title = firstHtmlTagText(html, "title");
  if (title && !isGenericCareersHeading(title)) return title;

  const providerTitle = compactText(providerResult?.title || "");
  if (providerTitle && !isGenericCareersHeading(providerTitle)) return providerTitle;

  return h1 || ogTitle || metaTitle || title || providerTitle;
}

function isGenericCareersHeading(value) {
  const normalized = normalizeTitleText(value);
  return /^(校园招聘|校招|社会招聘|社招|招聘|人才招聘|加入我们|职位详情|职位|岗位|careers?|jobs?|joinus|join)$/.test(normalized);
}

function firstHtmlTagText(html, tagName) {
  const pattern = new RegExp(`<${tagName}[^>]*>([\\s\\S]*?)<\\/${tagName}>`, "i");
  const match = String(html || "").match(pattern);
  return match ? compactText(stripHtmlForTitleMatch(match[1])) : "";
}

function extractMetaContent(html, name) {
  const escaped = escapeRegExp(name);
  const patterns = [
    new RegExp(`<meta[^>]+name=["']${escaped}["'][^>]+content=["']([^"']+)["'][^>]*>`, "i"),
    new RegExp(`<meta[^>]+content=["']([^"']+)["'][^>]+name=["']${escaped}["'][^>]*>`, "i"),
  ];
  for (const pattern of patterns) {
    const match = String(html || "").match(pattern);
    if (match) return compactText(decodeHtmlEntities(match[1]));
  }
  return "";
}

function extractMetaProperty(html, property) {
  const escaped = escapeRegExp(property);
  const patterns = [
    new RegExp(`<meta[^>]+property=["']${escaped}["'][^>]+content=["']([^"']+)["'][^>]*>`, "i"),
    new RegExp(`<meta[^>]+content=["']([^"']+)["'][^>]+property=["']${escaped}["'][^>]*>`, "i"),
  ];
  for (const pattern of patterns) {
    const match = String(html || "").match(pattern);
    if (match) return compactText(decodeHtmlEntities(match[1]));
  }
  return "";
}

function extractMainTextSnippet(html) {
  return compactText(stripHtmlForTitleMatch(html)).slice(0, 800);
}

function cleanGenericJobTitle(title, company) {
  const companyText = String(company || "").trim();
  let clean = compactText(title)
    .replace(/\s*[-_|｜]\s*(官方招聘|招聘官网|人才招聘|校园招聘|社会招聘|加入我们).*$/i, "")
    .replace(/\s*[-_|｜]\s*Moka.*$/i, "")
    .trim();

  if (companyText) {
    clean = clean
      .replace(new RegExp(`^${escapeRegExp(companyText)}\\s*[-_|｜:]\\s*`, "i"), "")
      .replace(new RegExp(`\\s*[-_|｜:]\\s*加入${escapeRegExp(companyText)}$`, "i"), "")
      .replace(new RegExp(`\\s*[-_|｜:]\\s*${escapeRegExp(companyText)}$`, "i"), "")
      .trim();
  }

  return clean || compactText(title);
}

function extractCompanyFromTitle(title) {
  const parts = compactText(title).split(/\s*[-_|｜]\s*/).filter(Boolean);
  if (parts.length < 2) return "";
  const last = parts[parts.length - 1];
  if (/招聘|人才|公司|实验室|银行|证券|科技|集团|大学|研究院/.test(last)) {
    return last;
  }
  return "";
}

function deriveCompanyFromUrl(url) {
  const parsed = parseUrl(url);
  return parsed ? deriveCompanyFromHostname(parsed.hostname) : null;
}

function extractLocationFromText(text) {
  const raw = String(text || "");
  const cities = [
    "北京",
    "上海",
    "深圳",
    "广州",
    "杭州",
    "南京",
    "苏州",
    "成都",
    "武汉",
    "西安",
    "香港",
  ];
  return cities.find((city) => raw.includes(city)) || "";
}

function extractMokaJobRowsFromHtml(html) {
  const rows = [];
  const seen = new Set();
  for (const payload of extractJsonPayloadsFromHtml(html)) {
    collectMokaJobRows(payload, rows, seen);
  }
  return rows;
}

function extractJsonPayloadsFromHtml(html) {
  const payloads = [];
  const text = String(html || "");
  const scriptPattern = /<script[^>]*(?:type=["']application\/json["']|id=["']__NEXT_DATA__["'])[^>]*>([\s\S]*?)<\/script>/gi;
  let match;
  while ((match = scriptPattern.exec(text))) {
    const parsed = parseJsonLenient(match[1]);
    if (parsed) payloads.push(parsed);
  }

  const assignmentPattern = /(?:window\.__INITIAL_STATE__|window\.__INITIAL_DATA__|window\.__NUXT__)\s*=\s*(\{[\s\S]*?\});/gi;
  while ((match = assignmentPattern.exec(text))) {
    const parsed = parseJsonLenient(match[1]);
    if (parsed) payloads.push(parsed);
  }

  return payloads;
}

function parseJsonLenient(value) {
  try {
    return JSON.parse(decodeHtmlEntities(String(value || "").trim()));
  } catch {
    return null;
  }
}

function collectMokaJobRows(value, rows, seen, depth = 0) {
  if (!value || depth > 8) return;

  if (Array.isArray(value)) {
    for (const item of value) collectMokaJobRows(item, rows, seen, depth + 1);
    return;
  }

  if (typeof value !== "object") return;

  const id = firstString(value.id, value.jobId, value.jobID, value.uuid, value.jobUuid);
  const title = firstString(value.title, value.jobTitle, value.name, value.positionName);
  if (id && title) {
    const key = `${id}:${title}`;
    if (!seen.has(key)) {
      seen.add(key);
      rows.push(value);
    }
  }

  for (const child of Object.values(value)) {
    collectMokaJobRows(child, rows, seen, depth + 1);
  }
}

function buildMokaDetailUrl(url, jobId) {
  const parsed = new URL(url);
  if (parsed.pathname.startsWith("/social-recruitment/")) {
    parsed.pathname = parsed.pathname.replace("/social-recruitment/", "/apply/");
  }
  parsed.searchParams.set("pure", "1");
  parsed.hash = `#/job/${encodeURIComponent(jobId)}/apply`;
  return parsed.href;
}

function compactText(value) {
  return decodeHtmlEntities(String(value || ""))
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function firstString(...values) {
  for (const value of values) {
    const text = compactText(value);
    if (text) return text;
  }
  return "";
}

function makeDiscoveryContentHash(parts) {
  let hash = 0;
  const text = parts.join("|");
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash << 5) - hash + text.charCodeAt(index);
    hash |= 0;
  }
  return `disc-${Math.abs(hash)}`;
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

function buildDiscoveryCacheKey({ userId, query, city, company, jobType } = {}) {
  return [
    normalizeCachePart(userId),
    normalizeCachePart(query),
    normalizeCachePart(city),
    normalizeCachePart(company),
    normalizeCachePart(jobType),
  ].join("|");
}

function selectDiscoveryQueryBatch({
  discoveryQueries = [],
  queryOffset = 0,
  queryLimit = 1,
  maxGeneratedQueries = 2,
} = {}) {
  const maxQueries = Math.max(1, Math.min(Number(maxGeneratedQueries) || 2, 2));
  const normalizedOffset = Math.max(
    0,
    Math.min(Number(queryOffset) || 0, Math.max(0, maxQueries - 1)),
  );
  const normalizedLimit = Math.max(1, Math.min(Number(queryLimit) || 1, 1));
  const eligibleQueries = (discoveryQueries || []).slice(0, maxQueries);
  const calledQueries = eligibleQueries.slice(
    normalizedOffset,
    normalizedOffset + normalizedLimit,
  );
  const nextQueryOffset =
    normalizedOffset + normalizedLimit < eligibleQueries.length
      ? normalizedOffset + normalizedLimit
      : null;

  return {
    calledQueries,
    queryOffset: normalizedOffset,
    queryLimit: normalizedLimit,
    maxGeneratedQueries: maxQueries,
    canContinue: nextQueryOffset !== null,
    nextQueryOffset,
  };
}

function summarizeCachedDiscovery({ run, candidates = [], jobs = [] } = {}) {
  const candidatesParsed = candidates.filter((candidate) => candidate.status === "parsed").length;
  const candidatesPending = candidates.filter((candidate) => candidate.status === "pending").length;
  const candidatesFailed = candidates.filter((candidate) => candidate.status === "failed").length;
  const jobsReused = jobs.length;

  return {
    cache_hit: true,
    cache_source: run ? "discovery_runs" : "memory",
    status: jobsReused > 0 ? "success" : run?.status || "partial_success",
    candidates_found: candidates.length,
    candidates_parsed: candidatesParsed,
    candidates_pending: candidatesPending,
    candidates_failed: candidatesFailed,
    jobs_reused: jobsReused,
    jobs_created: 0,
    jobs_updated: 0,
    failure_reason:
      jobsReused > 0
        ? null
        : candidates.length > 0
          ? candidatesFailed > 0 && candidatesPending === 0
            ? "quality_gate_failed"
            : "candidates_pending"
          : "provider_no_results",
    error_message: jobsReused > 0 ? null : run?.error_message || null,
  };
}

function normalizeCachePart(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

module.exports = {
  buildDiscoveryCacheKey,
  buildDiscoveryDailyBudgetStatus,
  buildDiscoveryQueries,
  buildShanghaiDayWindow,
  buildSourceCandidateRecord,
  buildSourceCandidateStatusReason,
  buildRawResultsAudit,
  classifyDiscoveryUrl,
  createProviderDiagnostic,
  extractBingResultUrls,
  extractDuckDuckGoResultUrls,
  extractGenericOfficialDetailJob,
  extractMokaJobsFromHtml,
  extractMokaJobsFromRows,
  buildMokaBoardUrl,
  hasChinaOfficialSignal,
  isBannedJobPlatformUrl,
  looksLikeJobDetailPageUrl,
  pageContainsJobTitle,
  selectDiscoveryQueryBatch,
  shouldRecordDiscoveryCandidate,
  summarizeCachedDiscovery,
  summarizeDiscoveryOutcome,
  validateJobQualityGate,
};

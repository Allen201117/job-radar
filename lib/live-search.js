const APPLE_DETAIL_PREFIX = "https://jobs.apple.com/en-us/details";
const BAIDU_DETAIL_PREFIX = "https://talent.baidu.com/jobs/detail";
const JD_DETAIL_PREFIX = "https://zhaopin.jd.com/web/job-info-detail";
const {
  expandChinaKeywordTerms,
  jobMatchesChinaKeyword,
  normalizeChinaCity,
  normalizeChinaJobFields,
  normalizeChinaLocation,
  normalizeChinaJobType,
} = require("./china-keyword-expansion");

const LIVE_ATS_SOURCES = [
  { provider: "greenhouse", company: "Anthropic", slug: "anthropic" },
  { provider: "greenhouse", company: "Airbnb", slug: "airbnb" },
  { provider: "greenhouse", company: "Databricks", slug: "databricks" },
  { provider: "greenhouse", company: "Figma", slug: "figma" },
  { provider: "greenhouse", company: "Reddit", slug: "reddit" },
  { provider: "greenhouse", company: "Discord", slug: "discord" },
  { provider: "greenhouse", company: "Stripe", slug: "stripe" },
  { provider: "greenhouse", company: "Airtable", slug: "airtable" },
  { provider: "greenhouse", company: "Cloudflare", slug: "cloudflare" },
  { provider: "greenhouse", company: "Roblox", slug: "roblox" },
  { provider: "greenhouse", company: "Pinterest", slug: "pinterest" },
  { provider: "greenhouse", company: "Twitch", slug: "twitch" },
  { provider: "greenhouse", company: "Mozilla", slug: "mozilla" },
  { provider: "greenhouse", company: "Asana", slug: "asana" },
  { provider: "greenhouse", company: "Dropbox", slug: "dropbox" },
  { provider: "greenhouse", company: "Lyft", slug: "lyft" },
  { provider: "greenhouse", company: "Instacart", slug: "instacart" },
  { provider: "greenhouse", company: "Brex", slug: "brex" },
  { provider: "greenhouse", company: "Okta", slug: "okta" },
  { provider: "greenhouse", company: "MongoDB", slug: "mongodb" },
  { provider: "greenhouse", company: "Twilio", slug: "twilio" },
  { provider: "lever", company: "Conversica", slug: "conversica" },
];

function buildAppleDetailUrl(row) {
  const id = String(row?.id || "").trim();
  if (!id) return "";

  const slug =
    row.transformedPostingTitle ||
    slugify(row.postingTitle || row.title || "job");
  const teamCode = row.team?.teamCode
    ? `?team=${encodeURIComponent(row.team.teamCode)}`
    : "";

  return `${APPLE_DETAIL_PREFIX}/${encodeURIComponent(id)}/${slug}${teamCode}`;
}

function formatAppleSearchResult(row) {
  const jdUrl = buildAppleDetailUrl(row);
  const locations = Array.isArray(row.locations)
    ? row.locations.map((location) => location?.name).filter(Boolean)
    : [];

  return normalizeChinaJobFields({
    company: "Apple",
    title: row.postingTitle || row.title || "",
    location: normalizeChinaLocation(locations.join(", ")) || null,
    job_type: row.type === "REQ" ? "社招" : null,
    summary: row.jobSummary || null,
    jd_url: jdUrl,
    apply_url: jdUrl,
    salary_text: null,
    posted_at: row.postingDate || row.postDateInGMT || null,
    content_hash: makeContentHash([
      row.postingTitle || row.title || "",
      locations.join(", "),
      row.jobSummary || "",
    ]),
    status: "active",
  });
}

function formatBaiduSearchResult(row, fallbackRecruitType = "SOCIAL") {
  const postId = String(row?.postId || "").trim();
  const recruitType = String(row?.recruitType || fallbackRecruitType || "SOCIAL").trim();
  const jdUrl = postId
    ? `${BAIDU_DETAIL_PREFIX}/${encodeURIComponent(recruitType)}/${encodeURIComponent(postId)}`
    : "";

  return normalizeChinaJobFields({
    company: "百度",
    title: row?.name || "",
    location: normalizeChinaLocation(row?.workPlace) || null,
    job_type:
      normalizeChinaJobType({
        title: row?.name || "",
        sourceType: row?.postType || row?.projectType || recruitType,
        url: jdUrl,
        summary: row?.workContent || row?.serviceCondition,
      }) ||
      row?.postType ||
      row?.projectType ||
      null,
    summary: row?.workContent || row?.serviceCondition || null,
    jd_url: jdUrl,
    apply_url: jdUrl,
    salary_text: null,
    posted_at: row?.updateDate || row?.publishDate || null,
    content_hash: makeContentHash([
      row?.name || "",
      row?.workPlace || "",
      row?.workContent || row?.serviceCondition || "",
    ]),
    status: "active",
  });
}

function formatJdJob(row) {
  const requirementId = String(row?.requirementId || row?.requementId || "").trim();
  const jdUrl = requirementId
    ? `${JD_DETAIL_PREFIX}?requementId=${encodeURIComponent(requirementId)}`
    : "";
  const summary = [row?.workContent, row?.qualification].filter(Boolean).join("\n");

  return normalizeChinaJobFields({
    company: "京东",
    title: row?.positionNameOpen || row?.positionName || row?.title || row?.jobName || "",
    location: normalizeChinaLocation(row?.workCity || row?.location || row?.city) || null,
    job_type: row?.jobType || row?.recruitType || null,
    summary: summary || null,
    jd_url: jdUrl,
    apply_url: jdUrl,
    salary_text: null,
    posted_at: formatJdPostedAt(row),
    content_hash: makeContentHash([
      row?.positionNameOpen || row?.positionName || row?.title || "",
      row?.workCity || "",
      summary || "",
    ]),
    status: "active",
  });
}

function formatGreenhouseJob(row, source) {
  const jdUrl = row?.absolute_url || "";
  const departments = Array.isArray(row?.departments)
    ? row.departments.map((department) => department?.name).filter(Boolean)
    : [];
  const offices = Array.isArray(row?.offices)
    ? row.offices.map((office) => office?.name).filter(Boolean)
    : [];
  const location = row?.location?.name || offices.join(", ") || null;
  const summary = stripHtml(row?.content || row?.description || "");

  return normalizeChinaJobFields({
    company: source.company,
    title: row?.title || "",
    location: normalizeChinaLocation(location) || location,
    job_type: departments.join(" · ") || null,
    summary,
    jd_url: jdUrl,
    apply_url: jdUrl,
    salary_text: null,
    posted_at: row?.updated_at || null,
    content_hash: makeContentHash([
      row?.title || "",
      location || "",
      summary || "",
    ]),
    status: "active",
  });
}

function formatLeverPosting(row, source) {
  const location = row?.categories?.location || null;
  const team = row?.categories?.team || "";
  const commitment = row?.categories?.commitment || "";
  const jobType = [team, commitment].filter(Boolean).join(" · ") || null;
  const summary = row?.descriptionPlain || stripHtml(row?.description || "");
  const postedAt = Number.isFinite(row?.createdAt)
    ? new Date(row.createdAt).toISOString()
    : null;

  return normalizeChinaJobFields({
    company: source.company,
    title: row?.text || "",
    location: normalizeChinaLocation(location) || location,
    job_type: jobType,
    summary,
    jd_url: row?.hostedUrl || "",
    apply_url: row?.applyUrl || row?.hostedUrl || "",
    salary_text: null,
    posted_at: postedAt,
    content_hash: makeContentHash([
      row?.text || "",
      location || "",
      summary || "",
    ]),
    status: "active",
  });
}

function extractAppleSearchResultsFromHtml(html) {
  const match = String(html || "").match(
    /window\.__staticRouterHydrationData\s*=\s*JSON\.parse\("([\s\S]*?)"\);<\/script>/,
  );
  if (!match) return [];

  try {
    const hydrationText = JSON.parse(`"${match[1]}"`);
    const hydration = JSON.parse(hydrationText);
    const rows = hydration?.loaderData?.search?.searchResults;
    return Array.isArray(rows) ? rows : [];
  } catch {
    return [];
  }
}

function extractBaiduInitialDataFromHtml(html) {
  const match = String(html || "").match(
    /window\.__INITIAL_DATA__\s*=(.*?);\s*window\.prefix/s,
  );
  if (!match) return [];

  const raw = match[1].replace(/(?<=[:\[,])\s*undefined\s*(?=[,}\]])/g, "null");
  try {
    const initialData = JSON.parse(raw);
    const listData = initialData?.listData || {};
    const recruitType = listData.recruitType || "SOCIAL";
    const rows = Array.isArray(listData.listDetailData) ? listData.listDetailData : [];
    return rows.map((row) => ({ ...row, recruitType: row.recruitType || recruitType }));
  } catch {
    return [];
  }
}

function isHighQualityJdUrl(url, sourceName) {
  if (!url) return false;

  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }

  if (!["http:", "https:"].includes(parsed.protocol)) return false;
  if (parsed.pathname === "/" || parsed.pathname === "") return false;

  if (sourceName === "apple") {
    return (
      parsed.hostname === "jobs.apple.com" &&
      /^\/en-us\/details\/[^/]+\/[^/]+/.test(parsed.pathname)
    );
  }

  if (sourceName === "baidu") {
    return (
      parsed.hostname === "talent.baidu.com" &&
      /^\/jobs\/detail\/(SOCIAL|GRADUATE|INTERN)\/[^/]+/.test(parsed.pathname)
    );
  }

  if (sourceName === "jd") {
    return (
      parsed.hostname === "zhaopin.jd.com" &&
      parsed.pathname === "/web/job-info-detail" &&
      /^\d+$/.test(parsed.searchParams.get("requementId") || "")
    );
  }

  if (sourceName === "greenhouse") {
    return (
      parsed.hostname.endsWith("greenhouse.io") &&
      /\/jobs\/[^/]+/.test(parsed.pathname)
    );
  }

  if (sourceName === "lever") {
    return (
      parsed.hostname === "jobs.lever.co" &&
      /^\/[^/]+\/[^/]+/.test(parsed.pathname)
    );
  }

  if (sourceName === "moka") {
    return (
      parsed.hostname === "app.mokahr.com" &&
      /^\/(apply|campus_apply|social-recruitment)\/[^/]+(?:\/[^/]+)?/.test(parsed.pathname) &&
      /^#\/job\/[^/]+(?:\/apply|\/select)?/.test(parsed.hash)
    );
  }

  if (sourceName === "generic_official_detail") {
    return looksLikeGenericJobDetailUrl(parsed);
  }

  return false;
}

function filterJobsByQueryAndCity(jobs, query, city) {
  const terms = expandSearchTerms(query);
  const cityText = normalizeForSearch(city);
  const normalizedCityText = normalizeForSearch(normalizeChinaCity(city));
  const cityTerms = Array.from(new Set([cityText, normalizedCityText].filter(Boolean)));

  return (jobs || []).filter((job) => {
    const location = normalizeForSearch(job.location);

    // 组合意图精准：以 jobMatchesChinaKeyword（单元间 AND、单元内 OR）为准，
    // 不再用 terms.some 宽 OR 兜底（那会把「AI PM」放宽成 AI ∪ 产品，召回过宽、不准）。
    const queryMatches = terms.length === 0 || jobMatchesChinaKeyword(job, query);
    const cityMatches =
      cityTerms.length === 0 || cityTerms.some((term) => location.includes(term));

    return queryMatches && cityMatches;
  });
}

function mergeJobsByUrl(cached, live) {
  const merged = [];
  const seen = new Set();

  for (const job of [...cached, ...live]) {
    const key = job.jd_url || job.jdUrl;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    merged.push(job);
  }

  return merged;
}

function toApiJob(job, score = 50) {
  return {
    id: job.id || "",
    sourceId: job.source_id || "",
    sourceName: job.company,
    company: job.company,
    title: job.title,
    location: job.location || "官网未披露",
    language: "zh",
    type: job.job_type || "全职",
    salary: job.salary_text || "官网未披露",
    deadline: "以岗位详情页为准",
    postedAt: job.posted_at || job.first_seen_at || "",
    firstSeenAt: job.first_seen_at || "",
    summary: job.summary || "",
    jdDigest: job.summary
      ? [`核心职责：${job.summary.slice(0, 80)}`, "完整 JD 以岗位详情页为准"]
      : [],
    jdUrl: job.jd_url || "",
    applyUrl: job.apply_url || job.jd_url || "",
    skills: [],
    roles: [],
    jobFunction: "未分类",
    industry: "未分类",
    seniority: "unknown",
    detailStatus: "来自企业官方公开招聘源",
    detailCheckedAt: new Date().toISOString().slice(0, 10),
    match: { score, reasons: ["命中搜索条件"] },
  };
}

function formatJdPostedAt(row) {
  if (row?.formatPublishTime) return row.formatPublishTime;
  const value = row?.publishTime || row?.createTime;
  if (Number.isFinite(value) && value > 0) {
    return new Date(value).toISOString().slice(0, 10);
  }
  return value || null;
}

function slugify(value) {
  return String(value)
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function expandSearchTerms(query) {
  const normalized = normalizeForSearch(query);
  if (!normalized) return [];

  const terms = new Set(expandChinaKeywordTerms(query).map(normalizeForSearch));
  terms.add(normalized);
  const expansions = [
    [/算法|机器学习|人工智能|大模型|推荐/, ["algorithm", "machine learning", "ml", "ai", "model"]],
    [/数据|数仓|数据工程/, ["data", "analytics", "data engineer"]],
    [/前端/, ["frontend", "front-end", "web"]],
    [/后端|服务端/, ["backend", "back-end", "server"]],
    [/产品/, ["product"]],
    [/设计/, ["design", "designer"]],
    [/运营/, ["operations"]],
    [/安全/, ["security"]],
    [/实习/, ["intern", "internship"]],
  ];

  for (const [pattern, values] of expansions) {
    if (pattern.test(normalized)) {
      values.forEach((value) => terms.add(value));
    }
  }

  return Array.from(terms);
}

function normalizeForSearch(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function stripHtml(value) {
  return decodeHtmlEntities(String(value || ""))
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function looksLikeGenericJobDetailUrl(parsed) {
  const path = parsed.pathname.toLowerCase();
  const search = parsed.search.toLowerCase();
  if (!path || path === "/") return false;
  if (/\/(search|list|jobs?|careers?|career|campus|social|position|positions|recruit|recruitment|joinus|join-us|index)\/?$/.test(path)) {
    return false;
  }
  if (/(search|keyword|query|page)=/.test(search) && !/(id|jobid|job_id|postid|positionid|position_id|requementid|requirementid)=/.test(search)) {
    return false;
  }
  return /\b(detail|job|jobs|position|positions|opening|openings|recruit|joinus|join-us|career|careers)\b|招聘|职位|岗位/.test(
    decodeURIComponent(path).replace(/[._/-]+/g, " "),
  );
}

function decodeHtmlEntities(value) {
  let decoded = value;
  for (let index = 0; index < 2; index += 1) {
    decoded = decoded
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&apos;/g, "'")
      .replace(/&nbsp;/g, " ")
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">");
  }
  return decoded;
}

function makeContentHash(parts) {
  let hash = 0;
  const text = parts.join("|");
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash << 5) - hash + text.charCodeAt(index);
    hash |= 0;
  }
  return `js-${Math.abs(hash)}`;
}

// ── 大中华区地点过滤（对齐 crawler normalizer.keep_for_china_radar）────────────────
// 外企 ATS(greenhouse/lever) 看板含全球岗位；内联抓取时只放行大中华区 + 未绑定海外的 remote，
// 否则用户不填城市就会把看板灌满海外岗位（违背「在华雷达」定位）。标记表逐字对齐 normalizer。
const CHINA_LOCATION_MARKERS = [
  "china", "中国", "prc", "greater china",
  "beijing", "shanghai", "shenzhen", "guangzhou", "hangzhou", "chengdu",
  "nanjing", "suzhou", "wuhan", "xi'an", "xian", "foshan", "dongguan",
  "tianjin", "chongqing", "wuxi", "ningbo", "qingdao", "dalian", "xiamen",
  "hefei", "changsha", "zhengzhou", "jinan", "kunming", "shijiazhuang",
  "changchun", "harbin", "shenyang", "nanchang", "fuzhou", "nanning",
  "guiyang", "lanzhou", "taiyuan", "wenzhou", "zhuhai", "yantai", "xuzhou",
  "changzhou", "nantong", "weifang", "luoyang", "huizhou",
  "jiangsu", "zhejiang", "guangdong", "sichuan", "shandong", "henan",
  "hebei", "hunan", "hubei", "anhui", "fujian", "jiangxi", "liaoning",
  "shaanxi", "shanxi", "yunnan", "guizhou", "gansu", "hainan", "jilin",
  "heilongjiang", "qinghai", "ningxia", "xinjiang", "guangxi",
  "nei mongol", "inner mongolia",
  "北京", "上海", "深圳", "广州", "杭州", "成都", "南京", "苏州", "武汉", "西安", "佛山",
  "天津", "重庆", "无锡", "宁波", "青岛", "大连", "厦门", "合肥", "长沙", "郑州",
  "hong kong", "香港", "macau", "macao", "澳门",
];
const _CJK_RE = /[一-鿿]/;
const _CJK_MARKERS = CHINA_LOCATION_MARKERS.filter((m) => _CJK_RE.test(m));
const _LATIN_MARKERS = CHINA_LOCATION_MARKERS.filter((m) => !_CJK_RE.test(m));
// latin marker 用词边界，避免子串误命中（如 'macao' 命中 'Humacao'）；CJK marker 用子串。
const _LATIN_MARKER_RE = new RegExp(
  "\\b(?:" +
    _LATIN_MARKERS.map((m) => m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") +
    ")\\b",
);
const REMOTE_MARKERS = ["remote", "anywhere", "distributed", "work from home", "wfh", "远程", "远端"];
const OVERSEAS_LOCATION_TOKENS = new Set([
  "usa", "us", "canada", "uk", "britain", "ireland", "germany", "france", "netherlands",
  "spain", "italy", "poland", "portugal", "sweden", "switzerland", "austria", "belgium",
  "europe", "emea", "americas", "latam", "brazil", "mexico", "argentina", "colombia",
  "india", "japan", "korea", "singapore", "malaysia", "thailand", "vietnam", "indonesia",
  "philippines", "australia", "nz", "uae", "dubai", "israel", "egypt", "turkey", "africa",
]);
const OVERSEAS_LOCATION_PHRASES = [
  "united states", "united kingdom", "new zealand", "south korea", "saudi arabia",
  "sri lanka", "costa rica", "south africa",
];

function isChinaLocation(location) {
  if (!location) return false;
  const text = String(location).toLowerCase();
  if (_CJK_MARKERS.some((m) => text.includes(m))) return true;
  if (_LATIN_MARKER_RE.test(text)) return true;
  // 归一逗号/连字符/多空白为单空格，让 "Hong, Kong"、"Hong-Kong" 也被词边界命中。
  const norm = text.replace(/[\s,\-/]+/g, " ");
  return _LATIN_MARKER_RE.test(norm);
}

function isRemoteLocation(location) {
  if (!location) return false;
  const text = String(location).toLowerCase();
  return REMOTE_MARKERS.some((m) => text.includes(m));
}

function isOverseasPinned(location) {
  if (!location) return false;
  const text = String(location).toLowerCase();
  if (OVERSEAS_LOCATION_PHRASES.some((p) => text.includes(p))) return true;
  const tokens = text.split(/[^a-z]+/).filter(Boolean);
  return tokens.some((t) => OVERSEAS_LOCATION_TOKENS.has(t));
}

// 在华雷达保留口径：大中华区岗位 + 不绑定海外地点的 remote；排除 base 海外（含海外 remote）。
function keepForChinaRadar(location) {
  if (isChinaLocation(location)) return true;
  if (isRemoteLocation(location) && !isOverseasPinned(location)) return true;
  return false;
}

// 把真实 sources 行解析成可内联抓取的 { provider, url }；非内联 adapter / host 不符 / 坏 url → null。
// 仅 greenhouse / lever：公开 JSON API、host 固定可严校验（精确匹配防 'api.lever.co.evil.com' 这类 SSRF/脏数据）。
function resolveInlineAtsSource(source) {
  if (!source || !source.adapter_name || !source.source_url) return null;
  const adapter = source.adapter_name;
  if (adapter !== "greenhouse" && adapter !== "lever") return null;
  let parsed;
  try {
    parsed = new URL(String(source.source_url));
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:") return null;
  if (adapter === "greenhouse") {
    if (parsed.hostname !== "boards-api.greenhouse.io") return null;
    parsed.searchParams.set("content", "true");
    return { provider: "greenhouse", url: parsed.toString() };
  }
  if (parsed.hostname !== "api.lever.co") return null;
  parsed.searchParams.set("mode", "json");
  return { provider: "lever", url: parsed.toString() };
}

// 当前 lib 已实现 TS 内联抓取器的 adapter（Vercel serverless 秒回，免 GitHub Actions）。
// 其余 adapter（北森/Moka/飞书/SPA）需浏览器 → 走异步 dispatch，不在此集合。
const INLINE_LIVE_ADAPTERS = new Set(["baidu", "jd", "apple", "apple_cn", "greenhouse", "lever"]);

// P2-A 源选择器：按用户筛选项（公司/关键词→行业/城市）从 sources 表挑最相关的 N 个去定向刷新。
// 返回 [{ source, score, live }]：live=true 表示有内联抓取器可秒回；false 表示浏览器源(应走异步 dispatch)。
// daily 给广度基线，on-demand 用本函数收窄到"用户筛选项下"的相关源，避免无差别全刷。
function selectRelevantSources(sources, filters = {}, opts = {}) {
  const cap = Math.max(1, opts.cap || 12);
  const kw = normalizeForSearch(filters.keyword || "");
  const company = normalizeForSearch(filters.company || "");
  const scored = [];
  for (const s of sources || []) {
    if (!s || !s.adapter_name || s.enabled === false) continue;
    const sCompany = normalizeForSearch(s.company || "");
    if (company && !sCompany.includes(company)) continue; // 指定公司时只留命中的源
    const sText = normalizeForSearch(`${s.company || ""} ${s.industry || ""} ${s.segment || ""}`);
    const live = INLINE_LIVE_ADAPTERS.has(s.adapter_name);
    let score = 0;
    if (company && sCompany.includes(company)) score += 100; // 公司精确命中
    if (kw && sText.includes(kw)) score += 20; // 关键词命中公司/行业
    if (live) score += 5; // 能秒回的源优先
    scored.push({ source: s, score, live });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, cap);
}

module.exports = {
  INLINE_LIVE_ADAPTERS,
  LIVE_ATS_SOURCES,
  selectRelevantSources,
  keepForChinaRadar,
  resolveInlineAtsSource,
  buildAppleDetailUrl,
  extractBaiduInitialDataFromHtml,
  extractAppleSearchResultsFromHtml,
  filterJobsByQueryAndCity,
  formatBaiduSearchResult,
  formatJdJob,
  formatGreenhouseJob,
  formatLeverPosting,
  formatAppleSearchResult,
  expandSearchTerms,
  isHighQualityJdUrl,
  mergeJobsByUrl,
  toApiJob,
};

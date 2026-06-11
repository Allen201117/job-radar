const { isHighQualityJdUrl } = require("../live-search");
const {
  normalizeChinaJobFields,
  normalizeChinaJobType,
  normalizeChinaLocation,
} = require("../china-keyword-expansion");
const {
  decodeHtmlEntities,
  deriveCompanyFromHostname,
  looksLikeJobDetailPageUrl,
  parseUrl,
} = require("./filtering");

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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

function buildMokaDetailUrl(url, jobId) {
  const parsed = new URL(url);
  if (parsed.pathname.startsWith("/social-recruitment/")) {
    parsed.pathname = parsed.pathname.replace("/social-recruitment/", "/apply/");
  }
  parsed.searchParams.set("pure", "1");
  parsed.hash = `#/job/${encodeURIComponent(jobId)}/apply`;
  return parsed.href;
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

module.exports = {
  extractGenericOfficialDetailJob,
  extractMokaJobsFromHtml,
  extractMokaJobsFromRows,
  buildMokaBoardUrl,
  pageContainsJobTitle,
  validateJobQualityGate,
};

const { buildChinaDiscoveryQueries } = require("../china-official-sources");
const { classifyDiscoveryUrl, decodeHtmlEntities } = require("./filtering");

function buildDiscoveryQueries({ query, company, city, jobType } = {}) {
  return buildChinaDiscoveryQueries({ query, company, city, jobType });
}

function stripTrackingHash(url) {
  const parsed = new URL(url);
  parsed.hash = "";
  return parsed.href;
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

function buildDiscoveryCacheKey({ userId, query, city, company, jobType } = {}) {
  return [
    normalizeCachePart(userId),
    normalizeCachePart(query),
    normalizeCachePart(city),
    normalizeCachePart(company),
    normalizeCachePart(jobType),
  ].join("|");
}

function normalizeCachePart(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
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

module.exports = {
  buildDiscoveryQueries,
  extractDuckDuckGoResultUrls,
  extractBingResultUrls,
  createProviderDiagnostic,
  buildRawResultsAudit,
  buildShanghaiDayWindow,
  buildDiscoveryDailyBudgetStatus,
  buildDiscoveryCacheKey,
  selectDiscoveryQueryBatch,
};

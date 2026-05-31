const { createProviderDiagnostic } = require("./official-discovery");

const BAIDU_QIANFAN_PROVIDER_NAME = "baidu_qianfan_web_search";
const BAIDU_QIANFAN_WEB_SEARCH_URL =
  "https://qianfan.baidubce.com/v2/ai_search/web_search";
const DEFAULT_TOP_K = 10;
const DEFAULT_TIMEOUT = 10000;

function buildBaiduQianfanWebSearchRequest(query, { topK = DEFAULT_TOP_K } = {}) {
  return {
    messages: [
      {
        role: "user",
        content: String(query || "").trim().slice(0, 72),
      },
    ],
    search_source: "baidu_search_v2",
    resource_type_filter: [{ type: "web", top_k: topK }],
    search_recency_filter: "year",
  };
}

async function searchBaiduQianfanWeb({
  query,
  apiKey = process.env.BAIDU_QIANFAN_API_KEY,
  fetchImpl = globalThis.fetch,
  timeoutMs = DEFAULT_TIMEOUT,
  topK = DEFAULT_TOP_K,
  disabled = isBaiduQianfanSearchDisabled(),
} = {}) {
  const providerName = BAIDU_QIANFAN_PROVIDER_NAME;
  const cleanQuery = String(query || "").trim();

  if (disabled) {
    const error = "Baidu Qianfan web search disabled by BAIDU_QIANFAN_SEARCH_DISABLED";
    return {
      urls: [],
      errors: [error],
      diagnostic: createProviderDiagnostic({
        providerName,
        query: cleanQuery,
        status: "provider_failed",
        httpStatus: null,
        rawResultsCount: 0,
        extractedUrlsCount: 0,
        results: [],
        error,
        diagnostics: {
          configured: Boolean(apiKey),
          rate_limited: false,
          disabled: true,
          disabled_by_env: true,
          reason: "disabled_by_env",
        },
      }),
    };
  }

  if (!apiKey) {
    const error = "Missing Baidu Qianfan API key";
    return {
      urls: [],
      errors: [error],
      diagnostic: createProviderDiagnostic({
        providerName,
        query: cleanQuery,
        status: "provider_failed",
        httpStatus: null,
        rawResultsCount: 0,
        extractedUrlsCount: 0,
        results: [],
        error,
        diagnostics: {
          configured: false,
          reason: "missing_api_key",
        },
      }),
    };
  }

  if (typeof fetchImpl !== "function") {
    const error = "Fetch implementation unavailable";
    return {
      urls: [],
      errors: [error],
      diagnostic: createProviderDiagnostic({
        providerName,
        query: cleanQuery,
        status: "provider_failed",
        httpStatus: null,
        rawResultsCount: 0,
        extractedUrlsCount: 0,
        results: [],
        error,
        diagnostics: {
          configured: true,
          reason: "fetch_unavailable",
        },
      }),
    };
  }

  try {
    const response = await fetchImpl(BAIDU_QIANFAN_WEB_SEARCH_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "X-Appbuilder-Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(buildBaiduQianfanWebSearchRequest(cleanQuery, { topK })),
      signal:
        typeof AbortSignal !== "undefined" && AbortSignal.timeout
          ? AbortSignal.timeout(timeoutMs)
          : undefined,
    });

    const httpStatus = response.status;
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }

    const normalized = normalizeBaiduQianfanWebSearchResponse(data);
    const apiError = data?.code || data?.message;
    const error = response.ok
      ? apiError
        ? String(data?.message || data?.code)
        : null
      : `Baidu Qianfan returned HTTP ${httpStatus}`;
    const rateLimited =
      httpStatus === 429 ||
      /rate\s*limit|too many requests|限流|频率/i.test(String(apiError || error || ""));
    const status =
      normalized.results.length > 0
        ? error
          ? "partial_success"
          : "success"
        : error
          ? "provider_failed"
          : "no_results_found";

    return {
      urls: normalized.results.map((result) => result.url),
      errors: error ? [error] : [],
      diagnostic: createProviderDiagnostic({
        providerName,
        query: cleanQuery,
        status,
        httpStatus,
        rawResultsCount: normalized.rawResultsCount,
        extractedUrlsCount: normalized.results.length,
        results: normalized.results,
        error,
        diagnostics: {
          configured: true,
          response_shape: normalized.responseShape,
          request_id: data?.request_id || null,
          rate_limited: rateLimited,
        },
      }),
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const errorMessage = `Baidu Qianfan web search failed: ${message}`;
    return {
      urls: [],
      errors: [errorMessage],
      diagnostic: createProviderDiagnostic({
        providerName,
        query: cleanQuery,
        status: "provider_failed",
        httpStatus: null,
        rawResultsCount: 0,
        extractedUrlsCount: 0,
        results: [],
        error: errorMessage,
        diagnostics: {
          configured: true,
          reason: "request_failed",
        },
      }),
    };
  }
}

function isBaiduQianfanSearchDisabled() {
  return /^(1|true|yes)$/i.test(String(process.env.BAIDU_QIANFAN_SEARCH_DISABLED || ""));
}

function normalizeBaiduQianfanWebSearchResponse(data) {
  const container = findResultContainer(data);
  const rows = Array.isArray(container.rows) ? container.rows : [];
  const results = rows
    .map(normalizeBaiduQianfanResult)
    .filter((result) => result.title && result.url);

  return {
    results,
    rawResultsCount: rows.length,
    responseShape: {
      top_level_keys: Object.keys(data || {}).sort(),
      result_container: container.name,
      first_result_keys: rows[0] ? Object.keys(rows[0]).sort() : [],
    },
  };
}

function findResultContainer(data) {
  if (Array.isArray(data?.references)) {
    return { name: "references", rows: data.references };
  }
  if (Array.isArray(data?.results)) {
    return { name: "results", rows: data.results };
  }
  if (Array.isArray(data?.data?.references)) {
    return { name: "data.references", rows: data.data.references };
  }
  if (Array.isArray(data?.data?.results)) {
    return { name: "data.results", rows: data.data.results };
  }
  if (Array.isArray(data?.webPages?.value)) {
    return { name: "webPages.value", rows: data.webPages.value };
  }
  return { name: "not_found", rows: [] };
}

function normalizeBaiduQianfanResult(row) {
  const title = firstString(row?.title, row?.web_anchor, row?.name);
  const url = firstString(row?.url, row?.link, row?.website);
  const snippet = firstString(row?.snippet, row?.content, row?.summary, row?.description);

  return {
    title,
    url,
    snippet,
  };
}

function firstString(...values) {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text) return text;
  }
  return "";
}

module.exports = {
  BAIDU_QIANFAN_PROVIDER_NAME,
  BAIDU_QIANFAN_WEB_SEARCH_URL,
  buildBaiduQianfanWebSearchRequest,
  normalizeBaiduQianfanWebSearchResponse,
  searchBaiduQianfanWeb,
  isBaiduQianfanSearchDisabled,
};

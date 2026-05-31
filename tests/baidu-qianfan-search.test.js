const assert = require("node:assert/strict");
const test = require("node:test");

const {
  BAIDU_QIANFAN_PROVIDER_NAME,
  buildBaiduQianfanWebSearchRequest,
  normalizeBaiduQianfanWebSearchResponse,
  searchBaiduQianfanWeb,
} = require("../lib/baidu-qianfan-search");

test("builds Baidu Qianfan web search request body for one query", () => {
  assert.deepEqual(buildBaiduQianfanWebSearchRequest("数据分析 实习 上海 招聘 官网"), {
    messages: [
      {
        role: "user",
        content: "数据分析 实习 上海 招聘 官网",
      },
    ],
    search_source: "baidu_search_v2",
    resource_type_filter: [{ type: "web", top_k: 10 }],
    search_recency_filter: "year",
  });
});

test("normalizes Baidu Qianfan references to title url snippet results", () => {
  const normalized = normalizeBaiduQianfanWebSearchResponse({
    request_id: "req-1",
    references: [
      {
        title: "上海实验室 - 加入我们",
        url: "https://www.shlab.org.cn/joinus/detail/1",
        snippet: "数据分析实习生招聘信息",
        content: "fallback content should not be used when snippet exists",
        type: "web",
      },
      {
        web_anchor: "百度校园招聘",
        url: "https://talent.baidu.com/jobs/campus-list",
        content: "产品经理校招",
        type: "web",
      },
      {
        title: "missing url",
        content: "ignored",
      },
    ],
  });

  assert.deepEqual(normalized, {
    results: [
      {
        title: "上海实验室 - 加入我们",
        url: "https://www.shlab.org.cn/joinus/detail/1",
        snippet: "数据分析实习生招聘信息",
      },
      {
        title: "百度校园招聘",
        url: "https://talent.baidu.com/jobs/campus-list",
        snippet: "产品经理校招",
      },
    ],
    rawResultsCount: 3,
    responseShape: {
      top_level_keys: ["references", "request_id"],
      result_container: "references",
      first_result_keys: ["content", "snippet", "title", "type", "url"],
    },
  });
});

test("returns missing_api_key diagnostics without calling fetch", async () => {
  const result = await searchBaiduQianfanWeb({
    query: "数据分析 实习 上海 招聘 官网",
    apiKey: "",
    fetchImpl: async () => {
      throw new Error("fetch should not be called");
    },
  });

  assert.equal(result.urls.length, 0);
  assert.deepEqual(result.errors, ["Missing Baidu Qianfan API key"]);
  assert.equal(result.diagnostic.provider_name, BAIDU_QIANFAN_PROVIDER_NAME);
  assert.equal(result.diagnostic.status, "provider_failed");
  assert.equal(result.diagnostic.error, "Missing Baidu Qianfan API key");
  assert.deepEqual(result.diagnostic.diagnostics, {
    configured: false,
    reason: "missing_api_key",
  });
});

test("returns disabled diagnostics without calling fetch when provider is disabled", async () => {
  const result = await searchBaiduQianfanWeb({
    query: "数据分析 实习 上海 招聘 官网",
    apiKey: "secret-value",
    disabled: true,
    fetchImpl: async () => {
      throw new Error("fetch should not be called");
    },
  });

  assert.equal(result.urls.length, 0);
  assert.deepEqual(result.errors, [
    "Baidu Qianfan web search disabled by BAIDU_QIANFAN_SEARCH_DISABLED",
  ]);
  assert.equal(result.diagnostic.provider_name, BAIDU_QIANFAN_PROVIDER_NAME);
  assert.equal(result.diagnostic.status, "provider_failed");
  assert.equal(result.diagnostic.http_status, null);
  assert.equal(result.diagnostic.diagnostics.rate_limited, false);
  assert.equal(result.diagnostic.diagnostics.disabled, true);
  assert.equal(result.diagnostic.diagnostics.disabled_by_env, true);
  assert.equal(result.diagnostic.diagnostics.reason, "disabled_by_env");
});

test("calls Baidu Qianfan API with bearer auth and records standard diagnostics", async () => {
  const calls = [];
  const result = await searchBaiduQianfanWeb({
    query: "数据分析 实习 上海 招聘 官网",
    apiKey: "secret-value",
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return {
        ok: true,
        status: 200,
        json: async () => ({
          request_id: "req-1",
          references: [
            {
              title: "上海实验室 - 加入我们",
              url: "https://www.shlab.org.cn/joinus/detail/1",
              snippet: "数据分析实习生招聘信息",
              type: "web",
            },
          ],
        }),
      };
    },
  });

  assert.equal(calls.length, 1);
  assert.equal(
    calls[0].url,
    "https://qianfan.baidubce.com/v2/ai_search/web_search",
  );
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers.Authorization, "Bearer secret-value");
  assert.equal(result.diagnostic.provider_name, BAIDU_QIANFAN_PROVIDER_NAME);
  assert.equal(result.diagnostic.http_status, 200);
  assert.equal(result.diagnostic.raw_results_count, 1);
  assert.equal(result.diagnostic.extracted_urls_count, 1);
  assert.deepEqual(result.diagnostic.results, [
    {
      title: "上海实验室 - 加入我们",
      url: "https://www.shlab.org.cn/joinus/detail/1",
      snippet: "数据分析实习生招聘信息",
    },
  ]);
});

test("marks Baidu Qianfan HTTP 429 as rate limited diagnostics", async () => {
  const result = await searchBaiduQianfanWeb({
    query: "数据分析 实习 上海 招聘 官网",
    apiKey: "secret-value",
    fetchImpl: async () => ({
      ok: false,
      status: 429,
      json: async () => ({
        request_id: "req-rate-limit",
        message: "Too Many Requests",
      }),
    }),
  });

  assert.equal(result.urls.length, 0);
  assert.deepEqual(result.errors, ["Baidu Qianfan returned HTTP 429"]);
  assert.equal(result.diagnostic.status, "provider_failed");
  assert.equal(result.diagnostic.http_status, 429);
  assert.equal(result.diagnostic.diagnostics.rate_limited, true);
  assert.equal(result.diagnostic.diagnostics.request_id, "req-rate-limit");
});

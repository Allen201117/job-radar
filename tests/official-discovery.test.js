const assert = require("node:assert/strict");
const test = require("node:test");

const {
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
  isBannedJobPlatformUrl,
  pageContainsJobTitle,
  validateJobQualityGate,
  hasChinaOfficialSignal,
  extractGenericOfficialDetailJob,
  extractMokaJobsFromHtml,
  extractMokaJobsFromRows,
  looksLikeJobDetailPageUrl,
  shouldRecordDiscoveryCandidate,
  selectDiscoveryQueryBatch,
  summarizeCachedDiscovery,
  summarizeDiscoveryOutcome,
} = require("../lib/official-discovery");

test("classifies supported ATS job and board URLs", () => {
  assert.deepEqual(
    classifyDiscoveryUrl("https://job-boards.greenhouse.io/anthropic/jobs/5076109008"),
    {
      detectedPlatform: "greenhouse",
      dbDetectedPlatform: "greenhouse",
      sourceType: "official_ats",
      company: "anthropic",
      confidence: 0.95,
      reason: "Supported Greenhouse job detail URL",
      officialSignal: "official_ats:greenhouse",
      matchedKeywords: ["jobs"],
      rejectReason: null,
      parserSupported: true,
      parserName: "greenhouse",
      slug: "anthropic",
    },
  );

  assert.deepEqual(
    classifyDiscoveryUrl("https://jobs.lever.co/acme/abc-123"),
    {
      detectedPlatform: "lever",
      dbDetectedPlatform: "lever",
      sourceType: "official_ats",
      company: "acme",
      confidence: 0.95,
      reason: "Supported Lever job detail URL",
      officialSignal: "official_ats:lever",
      matchedKeywords: ["jobs"],
      rejectReason: null,
      parserSupported: true,
      parserName: "lever",
      slug: "acme",
    },
  );
});

test("generates Chinese official recruitment queries from one user keyword", () => {
  assert.deepEqual(
    buildDiscoveryQueries({
      query: "数据分析 实习 上海",
    }).slice(0, 7),
    [
      "数据分析 实习 上海 招聘 官网",
      "数据分析 实习 上海 校招 官网",
      "数据分析 实习 上海 职位详情",
      "数据分析 实习 上海 社招 官网",
      "数据分析 实习 上海 官方招聘",
      "数据分析 实习 上海 人才招聘",
      "数据分析 实习 上海 校园招聘",
    ],
  );

  const queries = buildDiscoveryQueries({
    query: "product manager",
    city: "北京市",
    jobType: "campus",
  });
  assert.ok(queries.includes("product manager 校招 北京 招聘 官网"));
  assert.ok(queries.includes("product manager 校招 北京 加入我们"));
  assert.equal(queries[2], "product manager 校招 北京 职位详情");
  assert.ok(queries.some((query) => query.includes("产品经理")));
  assert.equal(queries.some((query) => query.includes("Greenhouse Lever")), false);
});

test("rejects LeetCode company job pages as third-party job boards", () => {
  const classification = classifyDiscoveryUrl("https://leetcode.cn/company/chinaclear/jobs/EXPERIENCED/");

  assert.equal(classification.rejected, true);
  assert.equal(classification.sourceType, "third_party_job_board");
  assert.equal(classification.detectedPlatform, "third_party_job_board");
});

test("records unknown official careers as pending candidates", () => {
  assert.deepEqual(
    classifyDiscoveryUrl("https://example.com/careers/machine-learning-engineer"),
    {
      detectedPlatform: "official_careers",
      dbDetectedPlatform: "official_careers",
      sourceType: "official_company_career",
      company: "example",
      confidence: 0.65,
      reason: "Looks like an official company careers page, parser not yet supported",
      officialSignal: "career_keyword",
      matchedKeywords: ["careers"],
      rejectReason: null,
      parserSupported: false,
      parserName: null,
      slug: null,
    },
  );
});

test("records official careers homepages and official ATS boards as pending candidates", () => {
  const officialHomepage = classifyDiscoveryUrl("https://careers.tencent.com/");
  assert.equal(officialHomepage.detectedPlatform, "official_careers");
  assert.equal(officialHomepage.parserSupported, false);
  assert.equal(
    shouldRecordDiscoveryCandidate("https://careers.tencent.com/", officialHomepage),
    true,
  );
  assert.equal(
    hasChinaOfficialSignal("https://careers.tencent.com/", officialHomepage, {
      query: "产品经理 校招 北京",
      city: "北京",
    }),
    true,
  );

  const ashbyBoard = classifyDiscoveryUrl("https://jobs.ashbyhq.com/acme");
  assert.equal(ashbyBoard.detectedPlatform, "ashby");
  assert.equal(ashbyBoard.parserSupported, false);
  assert.equal(
    shouldRecordDiscoveryCandidate("https://jobs.ashbyhq.com/acme", ashbyBoard),
    true,
  );
});

test("treats official join-us detail pages as company career candidates", () => {
  const classification = classifyDiscoveryUrl(
    "https://www.shlab.org.cn/joinus/detail/7612950926287391027?mode=campus",
  );

  assert.equal(classification.sourceType, "official_campus");
  assert.equal(classification.detectedPlatform, "official_careers");
  assert.equal(classification.company, "shlab");
  assert.equal(classification.officialSignal, "known_china_official_source");
  assert.equal(classification.parserName, "generic_official_detail");
  assert.ok(classification.matchedKeywords.includes("joinus"));
  assert.equal(shouldRecordDiscoveryCandidate("https://www.shlab.org.cn/joinus/detail/1", classification), true);
});

test("classifies known China official careers domains before ATS fallback", () => {
  assert.deepEqual(
    classifyDiscoveryUrl("https://jobs.bytedance.com/campus/position"),
    {
      detectedPlatform: "official_careers",
      dbDetectedPlatform: "official_careers",
      sourceType: "official_campus",
      company: "字节跳动",
      confidence: 0.85,
      reason: "Known China official careers source, parser pending or source-specific",
      officialSignal: "known_china_official_source",
      matchedKeywords: ["campus", "jobs"],
      rejectReason: null,
      parserSupported: false,
      parserName: null,
      slug: null,
    },
  );

  const detail = classifyDiscoveryUrl(
    "https://jobs.bytedance.com/campus/position/7631837782784968965/detail",
  );
  assert.equal(detail.company, "字节跳动");
  assert.equal(detail.sourceType, "official_campus");
  assert.equal(detail.parserSupported, true);
  assert.equal(detail.parserName, "generic_official_detail");
});

test("does not reject known China official subdomains because of parent content hosts", () => {
  const classification = classifyDiscoveryUrl("https://hr.163.com/");

  assert.equal(classification.detectedPlatform, "official_careers");
  assert.equal(classification.company, "网易");
  assert.equal(classification.rejectReason, null);
  assert.equal(classification.officialSignal, "known_china_official_source");
});

test("rejects third-party job platforms", () => {
  assert.equal(isBannedJobPlatformUrl("https://www.linkedin.com/jobs/view/123"), true);
  assert.equal(isBannedJobPlatformUrl("https://www.indeed.com/viewjob?jk=123"), true);
  assert.equal(isBannedJobPlatformUrl("https://www.zhipin.com/job_detail/123.html"), true);
  assert.equal(isBannedJobPlatformUrl("https://maimai.cn/jobs/123"), true);
  assert.equal(isBannedJobPlatformUrl("https://www.nowcoder.com/jobs/detail/399995"), true);
  assert.equal(isBannedJobPlatformUrl("https://www.recruit.net/job/xiaomi-jobs/123"), true);
  assert.equal(isBannedJobPlatformUrl("https://job-boards.greenhouse.io/acme/jobs/123"), false);
});

test("classifies China recruitment platforms and content reposts", () => {
  assert.deepEqual(
    classifyDiscoveryUrl("https://app.mokahr.com/campus_apply/tencent/123#/jobs"),
    {
      detectedPlatform: "moka",
      dbDetectedPlatform: "official_careers",
      sourceType: "official_campus",
      company: "tencent",
      confidence: 0.82,
      reason: "China official ATS URL detected, Moka parser supported when public job data is exposed",
      officialSignal: "china_ats:moka",
      matchedKeywords: ["campus_apply", "jobs"],
      rejectReason: null,
      parserSupported: true,
      parserName: "moka",
      slug: "tencent",
    },
  );

  const zhihu = classifyDiscoveryUrl("https://zhuanlan.zhihu.com/p/123456");
  assert.equal(zhihu.sourceType, "content_article");
  assert.equal(zhihu.rejected, true);
  assert.equal(zhihu.rejectReason, "Blocked content repost or SEO aggregation page");
});

test("rejects university employment repost pages as discovery candidates", () => {
  const repost = classifyDiscoveryUrl(
    "https://career.tsinghua.edu.cn/jobfair/jobs/123?company=Acme",
  );

  assert.equal(repost.detectedPlatform, "campus_repost");
  assert.equal(repost.sourceType, "campus_repost");
  assert.equal(repost.rejected, true);
  assert.equal(repost.rejectReason, "Blocked university career-center repost page");
  assert.equal(shouldRecordDiscoveryCandidate("https://career.tsinghua.edu.cn/jobfair/jobs/123", repost), false);
});

test("supports generic official detail pages but rejects generic list pages", () => {
  const detailUrl = "https://www.shlab.org.cn/joinus/detail/7612950926287391027?mode=campus";
  const detail = classifyDiscoveryUrl(
    detailUrl,
  );
  const list = classifyDiscoveryUrl("https://www.shlab.org.cn/joinus");

  assert.equal(looksLikeJobDetailPageUrl(detailUrl), true);
  assert.equal(looksLikeJobDetailPageUrl("https://www.shlab.org.cn/joinus"), false);
  assert.equal(detail.parserSupported, true);
  assert.equal(detail.parserName, "generic_official_detail");
  assert.equal(detail.sourceType, "official_campus");
  assert.equal(list.parserSupported, false);
  assert.equal(list.parserName, null);
});

test("extracts a generic official detail job from a public detail page", () => {
  const classification = classifyDiscoveryUrl(
    "https://www.shlab.org.cn/joinus/detail/7612950926287391027?mode=campus",
  );
  const job = extractGenericOfficialDetailJob({
    url: "https://www.shlab.org.cn/joinus/detail/7612950926287391027?mode=campus",
    html: `
      <html>
        <head>
          <title>数据分析实习生 - 上海实验室</title>
          <meta name="description" content="参与科研平台数据分析，工作地点上海。" />
        </head>
        <body>
          <h1>数据分析实习生</h1>
          <main>上海 数据分析 Python 实习</main>
        </body>
      </html>
    `,
    classification,
    providerResult: {
      title: "上海实验室 数据分析实习生",
      snippet: "上海数据分析实习岗位",
    },
    query: "数据分析 实习 上海",
    city: "上海",
    jobType: "实习",
  });

  assert.equal(job.company, "shlab");
  assert.equal(job.title, "数据分析实习生");
  assert.equal(job.location, "上海");
  assert.equal(job.job_type, "实习");
  assert.equal(
    job.jd_url,
    "https://www.shlab.org.cn/joinus/detail/7612950926287391027?mode=campus",
  );
  assert.match(job.summary, /科研平台数据分析/);
});

test("extracts a generic official detail job when a page has a generic careers heading", () => {
  const classification = classifyDiscoveryUrl(
    "https://jobs.bytedance.com/campus/position/7631837782784968965/detail",
  );
  const job = extractGenericOfficialDetailJob({
    url: "https://jobs.bytedance.com/campus/position/7631837782784968965/detail",
    html: `
      <html>
        <head>
          <title>数据分析实习生-AI创新业务 - 加入字节跳动</title>
          <meta name="description" content="上海 实习 产品 - 数据分析。负责埋点设计，协助资深分析师快速回收实验。" />
        </head>
        <body>
          <h1>校园招聘</h1>
          <main>职位描述 上海 数据分析 SQL Python 实习</main>
        </body>
      </html>
    `,
    classification,
    providerResult: {
      title: "数据分析实习生-AI创新业务",
      snippet: "上海 实习 产品 - 数据分析",
    },
    query: "数据分析 实习 上海",
    city: "上海",
    jobType: "实习",
  });

  assert.equal(job.company, "字节跳动");
  assert.equal(job.title, "数据分析实习生-AI创新业务");
  assert.equal(job.location, "上海");
  assert.equal(job.job_type, "实习");
});

test("extracts Moka jobs from public embedded job data", () => {
  const classification = classifyDiscoveryUrl(
    "https://app.mokahr.com/campus_apply/acme/123#/jobs",
  );
  const jobs = extractMokaJobsFromHtml({
    url: "https://app.mokahr.com/campus_apply/acme/123#/jobs",
    html: `
      <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "jobs": [
                {
                  "id": "job-1",
                  "title": "产品经理校招生",
                  "location": "北京",
                  "departmentName": "产品部",
                  "description": "负责产品需求分析。"
                }
              ]
            }
          }
        }
      </script>
    `,
    classification,
  });

  assert.equal(jobs.length, 1);
  assert.equal(jobs[0].company, "acme");
  assert.equal(jobs[0].title, "产品经理校招生");
  assert.equal(jobs[0].location, "北京");
  assert.equal(
    jobs[0].jd_url,
    "https://app.mokahr.com/campus_apply/acme/123?pure=1#/job/job-1/apply",
  );
});

test("formats Moka public API job rows with location objects", () => {
  const classification = classifyDiscoveryUrl(
    "https://app.mokahr.com/campus_apply/immomo/54299",
  );
  const jobs = extractMokaJobsFromRows({
    url: "https://app.mokahr.com/campus_apply/immomo/54299",
    rows: [
      {
        id: "job-2",
        title: "【2027校招暑期实习】海外产品经理（校招）",
        description: "<p>负责海外产品需求分析。</p>",
        commitment: "实习",
        publishedAt: "2026-05-15T03:37:06.000Z",
        department: { name: "产品部" },
        locations: [
          {
            country: "中国",
            province: "北京市",
            address: "朝阳区酒仙桥街道",
          },
        ],
      },
    ],
    classification,
  });

  assert.equal(jobs.length, 1);
  assert.equal(jobs[0].company, "immomo");
  assert.equal(jobs[0].title, "【2027校招暑期实习】海外产品经理（校招）");
  assert.equal(jobs[0].location, "北京");
  assert.equal(jobs[0].job_type, "暑期实习");
  assert.equal(
    jobs[0].jd_url,
    "https://app.mokahr.com/campus_apply/immomo/54299?pure=1#/job/job-2/apply",
  );
});

test("builds source candidate records with compatibility reason JSON", () => {
  const classification = classifyDiscoveryUrl(
    "https://app.mokahr.com/social-recruitment/acme/456#/jobs",
  );
  const record = buildSourceCandidateRecord({
    query: "产品经理 校招 北京",
    fallbackCompany: null,
    fallbackTitle: "产品经理 校招 北京",
    url: "https://app.mokahr.com/social-recruitment/acme/456#/jobs",
    classification,
    providerResult: {
      provider_name: "baidu_qianfan_web_search",
      provider_query: "产品经理 校招 北京 招聘 官网",
      title: "Acme 官方招聘",
      snippet: "产品经理校招岗位",
    },
    status: "pending",
  });
  const reason = JSON.parse(record.reason);

  assert.equal(record.detected_platform, "official_careers");
  assert.equal(record.source_type, "official_social_recruiting");
  assert.equal(record.company, "acme");
  assert.equal(reason.detected_platform, "moka");
  assert.equal(reason.provider_name, "baidu_qianfan_web_search");
  assert.equal(reason.provider_query, "产品经理 校招 北京 招聘 官网");
  assert.equal(reason.title, "Acme 官方招聘");
  assert.equal(reason.snippet, "产品经理校招岗位");
  assert.deepEqual(reason.classification.sourceType, "official_social_recruiting");
  assert.equal(reason.source_type, "official_social_recruiting");
  assert.deepEqual(reason.matched_keywords, ["social-recruitment", "jobs"]);
  assert.equal(reason.official_signal, "china_ats:moka");
  assert.equal(reason.reject_reason, null);
});

test("source candidate status updates preserve provider reason metadata", () => {
  const previousReason = JSON.stringify({
    provider_name: "baidu_qianfan_web_search",
    provider_query: "数据分析 实习 上海 招聘 官网",
    title: "上海实验室 - 加入我们",
    snippet: "数据分析实习生招聘",
    source_type: "official_campus",
    reject_reason: null,
  });

  assert.deepEqual(
    JSON.parse(
      buildSourceCandidateStatusReason({
        previousReason,
        status: "parsed",
        statusReason: "Parsed 1 jobs with accurate official detail URLs",
        updatedAt: "2026-05-27T08:00:00.000Z",
      }),
    ),
    {
      provider_name: "baidu_qianfan_web_search",
      provider_query: "数据分析 实习 上海 招聘 官网",
      title: "上海实验室 - 加入我们",
      snippet: "数据分析实习生招聘",
      source_type: "official_campus",
      reject_reason: null,
      status: "parsed",
      status_update: "Parsed 1 jobs with accurate official detail URLs",
      status_updated_at: "2026-05-27T08:00:00.000Z",
    },
  );
});

test("creates provider diagnostics that do not hide unconfigured search APIs", () => {
  assert.deepEqual(
    createProviderDiagnostic({
      providerName: "bing_web_search_api",
      query: "数据分析 实习 上海 招聘 官网",
      status: "provider_failed",
      httpStatus: null,
      rawResultsCount: 0,
      extractedUrlsCount: 0,
      error: "Missing BING_SEARCH_API_KEY; falling back to HTML search providers.",
      diagnostics: { configured: false },
    }),
    {
      provider_name: "bing_web_search_api",
      name: "bing_web_search_api",
      query: "数据分析 实习 上海 招聘 官网",
      status: "provider_failed",
      http_status: null,
      raw_results_count: 0,
      rawResultsCount: 0,
      extracted_urls_count: 0,
      extracted_urls: 0,
      results: [],
      error: "Missing BING_SEARCH_API_KEY; falling back to HTML search providers.",
      diagnostics: { configured: false },
    },
  );
});

test("enforces job quality gate before writing jobs", async () => {
  assert.equal(
    pageContainsJobTitle("<h1>数据分析实习生</h1>", "数据分析 实习生"),
    true,
  );
  assert.equal(
    pageContainsJobTitle("<h1>校园招聘岗位列表</h1>", "数据分析实习生"),
    false,
  );

  const accepted = await validateJobQualityGate(
    {
      company: "百度",
      title: "数据分析实习生",
      jd_url: "https://talent.baidu.com/jobs/detail/INTERN/abc",
    },
    {
      sourceName: "baidu",
      fetchPage: async () => ({
        ok: true,
        status: 200,
        text: async () => "<html><h1>数据分析实习生</h1></html>",
      }),
    },
  );
  assert.equal(accepted.ok, true);
  assert.equal(accepted.http_status, 200);
  assert.equal(accepted.page_contains_title, true);

  const rejected = await validateJobQualityGate(
    {
      company: "百度",
      title: "数据分析实习生",
      jd_url: "https://talent.baidu.com/jobs/social-list?search=数据分析",
    },
    {
      sourceName: "baidu",
      fetchPage: async () => ({
        ok: true,
        status: 200,
        text: async () => "<html><h1>数据分析实习生</h1></html>",
      }),
    },
  );
  assert.deepEqual(rejected, {
    ok: false,
    reason: "jd_url_is_not_supported_detail_page",
    http_status: null,
    page_contains_title: false,
  });
});

test("extracts DuckDuckGo result URLs including redirect wrappers", () => {
  const html = `
    <a class="result__a" href="/l/?uddg=https%3A%2F%2Fjobs.lever.co%2Facme%2Fabc">Job</a>
    <a class="result__a" href="https://example.com/careers/software-engineer">Careers</a>
  `;

  assert.deepEqual(extractDuckDuckGoResultUrls(html), [
    "https://jobs.lever.co/acme/abc",
    "https://example.com/careers/software-engineer",
  ]);
});

test("extracts Bing result URLs from direct and redirect links", () => {
  const wrapped = `https://www.bing.com/ck/a?u=${Buffer.from("https://example.com/careers/ml-intern").toString("base64")}`;
  const html = `
    <li class="b_algo"><h2><a href="https://jobs.lever.co/acme/abc">Job</a></h2></li>
    <li class="b_algo"><h2><a href="${wrapped}">Careers</a></h2></li>
    <a href="https://www.bing.com/search?q=ignored">Ignored</a>
  `;

  assert.deepEqual(extractBingResultUrls(html), [
    "https://jobs.lever.co/acme/abc",
    "https://example.com/careers/ml-intern",
  ]);
});

test("ignores Bing non-result navigation links", () => {
  const html = `
    <a href="https://www.hao123.com/">Browser chrome</a>
    <a href="https://dictionary.cambridge.org/zhs/machine">Dictionary sidebar</a>
    <li class="b_algo"><h2><a href="https://jobs.ashbyhq.com/acme">Careers</a></h2></li>
  `;

  assert.deepEqual(extractBingResultUrls(html), [
    "https://jobs.ashbyhq.com/acme",
  ]);
});

test("records only unknown URLs that still look like hiring candidates", () => {
  assert.equal(
    shouldRecordDiscoveryCandidate(
      "https://dictionary.cambridge.org/dictionary/english/machine",
      classifyDiscoveryUrl("https://dictionary.cambridge.org/dictionary/english/machine"),
    ),
    false,
  );
  assert.equal(
    shouldRecordDiscoveryCandidate(
      "https://example.com/open-roles/software-engineer-new-grad",
      classifyDiscoveryUrl("https://example.com/open-roles/software-engineer-new-grad"),
    ),
    true,
  );
});

test("does not promote generic student or publication pages as hiring candidates", () => {
  const student = classifyDiscoveryUrl("https://student.xylemlearning.com/");
  assert.equal(
    shouldRecordDiscoveryCandidate("https://student.xylemlearning.com/", student),
    false,
  );

  const report = classifyDiscoveryUrl(
    "https://www.weforum.org/publications/the-future-of-jobs-report-2025/digest/",
  );
  assert.equal(report.sourceType, "content_article");
  assert.equal(report.rejected, true);
});

test("requires a China signal before writing broad official career candidates", () => {
  const overseas = classifyDiscoveryUrl("https://jala.tech/careers");
  assert.equal(
    hasChinaOfficialSignal("https://jala.tech/careers", overseas, {
      city: "上海",
      query: "数据分析 实习 上海",
    }),
    false,
  );

  const shanghai = classifyDiscoveryUrl("https://jobs.sanofi.com/en/job/shanghai/data-intern/1");
  assert.equal(
    hasChinaOfficialSignal("https://jobs.sanofi.com/en/job/shanghai/data-intern/1", shanghai, {
      city: "上海",
      query: "数据分析 实习 上海",
    }),
    true,
  );

  const chinaDomain = classifyDiscoveryUrl("https://www.shlab.org.cn/joinus/detail/1?mode=campus");
  assert.equal(
    hasChinaOfficialSignal("https://www.shlab.org.cn/joinus/detail/1?mode=campus", chinaDomain, {
      city: "上海",
      query: "数据分析 实习 上海",
    }),
    true,
  );
});

test("summarizes discovery outcome without hiding zero-result failures", () => {
  assert.deepEqual(
    summarizeDiscoveryOutcome({
      totalExtractedUrls: 0,
      blockedCount: 0,
      candidatesFound: 0,
      candidatesParsed: 0,
      candidatesPending: 0,
      jobsCreated: 0,
      jobsUpdated: 0,
      providers: [
        { name: "duckduckgo", status: "provider_failed", extracted_urls: 0 },
        { name: "bing_html", status: "no_results_found", extracted_urls: 0 },
      ],
      errors: ["DuckDuckGo returned HTTP 202"],
    }),
    {
      status: "failed",
      failureReason: "provider_failed",
      errorMessage: "DuckDuckGo returned HTTP 202",
    },
  );

  assert.deepEqual(
    summarizeDiscoveryOutcome({
      totalExtractedUrls: 0,
      blockedCount: 0,
      candidatesFound: 0,
      candidatesParsed: 0,
      candidatesPending: 0,
      jobsCreated: 0,
      jobsUpdated: 0,
      providers: [
        {
          name: "baidu_qianfan_web_search",
          status: "provider_failed",
          http_status: 429,
          extracted_urls: 0,
          diagnostics: { rate_limited: true },
        },
      ],
      errors: ["Baidu Qianfan returned HTTP 429"],
    }),
    {
      status: "failed",
      failureReason: "provider_rate_limited",
      errorMessage: "Baidu Qianfan returned HTTP 429",
    },
  );

  assert.deepEqual(
    summarizeDiscoveryOutcome({
      totalExtractedUrls: 0,
      blockedCount: 0,
      candidatesFound: 0,
      candidatesParsed: 0,
      candidatesPending: 0,
      jobsCreated: 0,
      jobsUpdated: 0,
      providers: [
        {
          name: "baidu_qianfan_web_search",
          status: "no_results_found",
          extracted_urls: 0,
        },
      ],
      errors: [],
    }),
    {
      status: "failed",
      failureReason: "provider_no_results",
      errorMessage: "Search provider returned no extractable results.",
    },
  );

  assert.deepEqual(
    summarizeDiscoveryOutcome({
      totalExtractedUrls: 4,
      blockedCount: 0,
      candidatesFound: 4,
      candidatesParsed: 0,
      candidatesPending: 4,
      jobsCreated: 0,
      jobsUpdated: 0,
      providers: [
        { name: "duckduckgo", status: "success", extracted_urls: 4 },
        { name: "bing_html", status: "skipped", extracted_urls: 0 },
      ],
      errors: [],
    }),
    {
      status: "partial_success",
      failureReason: "candidates_pending",
      errorMessage: "Discovered candidates are pending review or unsupported parsers; no jobs were written.",
    },
  );

  assert.deepEqual(
    summarizeDiscoveryOutcome({
      totalExtractedUrls: 10,
      blockedCount: 10,
      candidatesFound: 0,
      candidatesParsed: 0,
      candidatesPending: 0,
      jobsCreated: 0,
      jobsUpdated: 0,
      providers: [
        { name: "bing_html", status: "success", extracted_urls: 10 },
      ],
      errors: [],
    }),
    {
      status: "failed",
      failureReason: "all_results_rejected",
      errorMessage:
        "Search provider returned URLs, but every result was rejected by source-quality filters.",
    },
  );

  assert.deepEqual(
    summarizeDiscoveryOutcome({
      totalExtractedUrls: 2,
      blockedCount: 0,
      candidatesFound: 2,
      candidatesParsed: 0,
      candidatesPending: 2,
      parserSupportedCandidates: 0,
      jobsCreated: 0,
      jobsUpdated: 0,
      providers: [{ name: "baidu_qianfan_web_search", status: "success", extracted_urls: 2 }],
      errors: [],
    }),
    {
      status: "partial_success",
      failureReason: "parser_missing",
      errorMessage:
        "Official candidates were recorded, but no supported parser can produce high-quality job detail URLs yet.",
    },
  );

  assert.deepEqual(
    summarizeDiscoveryOutcome({
      totalExtractedUrls: 2,
      blockedCount: 0,
      candidatesFound: 1,
      candidatesParsed: 0,
      candidatesPending: 0,
      candidatesFailed: 1,
      parserSupportedCandidates: 1,
      qualityGateFailures: 1,
      jobsCreated: 0,
      jobsUpdated: 0,
      providers: [{ name: "baidu_qianfan_web_search", status: "success", extracted_urls: 2 }],
      errors: ["generic_official_detail quality gate rejected https://example.cn/jobs: detail_page_missing_title"],
    }),
    {
      status: "partial_success",
      failureReason: "quality_gate_failed",
      errorMessage:
        "generic_official_detail quality gate rejected https://example.cn/jobs: detail_page_missing_title",
    },
  );
});

test("builds discovery queries from keyword, company, city, and job type", () => {
  assert.deepEqual(
    buildDiscoveryQueries({
      query: "数据分析",
      company: "百度",
      city: "上海",
      jobType: "实习",
    }).slice(0, 7),
    [
      "数据分析 实习 上海 招聘 官网",
      "数据分析 实习 上海 校招 官网",
      "数据分析 实习 上海 职位详情",
      "数据分析 实习 上海 社招 官网",
      "数据分析 实习 上海 官方招聘",
      "数据分析 实习 上海 人才招聘",
      "数据分析 实习 上海 校园招聘",
    ],
  );
});

test("builds user-scoped discovery cache keys from normalized search inputs", () => {
  const key = buildDiscoveryCacheKey({
    userId: "user-a",
    query: " 数据分析 实习 上海 ",
    city: "上海",
    jobType: "实习",
  });

  assert.equal(key, "user-a|数据分析 实习 上海|上海||实习");
  assert.notEqual(
    key,
    buildDiscoveryCacheKey({
      userId: "user-b",
      query: "数据分析 实习 上海",
      city: "上海",
      jobType: "实习",
    }),
  );
});

test("selects one generated query by default and only the second query for continue", () => {
  const generated = buildDiscoveryQueries({
    query: "数据分析 实习 上海",
  });

  assert.deepEqual(selectDiscoveryQueryBatch({ discoveryQueries: generated }), {
    calledQueries: [generated[0]],
    queryOffset: 0,
    queryLimit: 1,
    maxGeneratedQueries: 2,
    canContinue: true,
    nextQueryOffset: 1,
  });

  assert.deepEqual(
    selectDiscoveryQueryBatch({
      discoveryQueries: generated,
      queryOffset: 1,
      queryLimit: 5,
      maxGeneratedQueries: 2,
    }),
    {
      calledQueries: [generated[1]],
      queryOffset: 1,
      queryLimit: 1,
      maxGeneratedQueries: 2,
      canContinue: false,
      nextQueryOffset: null,
    },
  );
});

test("blocks Baidu Qianfan when the daily discovery budget is exhausted", () => {
  assert.deepEqual(
    buildDiscoveryDailyBudgetStatus({
      callsToday: 40,
      maxDailySearchCalls: 40,
      now: new Date("2026-05-27T03:30:00.000Z"),
    }),
    {
      allowed: false,
      calls_today: 40,
      max_daily_search_calls: 40,
      remaining_calls: 0,
      failure_reason: "daily_search_budget_exhausted",
      window_start: "2026-05-26T16:00:00.000Z",
      window_end: "2026-05-27T16:00:00.000Z",
    },
  );

  assert.equal(
    buildDiscoveryDailyBudgetStatus({
      callsToday: 39,
      maxDailySearchCalls: 40,
      now: new Date("2026-05-27T03:30:00.000Z"),
    }).allowed,
    true,
  );
});

test("uses the Shanghai day window for daily search budget counting", () => {
  assert.deepEqual(
    buildShanghaiDayWindow(new Date("2026-05-27T15:59:59.000Z")),
    {
      start: "2026-05-26T16:00:00.000Z",
      end: "2026-05-27T16:00:00.000Z",
    },
  );

  assert.deepEqual(
    buildShanghaiDayWindow(new Date("2026-05-27T16:00:00.000Z")),
    {
      start: "2026-05-27T16:00:00.000Z",
      end: "2026-05-28T16:00:00.000Z",
    },
  );
});

test("summarizes disabled Qianfan provider separately from rate limits", () => {
  const outcome = summarizeDiscoveryOutcome({
    totalExtractedUrls: 0,
    blockedCount: 0,
    candidatesFound: 0,
    candidatesParsed: 0,
    candidatesPending: 0,
    jobsCreated: 0,
    jobsUpdated: 0,
    providers: [
      createProviderDiagnostic({
        providerName: "baidu_qianfan_web_search",
        query: "数据分析 实习 上海 招聘 官网",
        status: "provider_failed",
        httpStatus: null,
        rawResultsCount: 0,
        extractedUrlsCount: 0,
        error: "Baidu Qianfan web search disabled by BAIDU_QIANFAN_SEARCH_DISABLED",
        diagnostics: {
          disabled: true,
          disabled_by_env: true,
          rate_limited: false,
        },
      }),
    ],
    errors: ["Baidu Qianfan web search disabled by BAIDU_QIANFAN_SEARCH_DISABLED"],
  });

  assert.equal(outcome.status, "failed");
  assert.equal(outcome.failureReason, "provider_disabled");
});

test("builds raw result audit rows with classification and rejection reasons", () => {
  const audit = buildRawResultsAudit({
    providers: [
      createProviderDiagnostic({
        providerName: "baidu_qianfan_web_search",
        query: "数据分析 实习 上海 招聘 官网",
        status: "success",
        httpStatus: 200,
        rawResultsCount: 3,
        extractedUrlsCount: 3,
        results: [
          {
            title: "上海实验室 - 加入我们",
            url: "https://www.shlab.org.cn/joinus/detail/1?mode=campus",
            snippet: "数据分析实习生招聘",
          },
          {
            title: "猎聘 数据分析 实习",
            url: "https://www.liepin.com/job/123",
            snippet: "第三方平台",
          },
          {
            title: "高校就业转载",
            url: "https://career.tsinghua.edu.cn/jobfair/jobs/123",
            snippet: "宣讲会转载",
          },
        ],
        diagnostics: {},
      }),
    ],
    limitPerQuery: 10,
  });

  assert.equal(audit.length, 3);
  assert.deepEqual(audit[0], {
    provider_name: "baidu_qianfan_web_search",
    query: "数据分析 实习 上海 招聘 官网",
    title: "上海实验室 - 加入我们",
    url: "https://www.shlab.org.cn/joinus/detail/1?mode=campus",
    snippet: "数据分析实习生招聘",
    classification: "official_campus",
    detected_platform: "official_careers",
    reject_reason: null,
    official_signal: "known_china_official_source",
    confidence: 0.85,
  });
  assert.equal(audit[1].classification, "third_party_job_board");
  assert.equal(audit[1].reject_reason, "Blocked third-party job board");
  assert.equal(audit[2].classification, "campus_repost");
  assert.equal(audit[2].reject_reason, "Blocked university career-center repost page");
});

test("summarizes cached discovery without pretending cached jobs were created", () => {
  const summary = summarizeCachedDiscovery({
    run: {
      status: "partial_success",
      error_message: "Discovered candidates are pending review.",
    },
    candidates: [
      { status: "parsed", url: "https://www.shlab.org.cn/joinus/detail/1?mode=campus" },
      { status: "pending", url: "https://career.example.cn/jobs" },
    ],
    jobs: [
      {
        title: "数据分析实习生",
        jd_url: "https://www.shlab.org.cn/joinus/detail/1?mode=campus",
      },
    ],
  });

  assert.equal(summary.cache_hit, true);
  assert.equal(summary.candidates_found, 2);
  assert.equal(summary.candidates_parsed, 1);
  assert.equal(summary.candidates_pending, 1);
  assert.equal(summary.jobs_reused, 1);
  assert.equal(summary.jobs_created, 0);
  assert.equal(summary.jobs_updated, 0);
});

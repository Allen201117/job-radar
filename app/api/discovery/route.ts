import { NextRequest, NextResponse } from "next/server";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { createServerSupabase } from "@/lib/auth";
import liveSearch from "@/lib/live-search";
import officialDiscovery from "@/lib/official-discovery";
import baiduQianfanSearch from "@/lib/baidu-qianfan-search";
import { jobsStoreEnabled, jobsByUrls } from "@/lib/jobs-store/read";

const {
  searchBaiduQianfanWeb,
} = baiduQianfanSearch as any;

const {
  expandSearchTerms,
  extractAppleSearchResultsFromHtml,
  extractBaiduInitialDataFromHtml,
  filterJobsByQueryAndCity,
  formatAppleSearchResult,
  formatBaiduSearchResult,
  formatGreenhouseJob,
  formatJdJob,
  formatLeverPosting,
  isHighQualityJdUrl,
  mergeJobsByUrl,
  toApiJob,
} = liveSearch;

const {
  buildDiscoveryCacheKey,
  buildDiscoveryDailyBudgetStatus,
  buildRawResultsAudit,
  buildSourceCandidateRecord,
  buildSourceCandidateStatusReason,
  buildShanghaiDayWindow,
  buildMokaBoardUrl,
  buildDiscoveryQueries,
  classifyDiscoveryUrl,
  createProviderDiagnostic,
  extractGenericOfficialDetailJob,
  extractMokaJobsFromHtml,
  extractMokaJobsFromRows,
  extractBingResultUrls,
  extractDuckDuckGoResultUrls,
  hasChinaOfficialSignal,
  shouldRecordDiscoveryCandidate,
  selectDiscoveryQueryBatch,
  summarizeCachedDiscovery,
  summarizeDiscoveryOutcome,
  validateJobQualityGate,
} = officialDiscovery as any;

const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36";
const DISCOVERY_TIMEOUT = 10000;
const ATS_TIMEOUT = 8000;
const DISCOVERY_URL_LIMIT = Number(process.env.DISCOVERY_URL_LIMIT || 24);
const DISCOVERY_MAX_QUERY_PER_CLICK = Math.min(
  Math.max(Number(process.env.DISCOVERY_MAX_QUERY_PER_CLICK || 1), 1),
  1,
);
const DISCOVERY_MAX_GENERATED_QUERIES = Math.min(
  Math.max(Number(process.env.DISCOVERY_MAX_GENERATED_QUERIES || 2), 1),
  2,
);
const DISCOVERY_CACHE_TTL_MINUTES = Math.min(
  Math.max(Number(process.env.DISCOVERY_CACHE_TTL_MINUTES || 45), 30),
  60,
);
const BAIDU_QIANFAN_QUERY_DELAY_MS = Math.max(
  Number(process.env.BAIDU_QIANFAN_QUERY_DELAY_MS || 500),
  0,
);
const BAIDU_QIANFAN_RATE_LIMIT_COOLDOWN_MINUTES = Math.min(
  Math.max(Number(process.env.BAIDU_QIANFAN_RATE_LIMIT_COOLDOWN_MINUTES || 30), 5),
  60,
);
const MAX_DAILY_SEARCH_CALLS = Math.max(
  Number(process.env.MAX_DAILY_SEARCH_CALLS || 40),
  1,
);
const APPLE_SEARCH_URL = "https://jobs.apple.com/en-us/search";
const BAIDU_SEARCH_URL = "https://talent.baidu.com/jobs/social-list";
const JD_JOB_LIST_URL = "https://zhaopin.jd.com/web/job/job_list";
const JD_REFERER_URL = "https://zhaopin.jd.com/web/job/job_info_list/3";

const discoveryMemoryCache = new Map<string, { expiresAt: number; response: any }>();
let baiduQianfanRateLimitedUntil = 0;

type DiscoveryClassification = {
  detectedPlatform: string;
  dbDetectedPlatform: string;
  sourceType: string;
  company: string | null;
  confidence: number;
  reason: string;
  officialSignal: string | null;
  matchedKeywords: string[];
  rejectReason: string | null;
  parserSupported: boolean;
  parserName: string | null;
  slug: string | null;
  rejected?: boolean;
};

type DiscoveryCandidate = DiscoveryClassification & {
  id?: string;
  url: string;
  status: "pending" | "parsed" | "failed";
  providerResult?: any;
};

type UpsertedJob = {
  row: Record<string, unknown>;
  action: "created" | "updated";
};

type ProviderDiagnostic = {
  provider_name: string;
  name: string;
  status: "success" | "partial_success" | "provider_failed" | "no_results_found" | "skipped";
  http_status: number | null;
  raw_results_count: number;
  rawResultsCount: number;
  extracted_urls_count: number;
  extracted_urls: number;
  results: Array<{
    title: string;
    url: string;
    snippet: string;
  }>;
  error: string | null;
  query: string;
  diagnostics: {
    configured?: boolean;
    queries?: Array<{
      provider_name: string;
      name: string;
      query: string;
      status: string;
      http_status: number | null;
      raw_results_count: number;
      rawResultsCount: number;
      extracted_urls_count: number;
      extracted_urls: number;
      error: string | null;
      diagnostics: Record<string, unknown>;
    }>;
    [key: string]: unknown;
  };
  queries?: Array<{
    query: string;
    status: string;
    http_status: number | null;
    raw_results_count?: number;
    extracted_urls: number;
    error: string | null;
  }>;
};

export async function GET(request: NextRequest) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  const params = request.nextUrl.searchParams;
  const query = (params.get("query") || "").trim();
  const city = (params.get("city") || "").trim();
  const company = (params.get("company") || "").trim();
  const jobType = (params.get("jobType") || params.get("function") || "").trim();
  const limit = Math.min(Number(params.get("limit") || 30), 60);
  const forceRefresh = parseBooleanParam(params, "forceRefresh") ||
    parseBooleanParam(params, "force_refresh");
  const queryOffset = parseQueryOffset(params);
  const startedAt = Date.now();

  if (!query) {
    return NextResponse.json(
      { ok: false, error: "Missing query", mode: "official_job_discovery" },
      { status: 400 },
    );
  }

  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    return NextResponse.json(
      {
        ok: false,
        error: "Missing SUPABASE_SERVICE_ROLE_KEY",
        mode: "official_job_discovery",
      },
      { status: 500 },
    );
  }

  const service = createServiceClient();
  const discoveryQueries = buildDiscoveryQueries({ query, company, city, jobType });
  const queryBatch = selectDiscoveryQueryBatch({
    discoveryQueries,
    queryOffset,
    queryLimit: DISCOVERY_MAX_QUERY_PER_CLICK,
    maxGeneratedQueries: DISCOVERY_MAX_GENERATED_QUERIES,
  });
  const baseCacheKey = buildDiscoveryCacheKey({
    userId: user.id,
    query,
    city,
    company,
    jobType,
  });
  const cacheKey = buildScopedDiscoveryCacheKey(baseCacheKey, queryBatch.queryOffset);
  const cachedMemoryResponse = forceRefresh ? null : readMemoryDiscoveryCache(cacheKey);
  if (!forceRefresh && cachedMemoryResponse) {
    const response = markCachedDiscoveryResponse(cachedMemoryResponse, "memory");
    await writeCacheHitDiscoveryRun(service, {
      query,
      city,
      company,
      jobType,
      response,
      startedAt,
    });
    return NextResponse.json(response);
  }

  const cachedDiscovery = forceRefresh
    ? null
    : await readRecentDiscoveryCache(service, {
      query,
      city,
      company,
      jobType,
      discoveryQueries,
      queryBatch,
    });
  if (cachedDiscovery) {
    const response = buildCachedDiscoveryResponse({
      query,
      city,
      company,
      jobType,
      discoveryQueries,
      queryBatch,
      cachedDiscovery,
      startedAt,
    });
    await writeCacheHitDiscoveryRun(service, {
      query,
      city,
      company,
      jobType,
      response,
      startedAt,
    });
    writeMemoryDiscoveryCache(cacheKey, response);
    return NextResponse.json(response);
  }

  const errors: string[] = [];
  let blockedCount = 0;
  let rejectedThirdPartyCount = 0;
  let rejectedContentCount = 0;
  let rejectedNonOfficialCount = 0;
  let sourceCandidatesCreated = 0;
  let sourceCandidatesReused = 0;

  const dailyBudget = await readDailySearchBudgetStatus(service);
  if (!dailyBudget.allowed) {
    const responseBody = await buildBudgetExhaustedResponse({
      service,
      query,
      city,
      company,
      jobType,
      discoveryQueries,
      queryBatch,
      forceRefresh,
      startedAt,
      dailyBudget,
    });
    return NextResponse.json(responseBody);
  }

  const discoveryResult = await collectDiscoveryUrls(queryBatch.calledQueries, errors);
  const discoveredUrls = discoveryResult.urls;
  const providerDiagnostics = discoveryResult.providers;
  const providerResultByUrl = discoveryResult.providerResultByUrl;
  const rawResultsAudit = buildRawResultsAudit({
    providers: providerDiagnostics,
    limitPerQuery: 10,
  });
  const candidates: DiscoveryCandidate[] = [];
  const parsedByBoard = new Map<string, UpsertedJob[]>();

  for (const url of discoveredUrls.slice(0, DISCOVERY_URL_LIMIT)) {
    const classification = classifyDiscoveryUrl(url) as DiscoveryClassification;
    if (classification.rejected) {
      blockedCount += 1;
      if (classification.sourceType === "third_party_job_board") {
        rejectedThirdPartyCount += 1;
      } else if (classification.sourceType === "content_article") {
        rejectedContentCount += 1;
      }
      continue;
    }
    if (!shouldRecordDiscoveryCandidate(url, classification)) {
      blockedCount += 1;
      rejectedNonOfficialCount += 1;
      continue;
    }
    if (!hasChinaOfficialSignal(url, classification, { city, query })) {
      blockedCount += 1;
      rejectedNonOfficialCount += 1;
      continue;
    }

    const candidate = await upsertSourceCandidate(service, {
      query,
      fallbackCompany: company || null,
      fallbackTitle: query,
      url,
      classification,
      providerResult: providerResultByUrl.get(url) || null,
      status: "pending",
    });
    if (!candidate) {
      errors.push(`Failed to record source candidate: ${url}`);
      continue;
    }
    if (candidate.created) {
      sourceCandidatesCreated += 1;
    } else {
      sourceCandidatesReused += 1;
    }

    candidates.push({
      ...classification,
      id: candidate.id,
      url,
      status: "pending",
      providerResult: providerResultByUrl.get(url) || null,
    });
  }

  const upsertedJobs: UpsertedJob[] = [];
  for (const candidate of candidates) {
    if (!candidate.parserSupported) continue;

    const boardKey = `${candidate.parserName || candidate.detectedPlatform}:${candidate.slug || candidate.company || candidate.url}`;
    let boardJobs = parsedByBoard.get(boardKey);

    if (!boardJobs) {
      boardJobs = await parseSupportedBoard({
        service,
        candidate,
        query,
        city,
        jobType,
        limit,
        errors,
      });
      parsedByBoard.set(boardKey, boardJobs);
    }

    if (boardJobs.length > 0) {
      upsertedJobs.push(...boardJobs);
      await updateSourceCandidateStatus(
        service,
        candidate,
        "parsed",
        `Parsed ${boardJobs.length} jobs with accurate official detail URLs`,
      );
      candidate.status = "parsed";
    } else {
      await updateSourceCandidateStatus(
        service,
        candidate,
        "failed",
        "Supported parser returned no matching jobs with accurate detail URLs",
      );
      candidate.status = "failed";
    }
  }

  const mergedJobs = mergeJobsByUrl(
    [],
    upsertedJobs.map((job) => job.row),
  ).slice(0, limit);
  const jobsCreated = upsertedJobs.filter((job) => job.action === "created").length;
  const jobsUpdated = upsertedJobs.filter((job) => job.action === "updated").length;
  const candidatesParsed = candidates.filter((candidate) => candidate.status === "parsed").length;
  const candidatesPending = candidates.filter((candidate) => candidate.status === "pending").length;
  const candidatesFailed = candidates.filter((candidate) => candidate.status === "failed").length;
  const parserSupportedCandidates = candidates.filter((candidate) => candidate.parserSupported).length;
  const qualityGateFailures = errors.filter((error) => /quality gate rejected/i.test(error)).length;
  const outcome = summarizeDiscoveryOutcome({
    totalExtractedUrls: discoveredUrls.length,
    blockedCount,
    candidatesFound: candidates.length,
    candidatesParsed,
    candidatesPending,
    candidatesFailed,
    parserSupportedCandidates,
    qualityGateFailures,
    jobsCreated,
    jobsUpdated,
    providers: providerDiagnostics,
    errors,
  });

  const diagnostics = {
    providers: providerDiagnostics,
    generated_queries: discoveryQueries,
    query_offset: queryBatch.queryOffset,
    query_limit: queryBatch.queryLimit,
    max_generated_queries: queryBatch.maxGeneratedQueries,
    max_query_per_click: DISCOVERY_MAX_QUERY_PER_CLICK,
    can_continue_discovery: queryBatch.canContinue,
    next_query_offset: queryBatch.nextQueryOffset,
    force_refresh: forceRefresh,
    providers_called: providerDiagnostics.map((provider) => provider.provider_name || provider.name),
    provider_used: providerDiagnostics.map((provider) => provider.provider_name || provider.name),
    generated_queries_called: discoveryResult.calledQueries,
    generated_queries_called_count: discoveryResult.calledQueries.length,
    baidu_qianfan_status: getProviderStatus(providerDiagnostics, "baidu_qianfan_web_search"),
    provider_http_status: getProviderHttpStatus(providerDiagnostics, "baidu_qianfan_web_search"),
    rate_limited: providerDiagnostics.some((provider) => isRateLimitedDiagnostic(provider)),
    cache_hit: false,
    cache_ttl_minutes: DISCOVERY_CACHE_TTL_MINUTES,
    daily_budget: dailyBudget,
    raw_results_count: providerDiagnostics.reduce(
      (sum, provider) => sum + (provider.raw_results_count || 0),
      0,
    ),
    raw_results_sample: rawResultsAudit,
    total_results_from_search: discoveredUrls.length,
    official_candidates_count: candidates.length,
    blocked_results: blockedCount,
    rejected_third_party_count: rejectedThirdPartyCount,
    rejected_content_count: rejectedContentCount,
    rejected_non_official_count: rejectedNonOfficialCount,
    failure_reason: outcome.failureReason,
    candidates: {
      found: candidates.length,
      parsed: candidatesParsed,
      pending: candidatesPending,
      failed: candidatesFailed,
      created: sourceCandidatesCreated,
      reused: sourceCandidatesReused,
      parser_supported: parserSupportedCandidates,
    },
    jobs: {
      parsed: upsertedJobs.length,
      created: jobsCreated,
      updated: jobsUpdated,
    },
  };

  const discoveryRun = await writeDiscoveryRun(service, {
    query,
    city,
    company,
    jobType,
    status: outcome.status,
    candidatesFound: candidates.length,
    candidatesParsed,
    candidatesPending,
    jobsCreated,
    jobsUpdated,
    blockedCount,
    errorMessage: outcome.errorMessage,
    providerName: "baidu_qianfan_web_search",
    providerQuery: discoveryResult.calledQueries[0] || null,
    rawResultsCount: diagnostics.raw_results_count,
    officialCandidatesCount: candidates.length,
    sourceCandidatesCreated,
    sourceCandidatesReused,
    rateLimited: diagnostics.rate_limited,
    cacheHit: false,
    failureReason: outcome.failureReason,
    diagnostics,
  });
  if (discoveryRun.error) {
    errors.push(`Discovery run insert failed: ${discoveryRun.error}`);
  }

  const responseBody = {
    ok: true,
    mode: "official_job_discovery",
    discovery_run_id: discoveryRun.id,
    status: outcome.status,
    query,
    query_offset: queryBatch.queryOffset,
    query_limit: queryBatch.queryLimit,
    max_generated_queries: queryBatch.maxGeneratedQueries,
    can_continue_discovery: queryBatch.canContinue,
    next_query_offset: queryBatch.nextQueryOffset,
    force_refresh: forceRefresh,
    generated_queries: discoveryQueries,
    provider_used: diagnostics.providers_called,
    provider_http_status: diagnostics.provider_http_status,
    generated_queries_called: discoveryResult.calledQueries,
    generated_queries_called_count: discoveryResult.calledQueries.length,
    providers_called: diagnostics.providers_called,
    baidu_qianfan_status: diagnostics.baidu_qianfan_status,
    rate_limited: diagnostics.rate_limited,
    cache_hit: false,
    cache_ttl_minutes: DISCOVERY_CACHE_TTL_MINUTES,
    daily_budget: dailyBudget,
    raw_results_count: diagnostics.raw_results_count,
    raw_results_sample: rawResultsAudit,
    official_candidates_count: candidates.length,
    rejected_third_party_count: rejectedThirdPartyCount,
    rejected_content_count: rejectedContentCount,
    rejected_non_official_count: rejectedNonOfficialCount,
    source_candidates_created: sourceCandidatesCreated,
    source_candidates_reused: sourceCandidatesReused,
    jobs: mergedJobs.map((job: any) => toApiJob(job, 60)),
    total: mergedJobs.length,
    total_results_from_search: discoveredUrls.length,
    candidates_found: candidates.length,
    pending_candidates: candidatesPending,
    parsed_jobs: upsertedJobs.length,
    jobs_created: jobsCreated,
    jobs_updated: jobsUpdated,
    blocked_results: blockedCount,
    sample_candidates: candidates.slice(0, 5).map((candidate) => ({
      title: providerResultByUrl.get(candidate.url)?.title || null,
      url: candidate.url,
      snippet: providerResultByUrl.get(candidate.url)?.snippet || null,
      company_guess: candidate.company,
      classification: candidate.sourceType,
      detected_platform: candidate.detectedPlatform,
      confidence: candidate.confidence,
      status: candidate.status,
      reason: candidate.reason,
    })),
    sample_jobs: mergedJobs.slice(0, 5).map((job: any) => ({
      company: job.company,
      title: job.title,
      location: job.location,
      job_type: job.job_type,
      jd_url: job.jd_url,
      http_status: job.__quality?.http_status ?? null,
      page_contains_title: job.__quality?.page_contains_title ?? null,
      quality_pass: Boolean(job.__quality?.ok ?? true),
    })),
    failure_reason: outcome.failureReason,
    diagnostics,
    error_message: outcome.errorMessage,
    candidatesFound: candidates.length,
    candidatesParsed,
    candidatesPending,
    candidatesFailed,
    jobsCreated,
    jobsUpdated,
    blockedCount,
    discoveredPlatforms: Array.from(
      new Set(candidates.map((candidate) => candidate.detectedPlatform)),
    ),
    searchedQueries: discoveryQueries,
    errors,
    qualityGate: "Only jobs with parser-verified official detail jd_url are written to jobs",
    searchedAt: new Date().toISOString(),
    latencyMs: Date.now() - startedAt,
  };

  writeMemoryDiscoveryCache(cacheKey, responseBody);
  return NextResponse.json(responseBody);
}

async function readRecentDiscoveryCache(
  service: SupabaseClient,
  {
    query,
    city,
    company,
    jobType,
    discoveryQueries,
    queryBatch,
  }: {
    query: string;
    city: string;
    company: string;
    jobType: string;
    discoveryQueries: string[];
    queryBatch: any;
  },
) {
  const cutoff = new Date(Date.now() - DISCOVERY_CACHE_TTL_MINUTES * 60 * 1000).toISOString();
  let runQuery: any = service
    .from("discovery_runs")
    .select("*")
    .eq("query", query)
    .gte("created_at", cutoff)
    .order("created_at", { ascending: false })
    .limit(1);

  runQuery = applyNullableSupabaseFilter(runQuery, "city", city);
  runQuery = applyNullableSupabaseFilter(runQuery, "company", company);
  runQuery = applyNullableSupabaseFilter(runQuery, "job_type", jobType);

  const { data: run, error: runError } = await runQuery.maybeSingle();
  if (runError || !run) return null;

  const { data: candidates, error: candidatesError } = await service
    .from("source_candidates")
    .select("*")
    .eq("query", query)
    .gte("created_at", cutoff)
    .neq("status", "rejected")
    .order("created_at", { ascending: false })
    .limit(DISCOVERY_URL_LIMIT);
  if (candidatesError) return null;

  let candidateRows = filterCandidatesByProviderQuery(
    candidates || [],
    queryBatch.calledQueries || [],
  );
  if (queryBatch.queryOffset === 0 && candidateRows.length === 0 && (candidates || []).length > 0) {
    candidateRows = candidates || [];
  }
  if (queryBatch.queryOffset > 0 && candidateRows.length === 0) return null;
  const parsedUrls = candidateRows
    .filter((candidate: any) => candidate.status === "parsed" && candidate.url)
    .map((candidate: any) => candidate.url);
  // jobs 已迁自建香港 PG：缓存命中的岗位回查走 jobs-store；异常落回 Supabase 兜底。
  let jobs: any[] = [];
  if (parsedUrls.length > 0) {
    let fetched = false;
    if (jobsStoreEnabled()) {
      try {
        jobs = await jobsByUrls(parsedUrls, true);
        fetched = true;
      } catch {
        /* 香港库异常 → 走 Supabase 兜底 */
      }
    }
    if (!fetched) {
      const { data: cachedJobs } = await service
        .from("jobs")
        .select("*")
        .in("jd_url", parsedUrls)
        .eq("status", "active");
      jobs = cachedJobs || [];
    }
  }

  return {
    run,
    candidates: candidateRows,
    jobs,
    discoveryQueries,
    cutoff,
  };
}

function buildCachedDiscoveryResponse({
  query,
  city,
  company,
  jobType,
  discoveryQueries,
  queryBatch,
  cachedDiscovery,
  startedAt,
}: {
  query: string;
  city: string;
  company: string;
  jobType: string;
  discoveryQueries: string[];
  queryBatch: any;
  cachedDiscovery: {
    run: any;
    candidates: any[];
    jobs: any[];
    cutoff: string;
  };
  startedAt: number;
}) {
  const summary = summarizeCachedDiscovery({
    run: cachedDiscovery.run,
    candidates: cachedDiscovery.candidates,
    jobs: cachedDiscovery.jobs,
  });
  const diagnostics = {
    providers: [],
    generated_queries: discoveryQueries,
    query_offset: queryBatch.queryOffset,
    query_limit: queryBatch.queryLimit,
    max_generated_queries: queryBatch.maxGeneratedQueries,
    can_continue_discovery: queryBatch.canContinue,
    next_query_offset: queryBatch.nextQueryOffset,
    force_refresh: false,
    providers_called: ["cache"],
    provider_used: ["cache"],
    generated_queries_called: [],
    generated_queries_called_count: 0,
    baidu_qianfan_status: "cached",
    provider_http_status: null,
    rate_limited: false,
    cache_hit: true,
    cache_source: "discovery_runs",
    cache_ttl_minutes: DISCOVERY_CACHE_TTL_MINUTES,
    cache_cutoff: cachedDiscovery.cutoff,
    raw_results_count: 0,
    raw_results_sample: [],
    total_results_from_search: cachedDiscovery.candidates.length,
    official_candidates_count: cachedDiscovery.candidates.length,
    blocked_results: cachedDiscovery.run?.blocked_count || 0,
    rejected_third_party_count: 0,
    rejected_content_count: 0,
    failure_reason: summary.failure_reason,
    candidates: {
      found: summary.candidates_found,
      parsed: summary.candidates_parsed,
      pending: summary.candidates_pending,
      failed: summary.candidates_failed,
      created: 0,
      reused: cachedDiscovery.candidates.length,
    },
    jobs: {
      parsed: cachedDiscovery.jobs.length,
      created: 0,
      updated: 0,
      reused: cachedDiscovery.jobs.length,
    },
  };

  return {
    ok: true,
    mode: "official_job_discovery",
    discovery_run_id: cachedDiscovery.run?.id || null,
    status: summary.status,
    query,
    city,
    company,
    job_type: jobType,
    query_offset: queryBatch.queryOffset,
    query_limit: queryBatch.queryLimit,
    max_generated_queries: queryBatch.maxGeneratedQueries,
    max_query_per_click: DISCOVERY_MAX_QUERY_PER_CLICK,
    can_continue_discovery: queryBatch.canContinue,
    next_query_offset: queryBatch.nextQueryOffset,
    force_refresh: false,
    generated_queries: discoveryQueries,
    provider_used: ["cache"],
    provider_http_status: null,
    generated_queries_called: [],
    generated_queries_called_count: 0,
    providers_called: ["cache"],
    baidu_qianfan_status: "cached",
    rate_limited: false,
    cache_hit: true,
    cache_source: "discovery_runs",
    cache_ttl_minutes: DISCOVERY_CACHE_TTL_MINUTES,
    raw_results_count: 0,
    raw_results_sample: [],
    official_candidates_count: cachedDiscovery.candidates.length,
    rejected_third_party_count: 0,
    rejected_content_count: 0,
    source_candidates_created: 0,
    source_candidates_reused: cachedDiscovery.candidates.length,
    jobs: cachedDiscovery.jobs.map((job: any) => toApiJob(job, 60)),
    total: cachedDiscovery.jobs.length,
    total_results_from_search: cachedDiscovery.candidates.length,
    candidates_found: summary.candidates_found,
    pending_candidates: summary.candidates_pending,
    parsed_jobs: cachedDiscovery.jobs.length,
    jobs_created: 0,
    jobs_updated: 0,
    jobs_reused: cachedDiscovery.jobs.length,
    blocked_results: cachedDiscovery.run?.blocked_count || 0,
    sample_candidates: cachedDiscovery.candidates.slice(0, 5).map((candidate: any) => ({
      title: candidate.title || null,
      url: candidate.url,
      snippet: null,
      company_guess: candidate.company || null,
      classification: candidate.source_type || null,
      detected_platform: candidate.detected_platform || null,
      confidence: candidate.confidence || null,
      status: candidate.status,
      reason: candidate.reason,
    })),
    sample_jobs: cachedDiscovery.jobs.slice(0, 5).map((job: any) => ({
      company: job.company,
      title: job.title,
      location: job.location,
      job_type: job.job_type,
      jd_url: job.jd_url,
      http_status: null,
      page_contains_title: null,
      quality_pass: true,
    })),
    failure_reason: summary.failure_reason,
    diagnostics,
    error_message: summary.error_message,
    candidatesFound: summary.candidates_found,
    candidatesParsed: summary.candidates_parsed,
    candidatesPending: summary.candidates_pending,
    candidatesFailed: summary.candidates_failed,
    jobsCreated: 0,
    jobsUpdated: 0,
    blockedCount: cachedDiscovery.run?.blocked_count || 0,
    discoveredPlatforms: Array.from(
      new Set(cachedDiscovery.candidates.map((candidate: any) => candidate.detected_platform)),
    ).filter(Boolean),
    searchedQueries: discoveryQueries,
    errors: [],
    qualityGate: "Only jobs with parser-verified official detail jd_url are written to jobs",
    searchedAt: new Date().toISOString(),
    latencyMs: Date.now() - startedAt,
  };
}

async function readDailySearchBudgetStatus(service: SupabaseClient) {
  const window = buildShanghaiDayWindow(new Date());
  const withProviderColumns: any = await service
    .from("discovery_runs")
    .select("id", { count: "exact", head: true })
    .gte("created_at", window.start)
    .lt("created_at", window.end)
    .eq("provider_name", "baidu_qianfan_web_search")
    .eq("cache_hit", false);

  if (!withProviderColumns.error) {
    return {
      ...buildDiscoveryDailyBudgetStatus({
        callsToday: withProviderColumns.count || 0,
        maxDailySearchCalls: MAX_DAILY_SEARCH_CALLS,
      }),
      count_source: "discovery_runs_provider_columns",
    };
  }

  const fallback: any = await service
    .from("discovery_runs")
    .select("id", { count: "exact", head: true })
    .gte("created_at", window.start)
    .lt("created_at", window.end);

  if (fallback.error) {
    return {
      ...buildDiscoveryDailyBudgetStatus({
        callsToday: 0,
        maxDailySearchCalls: MAX_DAILY_SEARCH_CALLS,
      }),
      count_source: "count_failed_open",
      count_error: fallback.error.message,
      schema_hint: withProviderColumns.error.message,
    };
  }

  return {
    ...buildDiscoveryDailyBudgetStatus({
      callsToday: fallback.count || 0,
      maxDailySearchCalls: MAX_DAILY_SEARCH_CALLS,
    }),
    count_source: "discovery_runs_total_fallback",
    schema_hint: withProviderColumns.error.message,
  };
}

async function buildBudgetExhaustedResponse({
  service,
  query,
  city,
  company,
  jobType,
  discoveryQueries,
  queryBatch,
  forceRefresh,
  startedAt,
  dailyBudget,
}: {
  service: SupabaseClient;
  query: string;
  city: string;
  company: string;
  jobType: string;
  discoveryQueries: string[];
  queryBatch: any;
  forceRefresh: boolean;
  startedAt: number;
  dailyBudget: any;
}) {
  const diagnostics = {
    providers: [
      createProviderDiagnostic({
        providerName: "baidu_qianfan_web_search",
        query: queryBatch.calledQueries[0] || "",
        status: "provider_failed",
        httpStatus: null,
        rawResultsCount: 0,
        extractedUrlsCount: 0,
        results: [],
        error: "Baidu Qianfan daily search budget exhausted",
        diagnostics: {
          configured: Boolean(process.env.BAIDU_QIANFAN_API_KEY),
          rate_limited: false,
          daily_budget_exhausted: true,
          ...dailyBudget,
        },
      }),
    ],
    generated_queries: discoveryQueries,
    query_offset: queryBatch.queryOffset,
    query_limit: queryBatch.queryLimit,
    max_generated_queries: queryBatch.maxGeneratedQueries,
    max_query_per_click: DISCOVERY_MAX_QUERY_PER_CLICK,
    can_continue_discovery: queryBatch.canContinue,
    next_query_offset: queryBatch.nextQueryOffset,
    force_refresh: forceRefresh,
    providers_called: [],
    provider_used: ["budget_guard"],
    generated_queries_called: [],
    generated_queries_called_count: 0,
    baidu_qianfan_status: "skipped",
    provider_http_status: null,
    rate_limited: false,
    cache_hit: false,
    cache_ttl_minutes: DISCOVERY_CACHE_TTL_MINUTES,
    daily_budget: dailyBudget,
    raw_results_count: 0,
    raw_results_sample: [],
    total_results_from_search: 0,
    official_candidates_count: 0,
    blocked_results: 0,
    rejected_third_party_count: 0,
    rejected_content_count: 0,
    rejected_non_official_count: 0,
    failure_reason: "daily_search_budget_exhausted",
    candidates: {
      found: 0,
      parsed: 0,
      pending: 0,
      failed: 0,
      created: 0,
      reused: 0,
      parser_supported: 0,
    },
    jobs: {
      parsed: 0,
      created: 0,
      updated: 0,
    },
  };

  const discoveryRun = await writeDiscoveryRun(service, {
    query,
    city,
    company,
    jobType,
    status: "failed",
    candidatesFound: 0,
    candidatesParsed: 0,
    candidatesPending: 0,
    jobsCreated: 0,
    jobsUpdated: 0,
    blockedCount: 0,
    errorMessage: "Baidu Qianfan daily search budget exhausted",
    providerName: "baidu_qianfan_web_search",
    providerQuery: queryBatch.calledQueries[0] || null,
    rawResultsCount: 0,
    officialCandidatesCount: 0,
    sourceCandidatesCreated: 0,
    sourceCandidatesReused: 0,
    rateLimited: false,
    cacheHit: false,
    failureReason: "daily_search_budget_exhausted",
    diagnostics,
  });

  return {
    ok: true,
    mode: "official_job_discovery",
    discovery_run_id: discoveryRun.id,
    status: "failed",
    query,
    query_offset: queryBatch.queryOffset,
    query_limit: queryBatch.queryLimit,
    max_generated_queries: queryBatch.maxGeneratedQueries,
    max_query_per_click: DISCOVERY_MAX_QUERY_PER_CLICK,
    can_continue_discovery: queryBatch.canContinue,
    next_query_offset: queryBatch.nextQueryOffset,
    force_refresh: forceRefresh,
    generated_queries: discoveryQueries,
    provider_used: ["budget_guard"],
    provider_http_status: null,
    generated_queries_called: [],
    generated_queries_called_count: 0,
    providers_called: [],
    baidu_qianfan_status: "skipped",
    rate_limited: false,
    cache_hit: false,
    cache_ttl_minutes: DISCOVERY_CACHE_TTL_MINUTES,
    daily_budget: dailyBudget,
    raw_results_count: 0,
    raw_results_sample: [],
    official_candidates_count: 0,
    rejected_third_party_count: 0,
    rejected_content_count: 0,
    rejected_non_official_count: 0,
    source_candidates_created: 0,
    source_candidates_reused: 0,
    jobs: [],
    total: 0,
    total_results_from_search: 0,
    candidates_found: 0,
    pending_candidates: 0,
    parsed_jobs: 0,
    jobs_created: 0,
    jobs_updated: 0,
    blocked_results: 0,
    sample_candidates: [],
    sample_jobs: [],
    failure_reason: "daily_search_budget_exhausted",
    diagnostics,
    error_message: "Baidu Qianfan daily search budget exhausted",
    candidatesFound: 0,
    candidatesParsed: 0,
    candidatesPending: 0,
    candidatesFailed: 0,
    jobsCreated: 0,
    jobsUpdated: 0,
    blockedCount: 0,
    discoveredPlatforms: [],
    searchedQueries: discoveryQueries,
    errors: ["Baidu Qianfan daily search budget exhausted"],
    qualityGate: "Only jobs with parser-verified official detail jd_url are written to jobs",
    searchedAt: new Date().toISOString(),
    latencyMs: Date.now() - startedAt,
  };
}

function parseBooleanParam(params: URLSearchParams, name: string) {
  const value = String(params.get(name) || "").trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes";
}

function parseQueryOffset(params: URLSearchParams) {
  const raw =
    params.get("queryOffset") ||
    params.get("query_offset") ||
    (params.get("continue") ? "1" : "");
  const parsed = Number(raw || 0);
  if (!Number.isFinite(parsed)) return 0;
  return parsed;
}

function buildScopedDiscoveryCacheKey(baseCacheKey: string, queryOffset: number) {
  return `${baseCacheKey}|query_offset:${Math.max(0, Number(queryOffset) || 0)}`;
}

function readMemoryDiscoveryCache(cacheKey: string) {
  const entry = discoveryMemoryCache.get(cacheKey);
  if (!entry) return null;
  if (Date.now() > entry.expiresAt) {
    discoveryMemoryCache.delete(cacheKey);
    return null;
  }
  return entry.response;
}

function writeMemoryDiscoveryCache(cacheKey: string, response: any) {
  discoveryMemoryCache.set(cacheKey, {
    expiresAt: Date.now() + DISCOVERY_CACHE_TTL_MINUTES * 60 * 1000,
    response,
  });
}

function markCachedDiscoveryResponse(response: any, cacheSource: string) {
  const cached = JSON.parse(JSON.stringify(response));
  const reusedCandidates = maxNumericValue([
    cached.source_candidates_reused,
    cached.candidates_found,
    cached.candidatesFound,
    cached.official_candidates_count,
    cached.diagnostics?.candidates?.reused,
    cached.diagnostics?.candidates?.found,
    cached.sample_candidates?.length,
  ]);
  const reusedJobs = maxNumericValue([
    cached.jobs_reused,
    cached.total,
    cached.parsed_jobs,
    cached.jobs?.length,
    cached.diagnostics?.jobs?.reused,
    cached.diagnostics?.jobs?.parsed,
  ]);

  cached.cache_hit = true;
  cached.cache_source = cacheSource;
  cached.provider_used = ["cache"];
  cached.providers_called = ["cache"];
  cached.generated_queries_called = [];
  cached.generated_queries_called_count = 0;
  cached.baidu_qianfan_status = "cached";
  cached.rate_limited = false;
  cached.source_candidates_created = 0;
  cached.source_candidates_reused = reusedCandidates;
  cached.jobs_created = 0;
  cached.jobs_updated = 0;
  cached.jobsCreated = 0;
  cached.jobsUpdated = 0;
  cached.jobs_reused = reusedJobs;
  cached.diagnostics = {
    ...(cached.diagnostics || {}),
    providers_called: ["cache"],
    provider_used: ["cache"],
    generated_queries_called: [],
    generated_queries_called_count: 0,
    baidu_qianfan_status: "cached",
    rate_limited: false,
    cache_hit: true,
    cache_source: cacheSource,
    cache_ttl_minutes: DISCOVERY_CACHE_TTL_MINUTES,
    raw_results_count: 0,
    raw_results_sample: [],
    candidates: {
      ...(cached.diagnostics?.candidates || {}),
      created: 0,
      reused: reusedCandidates,
    },
    jobs: {
      ...(cached.diagnostics?.jobs || {}),
      created: 0,
      updated: 0,
      reused: reusedJobs,
    },
  };
  cached.raw_results_count = 0;
  cached.raw_results_sample = [];
  cached.searchedAt = new Date().toISOString();
  cached.latencyMs = 0;
  return cached;
}

async function writeCacheHitDiscoveryRun(
  service: SupabaseClient,
  {
    query,
    city,
    company,
    jobType,
    response,
    startedAt,
  }: {
    query: string;
    city: string;
    company: string;
    jobType: string;
    response: any;
    startedAt: number;
  },
) {
  const reusedCandidates = Number(
    maxNumericValue([
      response.source_candidates_reused,
      response.candidates_found,
      response.candidatesFound,
      response.official_candidates_count,
      response.diagnostics?.candidates?.reused,
      response.diagnostics?.candidates?.found,
      response.sample_candidates?.length,
    ]),
  );
  const reusedJobs = Number(
    maxNumericValue([
      response.jobs_reused,
      response.total,
      response.parsed_jobs,
      response.jobs?.length,
      response.diagnostics?.jobs?.reused,
      response.diagnostics?.jobs?.parsed,
    ]),
  );
  const status = response.status || (reusedCandidates > 0 ? "partial_success" : "failed");
  const failureReason =
    response.failure_reason ||
    response.diagnostics?.failure_reason ||
    (reusedCandidates > 0 ? "candidates_pending" : "provider_no_results");
  const diagnostics = {
    ...(response.diagnostics || {}),
    cache_hit: true,
    cache_source: response.cache_source || "cache",
    cached_discovery_run_id: response.discovery_run_id || null,
    generated_queries_called: [],
    generated_queries_called_count: 0,
    providers_called: ["cache"],
    provider_used: ["cache"],
    provider_http_status: null,
    rate_limited: false,
    latency_ms: Date.now() - startedAt,
  };

  const cacheRun = await writeDiscoveryRun(service, {
    query,
    city,
    company,
    jobType,
    status,
    candidatesFound: reusedCandidates,
    candidatesParsed: Number(response.candidatesParsed || response.diagnostics?.candidates?.parsed || 0),
    candidatesPending: Number(
      response.pending_candidates ??
        response.candidatesPending ??
        response.diagnostics?.candidates?.pending ??
        reusedCandidates,
    ),
    jobsCreated: 0,
    jobsUpdated: 0,
    blockedCount: Number(response.blocked_results || response.blockedCount || 0),
    errorMessage: response.error_message || null,
    providerName: "cache",
    providerQuery: null,
    rawResultsCount: 0,
    officialCandidatesCount: reusedCandidates,
    sourceCandidatesCreated: 0,
    sourceCandidatesReused: reusedCandidates,
    rateLimited: false,
    cacheHit: true,
    failureReason,
    diagnostics: {
      ...diagnostics,
      jobs: {
        ...(diagnostics.jobs || {}),
        reused: reusedJobs,
        created: 0,
        updated: 0,
      },
    },
  });

  if (cacheRun.id) {
    response.discovery_run_id = cacheRun.id;
    response.cache_discovery_run_id = cacheRun.id;
    response.diagnostics = {
      ...diagnostics,
      discovery_run_id: cacheRun.id,
      jobs: {
        ...(diagnostics.jobs || {}),
        reused: reusedJobs,
        created: 0,
        updated: 0,
      },
    };
  }
}

function maxNumericValue(values: unknown[]) {
  return Math.max(
    0,
    ...values
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value) && value >= 0),
  );
}

function applyNullableSupabaseFilter(builder: any, column: string, value: string) {
  return value ? builder.eq(column, value) : builder.is(column, null);
}

function filterCandidatesByProviderQuery(candidates: any[], calledQueries: string[]) {
  const expectedQueries = new Set((calledQueries || []).filter(Boolean));
  if (expectedQueries.size === 0) return candidates;

  return candidates.filter((candidate) => {
    const reason = parseCandidateReason(candidate?.reason);
    const providerQuery = reason?.provider_query;
    return providerQuery ? expectedQueries.has(providerQuery) : true;
  });
}

function parseCandidateReason(reason: unknown) {
  if (!reason || typeof reason !== "string") return null;
  try {
    return JSON.parse(reason);
  } catch {
    return null;
  }
}

async function collectDiscoveryUrls(
  queries: string[],
  errors: string[],
) {
  const urls: string[] = [];
  const seen = new Set<string>();
  const providers: ProviderDiagnostic[] = [];
  const providerResultByUrl = new Map<string, any>();
  const calledQueries = queries.slice(0, 1);

  const baiduQianfan = await runBaiduQianfanProvider(calledQueries);
  providers.push(baiduQianfan.diagnostic);
  baiduQianfan.errors.forEach((error) => errors.push(error));
  addProviderResults(baiduQianfan.diagnostic, urls, seen, providerResultByUrl);

  providers.push(createSkippedProviderDiagnostic("duckduckgo_html", calledQueries));
  providers.push(createSkippedProviderDiagnostic("bing_html", calledQueries));

  return { urls, providers, providerResultByUrl, calledQueries };
}

function createSkippedProviderDiagnostic(providerName: string, queries: string[]) {
  return createProviderDiagnostic({
    providerName,
    query: queries.join(" | "),
    status: "skipped",
    httpStatus: null,
    rawResultsCount: 0,
    extractedUrlsCount: 0,
    results: [],
    error: null,
    diagnostics: { reason: "baidu_qianfan_primary_provider" },
  }) as ProviderDiagnostic;
}

async function runBaiduQianfanProvider(queries: string[]) {
  const urls: string[] = [];
  const errors: string[] = [];
  const queryDiagnostics = [];
  const now = Date.now();

  if (now < baiduQianfanRateLimitedUntil) {
    const retryAt = new Date(baiduQianfanRateLimitedUntil).toISOString();
    const error = `Baidu Qianfan rate limited; cooldown active until ${retryAt}`;
    errors.push(error);
    queryDiagnostics.push(
      createProviderDiagnostic({
        providerName: "baidu_qianfan_web_search",
        query: queries[0] || "",
        status: "provider_failed",
        httpStatus: 429,
        rawResultsCount: 0,
        extractedUrlsCount: 0,
        results: [],
        error,
        diagnostics: {
          configured: Boolean(process.env.BAIDU_QIANFAN_API_KEY),
          rate_limited: true,
          cooldown_active: true,
          retry_at: retryAt,
        },
      }),
    );

    return {
      urls,
      errors,
      diagnostic: aggregateProviderDiagnostics(
        "baidu_qianfan_web_search",
        queries,
        queryDiagnostics,
        errors,
      ),
    };
  }

  for (let index = 0; index < queries.length; index += 1) {
    const query = queries[index];
    const result = await searchBaiduQianfanWeb({
      query,
      apiKey: process.env.BAIDU_QIANFAN_API_KEY,
      timeoutMs: DISCOVERY_TIMEOUT,
    });
    queryDiagnostics.push(result.diagnostic);
    result.errors.forEach((error: string) => errors.push(error));
    urls.push(...result.urls);
    if (isRateLimitedDiagnostic(result.diagnostic)) {
      baiduQianfanRateLimitedUntil =
        Date.now() + BAIDU_QIANFAN_RATE_LIMIT_COOLDOWN_MINUTES * 60 * 1000;
      break;
    }
    if (BAIDU_QIANFAN_QUERY_DELAY_MS > 0 && index < queries.length - 1) {
      await sleep(BAIDU_QIANFAN_QUERY_DELAY_MS);
    }
  }

  return {
    urls,
    errors,
    diagnostic: aggregateProviderDiagnostics(
      "baidu_qianfan_web_search",
      queries,
      queryDiagnostics,
      errors,
    ),
  };
}

async function runBingWebSearchApiProvider(queries: string[]) {
  const apiKey = process.env.BING_SEARCH_API_KEY || process.env.AZURE_BING_SEARCH_API_KEY;
  const endpoint = process.env.BING_SEARCH_ENDPOINT || "https://api.bing.microsoft.com/v7.0/search";
  const providerName = "bing_web_search_api";

  if (!apiKey) {
    const error = "Missing BING_SEARCH_API_KEY; falling back to HTML search providers.";
    const queryDiagnostics = queries.map((query) =>
      createProviderDiagnostic({
        providerName,
        query,
        status: "provider_failed",
        httpStatus: null,
        rawResultsCount: 0,
        extractedUrlsCount: 0,
        error,
        diagnostics: { configured: false },
      }),
    );
    return {
      urls: [],
      errors: [error],
      diagnostic: createProviderDiagnostic({
        providerName,
        query: queries.join(" | "),
        status: "provider_failed",
        httpStatus: null,
        rawResultsCount: 0,
        extractedUrlsCount: 0,
        error,
        diagnostics: { configured: false, queries: queryDiagnostics },
      }) as ProviderDiagnostic,
    };
  }

  const urls: string[] = [];
  const errors: string[] = [];
  const queryDiagnostics = [];

  for (const query of queries) {
    try {
      const url = new URL(endpoint);
      url.searchParams.set("q", query);
      url.searchParams.set("mkt", "zh-CN");
      url.searchParams.set("count", "10");

      const response = await fetch(url, {
        method: "GET",
        headers: {
          Accept: "application/json",
          "Ocp-Apim-Subscription-Key": apiKey,
          "User-Agent": USER_AGENT,
        },
        signal: AbortSignal.timeout(DISCOVERY_TIMEOUT),
      });
      const httpStatus = response.status;
      const data = response.ok ? await response.json() : null;
      const rows = Array.isArray(data?.webPages?.value) ? data.webPages.value : [];
      const extracted = rows.map((row: any) => row?.url).filter(Boolean);
      const error =
        response.ok ? null : `${providerName} returned HTTP ${httpStatus} for "${query}"`;
      if (error) errors.push(error);
      urls.push(...extracted);
      queryDiagnostics.push(
        createProviderDiagnostic({
          providerName,
          query,
          status:
            extracted.length > 0
              ? response.ok
                ? "success"
                : "partial_success"
              : response.ok
                ? "no_results_found"
                : "provider_failed",
          httpStatus,
          rawResultsCount: rows.length,
          extractedUrlsCount: extracted.length,
          error,
          diagnostics: { configured: true },
        }),
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const errorMessage = `${providerName} failed for "${query}": ${message}`;
      errors.push(errorMessage);
      queryDiagnostics.push(
        createProviderDiagnostic({
          providerName,
          query,
          status: "provider_failed",
          httpStatus: null,
          rawResultsCount: 0,
          extractedUrlsCount: 0,
          error: errorMessage,
          diagnostics: { configured: true },
        }),
      );
    }
  }

  return {
    urls,
    errors,
    diagnostic: aggregateProviderDiagnostics(providerName, queries, queryDiagnostics, errors),
  };
}

async function runSearchProvider({
  providerName,
  queries,
  fetchHtml,
  extractUrls,
  countRawResults,
}: {
  providerName: string;
  queries: string[];
  fetchHtml: (query: string) => Promise<{ html: string; httpStatus: number }>;
  extractUrls: (html: string) => string[];
  countRawResults: (html: string) => number;
}) {
  const urls: string[] = [];
  const errors: string[] = [];
  const queryDiagnostics = [];

  for (const query of queries) {
    try {
      const { html, httpStatus } = await fetchHtml(query);
      const extracted = extractUrls(html);
      const rawResults = countRawResults(html);
      const error =
        httpStatus === 200 ? null : `${providerName} returned HTTP ${httpStatus} for "${query}"`;
      if (error) errors.push(error);

      queryDiagnostics.push(createProviderDiagnostic({
        providerName,
        query,
        status:
          extracted.length > 0
            ? httpStatus === 200
              ? "success"
              : "partial_success"
            : httpStatus === 200
              ? "no_results_found"
              : "provider_failed",
        httpStatus,
        rawResultsCount: rawResults,
      extractedUrlsCount: extracted.length,
      results: extracted.map((url) => ({ title: "", url, snippet: "" })),
      error,
      diagnostics: {},
    }));
      urls.push(...extracted);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const errorMessage = `${providerName} failed for "${query}": ${message}`;
      errors.push(errorMessage);
      queryDiagnostics.push(createProviderDiagnostic({
        providerName,
        query,
        status: "provider_failed",
        httpStatus: null,
        rawResultsCount: 0,
        extractedUrlsCount: 0,
        error: errorMessage,
        diagnostics: {},
      }));
    }
  }

  return {
    urls,
    errors,
    diagnostic: aggregateProviderDiagnostics(providerName, queries, queryDiagnostics, errors),
  };
}

function aggregateProviderDiagnostics(
  providerName: string,
  queries: string[],
  queryDiagnostics: any[],
  errors: string[],
) {
  const extractedCount = queryDiagnostics.reduce(
    (sum, item) => sum + (item.extracted_urls_count || 0),
    0,
  );
  const rawResultsCount = queryDiagnostics.reduce(
    (sum, item) => sum + (item.raw_results_count || 0),
    0,
  );
  const failedCount = queryDiagnostics.filter(
    (query) => query.status === "provider_failed",
  ).length;
  const rateLimitedDiagnostic = queryDiagnostics.find((query) => isRateLimitedDiagnostic(query));
  const results = dedupeProviderResults(
    queryDiagnostics.flatMap((query) =>
      (query.results || []).map((result: any) => ({
        ...result,
        provider_name: query.provider_name || providerName,
        provider_query: query.query,
      })),
    ),
  );

  return createProviderDiagnostic({
    providerName,
    query: queries.join(" | "),
    status:
      extractedCount > 0
        ? failedCount > 0
          ? "partial_success"
          : "success"
        : failedCount > 0
          ? "provider_failed"
          : "no_results_found",
    httpStatus:
      rateLimitedDiagnostic?.http_status ||
      queryDiagnostics.find((query) => query.http_status !== null)?.http_status ||
      null,
    rawResultsCount,
    extractedUrlsCount: extractedCount,
    results,
    error: Array.from(new Set(errors)).join("\n") || null,
    diagnostics: {
      queries: queryDiagnostics,
      rate_limited: Boolean(rateLimitedDiagnostic),
    },
  }) as ProviderDiagnostic;
}

function isRateLimitedDiagnostic(diagnostic: any) {
  return Boolean(
    diagnostic?.diagnostics?.rate_limited ||
      diagnostic?.http_status === 429 ||
      /429|rate\s*limit|too many requests|限流|频率/i.test(String(diagnostic?.error || "")),
  );
}

function getProviderStatus(providers: ProviderDiagnostic[], providerName: string) {
  return (
    providers.find((provider) => (provider.provider_name || provider.name) === providerName)
      ?.status || "skipped"
  );
}

function getProviderHttpStatus(providers: ProviderDiagnostic[], providerName: string) {
  const provider = providers.find(
    (item) => (item.provider_name || item.name) === providerName,
  );
  return provider?.http_status ?? null;
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function dedupeProviderResults(results: any[]) {
  const deduped = [];
  const seen = new Set<string>();
  for (const result of results) {
    if (!result?.url || seen.has(result.url)) continue;
    seen.add(result.url);
    deduped.push(result);
  }
  return deduped;
}

function addProviderResults(
  diagnostic: ProviderDiagnostic,
  target: string[],
  seen: Set<string>,
  providerResultByUrl: Map<string, any>,
) {
  for (const result of diagnostic.results || []) {
    if (!result.url) continue;
    if (!providerResultByUrl.has(result.url)) {
      providerResultByUrl.set(result.url, {
        provider_name: diagnostic.provider_name || diagnostic.name,
        provider_query: (result as any).provider_query || diagnostic.query,
        title: result.title || "",
        url: result.url,
        snippet: result.snippet || "",
      });
    }
    if (seen.has(result.url)) continue;
    seen.add(result.url);
    target.push(result.url);
  }
}

async function fetchDuckDuckGoHtml(query: string) {
  const url = new URL("https://duckduckgo.com/html/");
  url.searchParams.set("q", query);
  return fetchSearchHtml(url);
}

async function fetchBingHtml(query: string) {
  const url = new URL("https://www.bing.com/search");
  url.searchParams.set("q", query);
  return fetchSearchHtml(url);
}

async function fetchSearchHtml(url: URL) {
  const response = await fetch(url, {
    method: "GET",
    headers: {
      Accept: "text/html,application/xhtml+xml",
      "Accept-Language": "en-US,en;q=0.9",
      "User-Agent": USER_AGENT,
    },
    signal: AbortSignal.timeout(DISCOVERY_TIMEOUT),
  });

  return {
    html: await response.text(),
    httpStatus: response.status,
  };
}

function countDuckDuckGoRawResults(html: string) {
  const text = String(html || "");
  const resultAnchors = text.match(/class=(["'])[^"']*\bresult__a\b[^"']*\1/gi);
  if (resultAnchors) return resultAnchors.length;
  return extractDuckDuckGoResultUrls(text).length;
}

function countBingRawResults(html: string) {
  const text = String(html || "");
  const resultBlocks = text.match(
    /<li[^>]*class=(["'])[^"']*\bb_algo\b[^"']*\1[\s\S]*?<\/li>/gi,
  );
  if (resultBlocks) return resultBlocks.length;
  return extractBingResultUrls(text).length;
}

async function parseSupportedBoard({
  service,
  candidate,
  query,
  city,
  jobType,
  limit,
  errors,
}: {
  service: SupabaseClient;
  candidate: DiscoveryCandidate;
  query: string;
  city: string;
  jobType: string;
  limit: number;
  errors: string[];
}) {
  try {
    const parserName = candidate.parserName || candidate.detectedPlatform;
    const source = {
      provider: parserName,
      company: candidate.company || candidate.slug || "Unknown",
      slug: candidate.slug,
      url: candidate.url,
    };
    const rawJobs = await searchParserLive({
      parserName,
      source,
      candidate,
      query,
      city,
      jobType,
      limit,
    });
    const filtered = filterJobsByQueryAndCity(rawJobs, query, city)
      .filter((job: any) => matchesJobType(job, jobType))
      .filter((job: any) => isHighQualityJdUrl(job.jd_url, parserName))
      .slice(0, limit);

    const upserted: UpsertedJob[] = [];
    for (const job of filtered) {
      const quality = await validateJobQualityGate(job, { sourceName: parserName });
      if (!quality.ok) {
        errors.push(
          `${parserName}:${candidate.slug || candidate.company || "unknown"} quality gate rejected ${job.jd_url}: ${quality.reason}`,
        );
        continue;
      }
      const result = await upsertDiscoveredJob(service, job);
      if (result) {
        upserted.push({
          ...result,
          row: {
            ...result.row,
            __quality: quality,
          },
        });
      }
    }
    return upserted;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    errors.push(`${candidate.detectedPlatform}:${candidate.slug} parser failed: ${message}`);
    return [];
  }
}

async function searchParserLive({
  parserName,
  source,
  candidate,
  query,
  city,
  jobType,
  limit,
}: {
  parserName: string;
  source: any;
  candidate: DiscoveryCandidate;
  query: string;
  city: string;
  jobType: string;
  limit: number;
}) {
  if (parserName === "greenhouse") return searchGreenhouseLive(source);
  if (parserName === "lever") return searchLeverLive(source);
  if (parserName === "baidu") return searchBaiduLive(query, limit);
  if (parserName === "jd") return searchJdLive(query, limit);
  if (parserName === "apple") return searchAppleLive(query, limit);
  if (parserName === "generic_official_detail") {
    return searchGenericOfficialDetail(candidate, query, city, jobType);
  }
  if (parserName === "moka") return searchMokaLive(candidate);
  return [];
}

async function searchGenericOfficialDetail(
  candidate: DiscoveryCandidate,
  query: string,
  city: string,
  jobType: string,
) {
  const response = await fetch(candidate.url, {
    method: "GET",
    headers: {
      Accept: "text/html,application/xhtml+xml",
      "Accept-Language": "zh-CN,en;q=0.9",
      "User-Agent": USER_AGENT,
    },
    signal: AbortSignal.timeout(ATS_TIMEOUT),
  });
  if (!response.ok) return [];

  const html = await response.text();
  const job = extractGenericOfficialDetailJob({
    url: candidate.url,
    html,
    classification: candidate,
    providerResult: candidate.providerResult || null,
    query,
    city,
    jobType,
  });

  return job ? [job] : [];
}

async function searchMokaLive(candidate: DiscoveryCandidate) {
  const board = await getMokaBoardInfo(candidate);
  if (board.slug) {
    const apiUrl = new URL(
      `https://api.mokahr.com/api-platform/v1/jobs/${encodeURIComponent(board.slug)}`,
    );
    apiUrl.searchParams.set("mode", board.mode);
    if (board.siteId) apiUrl.searchParams.set("siteId", board.siteId);

    const apiResponse = await fetch(apiUrl, {
      method: "GET",
      headers: {
        Accept: "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,en;q=0.9",
        Referer: board.boardUrl,
        "User-Agent": USER_AGENT,
      },
      signal: AbortSignal.timeout(ATS_TIMEOUT),
    });

    if (apiResponse.ok) {
      const data = await apiResponse.json();
      if (Array.isArray(data?.jobs)) {
        return extractMokaJobsFromRows({
          url: board.boardUrl,
          rows: data.jobs,
          classification: {
            ...candidate,
            company: candidate.company || board.slug,
          },
        });
      }
    }
  }

  const response = await fetch(candidate.url, {
    method: "GET",
    headers: {
      Accept: "text/html,application/xhtml+xml",
      "Accept-Language": "zh-CN,en;q=0.9",
      "User-Agent": USER_AGENT,
    },
    signal: AbortSignal.timeout(ATS_TIMEOUT),
  });
  if (!response.ok) return [];

  const html = await response.text();
  return extractMokaJobsFromHtml({
    url: candidate.url,
    html,
    classification: candidate,
  });
}

async function getMokaBoardInfo(candidate: DiscoveryCandidate) {
  const parsed = new URL(candidate.url);
  const segments = parsed.pathname.split("/").filter(Boolean);
  const mode = segments[0]?.includes("social") || segments[0] === "apply"
    ? "social"
    : "campus";
  const slug = candidate.slug || segments[1] || segments[0] || "";
  let siteId = segments.find((segment, index) => index > 1 && /^\d+$/.test(segment)) || "";

  if (!siteId) {
    try {
      const response = await fetch(candidate.url, {
        method: "GET",
        redirect: "manual",
        headers: {
          Accept: "text/html,application/xhtml+xml",
          "Accept-Language": "zh-CN,en;q=0.9",
          "User-Agent": USER_AGENT,
        },
        signal: AbortSignal.timeout(ATS_TIMEOUT),
      });
      const location = response.headers.get("location");
      if (location) {
        const redirected = new URL(location, candidate.url);
        const redirectedSegments = redirected.pathname.split("/").filter(Boolean);
        siteId =
          redirectedSegments.find((segment, index) => index > 1 && /^\d+$/.test(segment)) ||
          siteId;
      }
    } catch {}
  }

  return {
    mode,
    slug,
    siteId,
    boardUrl: buildMokaBoardUrl({
      originalUrl: candidate.url,
      slug,
      mode,
      siteId,
    }),
  };
}

async function searchAppleLive(query: string, limit: number) {
  const jobs = [];
  const expandedTerms = expandSearchTerms(query)
    .filter((term: string) => term && term.length <= 32)
    .slice(0, 4);
  const queries = Array.from(new Set([query, ...expandedTerms]));

  for (const q of queries.slice(0, 2)) {
    const url = new URL(APPLE_SEARCH_URL);
    url.searchParams.set("search", q);
    url.searchParams.set("location", "china-CHN");

    const response = await fetch(url, {
      method: "GET",
      headers: {
        Accept: "text/html,application/xhtml+xml",
        "User-Agent": USER_AGENT,
      },
      signal: AbortSignal.timeout(ATS_TIMEOUT),
    });
    if (!response.ok) continue;

    const html = await response.text();
    const rows = extractAppleSearchResultsFromHtml(html);
    for (const row of rows.slice(0, limit)) {
      jobs.push(formatAppleSearchResult(row));
    }
    if (jobs.length >= limit) break;
  }

  return jobs.slice(0, limit);
}

async function searchBaiduLive(query: string, limit: number) {
  const url = new URL(BAIDU_SEARCH_URL);
  url.searchParams.set("search", query);

  const response = await fetch(url, {
    method: "GET",
    headers: {
      Accept: "text/html,application/xhtml+xml",
      "Accept-Language": "zh-CN,en;q=0.9",
      "User-Agent": USER_AGENT,
    },
    signal: AbortSignal.timeout(ATS_TIMEOUT),
  });
  if (!response.ok) return [];

  const html = await response.text();
  const rows = extractBaiduInitialDataFromHtml(html);
  return rows.slice(0, limit).map((row: any) => formatBaiduSearchResult(row, "SOCIAL"));
}

async function searchJdLive(query: string, limit: number) {
  const response = await fetch(JD_JOB_LIST_URL, {
    method: "POST",
    headers: {
      Accept: "application/json, text/javascript, */*; q=0.01",
      "Accept-Language": "zh-CN,en;q=0.9",
      "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
      Origin: "https://zhaopin.jd.com",
      Referer: JD_REFERER_URL,
      "User-Agent": USER_AGENT,
      "X-Requested-With": "XMLHttpRequest",
    },
    body: new URLSearchParams({
      pageIndex: "1",
      pageSize: String(Math.min(limit, 30)),
      workCityJson: "[]",
      jobTypeJson: "[]",
      jobSearch: query,
      depTypeJson: "[]",
    }),
    signal: AbortSignal.timeout(ATS_TIMEOUT),
  });
  if (!response.ok) return [];

  const data = await response.json();
  return Array.isArray(data)
    ? data.slice(0, limit).map((row: any) => formatJdJob(row))
    : [];
}

async function searchGreenhouseLive(source: any) {
  const url = new URL(
    `https://boards-api.greenhouse.io/v1/boards/${source.slug}/jobs`,
  );
  url.searchParams.set("content", "true");

  const response = await fetch(url, {
    method: "GET",
    headers: {
      Accept: "application/json",
      "User-Agent": USER_AGENT,
    },
    signal: AbortSignal.timeout(ATS_TIMEOUT),
  });

  if (!response.ok) return [];

  const data = await response.json();
  return Array.isArray(data.jobs)
    ? data.jobs.map((row: any) => formatGreenhouseJob(row, source))
    : [];
}

async function searchLeverLive(source: any) {
  const url = new URL(`https://api.lever.co/v0/postings/${source.slug}`);
  url.searchParams.set("mode", "json");

  const response = await fetch(url, {
    method: "GET",
    headers: {
      Accept: "application/json",
      "User-Agent": USER_AGENT,
    },
    signal: AbortSignal.timeout(ATS_TIMEOUT),
  });

  if (!response.ok) return [];

  const data = await response.json();
  return Array.isArray(data)
    ? data.map((row: any) => formatLeverPosting(row, source))
    : [];
}

async function upsertDiscoveredJob(service: SupabaseClient, job: any) {
  const now = new Date().toISOString();
  const { data: existing, error: existingError } = await service
    .from("jobs")
    .select("*")
    .eq("jd_url", job.jd_url)
    .limit(1)
    .maybeSingle();

  if (existingError) {
    console.error("[discovery] job lookup failed", existingError.message);
    return null;
  }

  if (existing) {
    const { data, error } = await service
      .from("jobs")
      .update({
        company: job.company,
        title: job.title,
        location: job.location,
        job_type: job.job_type,
        summary: job.summary,
        apply_url: job.apply_url,
        salary_text: job.salary_text,
        posted_at: job.posted_at,
        content_hash: job.content_hash,
        status: "active",
        last_seen_at: now,
      })
      .eq("id", existing.id)
      .select("*")
      .single();

    if (error) {
      console.error("[discovery] job update failed", error.message);
      return { row: existing, action: "updated" as const };
    }
    return { row: data, action: "updated" as const };
  }

  const { data, error } = await service
    .from("jobs")
    .insert({
      ...job,
      source_id: null,
      first_seen_at: now,
      last_seen_at: now,
      status: "active",
    })
    .select("*")
    .single();

  if (error) {
    console.error("[discovery] job insert failed", error.message);
    return null;
  }

  return { row: data, action: "created" as const };
}

async function upsertSourceCandidate(
  service: SupabaseClient,
  {
    query,
    fallbackCompany,
    fallbackTitle,
    url,
    classification,
    providerResult,
    status,
  }: {
    query: string;
    fallbackCompany: string | null;
    fallbackTitle: string;
    url: string;
    classification: DiscoveryClassification;
    providerResult: any;
    status: "pending" | "parsed" | "failed";
  },
) {
  const { data: existing } = await service
    .from("source_candidates")
    .select("id")
    .eq("query", query)
    .eq("url", url)
    .limit(1)
    .maybeSingle();

  const record = buildSourceCandidateRecord({
    query,
    fallbackCompany,
    fallbackTitle,
    url,
    classification,
    providerResult,
    status,
  });
  const { data, error } = await service
    .from("source_candidates")
    .upsert(
      record,
      { onConflict: "query,url" },
    )
    .select("id")
    .single();

  if (error) {
    console.error("[discovery] source candidate upsert failed", error.message);
    return null;
  }

  return { ...data, created: !existing };
}

async function updateSourceCandidateStatus(
  service: SupabaseClient,
  candidate: DiscoveryCandidate,
  status: "parsed" | "failed",
  reason: string,
) {
  if (!candidate.id) return;

  const { data: existing } = await service
    .from("source_candidates")
    .select("reason")
    .eq("id", candidate.id)
    .maybeSingle();
  const nextReason = buildSourceCandidateStatusReason({
    previousReason: existing?.reason,
    status,
    statusReason: reason,
  });

  const { error } = await service
    .from("source_candidates")
    .update({ status, reason: nextReason })
    .eq("id", candidate.id);

  if (error) {
    console.error("[discovery] source candidate status update failed", error.message);
  }
}

async function writeDiscoveryRun(
  service: SupabaseClient,
  report: {
    query: string;
    city: string;
    company: string;
    jobType: string;
    status: string;
    candidatesFound: number;
    candidatesParsed: number;
    candidatesPending: number;
    jobsCreated: number;
    jobsUpdated: number;
    blockedCount: number;
    errorMessage: string | null;
    providerName?: string | null;
    providerQuery?: string | null;
    rawResultsCount?: number;
    officialCandidatesCount?: number;
    sourceCandidatesCreated?: number;
    sourceCandidatesReused?: number;
    rateLimited?: boolean;
    cacheHit?: boolean;
    failureReason?: string | null;
    diagnostics?: Record<string, unknown>;
  },
) {
  const baseRecord = {
    query: report.query,
    city: report.city || null,
    company: report.company || null,
    job_type: report.jobType || null,
    status: report.status,
    candidates_found: report.candidatesFound,
    candidates_parsed: report.candidatesParsed,
    candidates_pending: report.candidatesPending,
    jobs_created: report.jobsCreated,
    jobs_updated: report.jobsUpdated,
    blocked_count: report.blockedCount,
    error_message: report.errorMessage,
  };
  const extendedRecord = {
    ...baseRecord,
    provider_name: report.providerName || null,
    provider_query: report.providerQuery || null,
    raw_results_count: report.rawResultsCount || 0,
    official_candidates_count: report.officialCandidatesCount || 0,
    source_candidates_created: report.sourceCandidatesCreated || 0,
    source_candidates_reused: report.sourceCandidatesReused || 0,
    rate_limited: Boolean(report.rateLimited),
    cache_hit: Boolean(report.cacheHit),
    failure_reason: report.failureReason || null,
    diagnostics: report.diagnostics || null,
  };

  const { data, error } = await service
    .from("discovery_runs")
    .insert(extendedRecord)
    .select("id")
    .single();

  if (error) {
    const retry = await service
      .from("discovery_runs")
      .insert(baseRecord)
      .select("id")
      .single();
    if (retry.error) {
      console.error("[discovery] discovery run insert failed", retry.error.message);
      return { id: null, error: retry.error.message };
    }
    return {
      id: retry.data?.id || null,
      error: null,
      diagnosticsPersisted: false,
      schemaFallback: error.message,
    };
  }

  return { id: data?.id || null, error: null, diagnosticsPersisted: true };
}

function matchesJobType(job: any, jobType: string) {
  const needle = String(jobType || "").trim().toLowerCase();
  if (!needle || needle === "all") return true;

  return [job.title, job.job_type, job.summary]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
    .includes(needle);
}

function createServiceClient() {
  const supabaseUrl = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !serviceKey) {
    throw new Error("Missing Supabase service credentials");
  }

  return createClient(supabaseUrl, serviceKey, {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
    },
  });
}

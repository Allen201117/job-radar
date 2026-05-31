import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { createServerSupabase } from "@/lib/auth";
import liveSearch from "@/lib/live-search";

const {
  LIVE_ATS_SOURCES,
  extractAppleSearchResultsFromHtml,
  extractBaiduInitialDataFromHtml,
  filterJobsByQueryAndCity,
  formatAppleSearchResult,
  formatBaiduSearchResult,
  formatJdJob,
  formatGreenhouseJob,
  formatLeverPosting,
  expandSearchTerms,
  isHighQualityJdUrl,
  mergeJobsByUrl,
  toApiJob,
} = liveSearch;

const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36";
const APPLE_SEARCH_URL = "https://jobs.apple.com/en-us/search";
const BAIDU_SEARCH_URL = "https://talent.baidu.com/jobs/social-list";
const JD_JOB_LIST_URL = "https://zhaopin.jd.com/web/job/job_list";
const JD_REFERER_URL = "https://zhaopin.jd.com/web/job/job_info_list/3";
const TIMEOUT = 15000;
const ATS_TIMEOUT = 8000;
const ATS_SOURCE_LIMIT = Number(process.env.LIVE_ATS_SOURCE_LIMIT || 3);

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
  const limit = Math.min(Number(params.get("limit") || 30), 60);
  const functionFilter = params.get("function") || "all";
  const city = (params.get("city") || "").trim();
  const startTime = Date.now();

  const [cached, liveBaidu, liveJd] = await Promise.all([
    fetchCached(supabase, query, functionFilter, city, limit),
    query ? fetchBaiduLiveAndUpsert(query, limit, city) : Promise.resolve([]),
    query ? fetchJdLiveAndUpsert(query, limit, city) : Promise.resolve([]),
  ]);

  const live = interleaveJobsBySource([...liveBaidu, ...liveJd]);
  const merged = mergeJobsByUrl(
    query ? live : cached,
    query ? cached : live,
  ).slice(0, limit);
  const jobsCreated = live.filter((job: any) => job.__action === "created").length;
  const jobsUpdated = live.filter((job: any) => job.__action === "updated").length;
  const knownSourceCount = [liveBaidu, liveJd].filter((jobs) => jobs.length > 0).length;

  return NextResponse.json({
    ok: true,
    mode: "known_sources_refresh",
    jobs: merged.map((job: any) => toApiJob(job, job.__live ? 55 : 35)),
    total: merged.length,
    knownSources: knownSourceCount,
    chinaKnownSources: knownSourceCount,
    refreshedSources: [
      { adapter_name: "baidu", jobs_returned: liveBaidu.length },
      { adapter_name: "jd", jobs_returned: liveJd.length },
    ],
    jobs_created: jobsCreated,
    jobs_updated: jobsUpdated,
    atsSupplementSources: 0,
    priority: "仅刷新已确认中国官方源；动态扩源请使用 /api/discovery",
    searchedAt: new Date().toISOString(),
    latencyMs: Date.now() - startTime,
  });
}

async function fetchCached(
  supabase: Awaited<ReturnType<typeof createServerSupabase>>,
  query: string,
  func: string,
  city: string,
  limit: number,
) {
  let builder = supabase
    .from("jobs")
    .select("*")
    .eq("status", "active")
    .order("first_seen_at", { ascending: false })
    .limit(limit);

  if (query) {
    const q = escapePostgrestLike(query);
    builder = builder.or(
      `title.ilike.%${q}%,company.ilike.%${q}%,location.ilike.%${q}%,summary.ilike.%${q}%`,
    );
  }
  if (func !== "all") {
    builder = builder.ilike("job_type", `%${escapePostgrestLike(func)}%`);
  }
  if (city) {
    builder = builder.ilike("location", `%${escapePostgrestLike(city)}%`);
  }

  const { data, error } = await builder;
  if (error) {
    console.error("[search] cached query failed", error.message);
    return [];
  }
  return data || [];
}

async function fetchAppleLiveAndUpsert(query: string, limit: number, city: string) {
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    console.error("[search] missing SUPABASE_SERVICE_ROLE_KEY");
    return [];
  }

  const source = await getSource("apple");
  if (!source) return [];

  const rawJobs = await searchAppleLive(query, limit);
  const validJobs = filterJobsByQueryAndCity(rawJobs, query, city).filter((job: any) =>
    isHighQualityJdUrl(job.jd_url, "apple"),
  );

  const upserted = [];
  for (const job of validJobs) {
    const row = await upsertLiveJob({ ...job, source_id: source.id });
    if (row) upserted.push({ ...row, __live: true, __sourceKey: "apple" });
  }

  return upserted;
}

async function fetchBaiduLiveAndUpsert(query: string, limit: number, city: string) {
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    console.error("[search] missing SUPABASE_SERVICE_ROLE_KEY");
    return [];
  }

  const source = await getSource("baidu");
  if (!source) return [];

  const rawJobs = await searchBaiduLive(query, limit);
  const validJobs = filterJobsByQueryAndCity(rawJobs, query, city).filter((job: any) =>
    isHighQualityJdUrl(job.jd_url, "baidu"),
  );

  const upserted = [];
  for (const job of validJobs) {
    const row = await upsertLiveJob({ ...job, source_id: source.id });
    if (row) upserted.push({ ...row, __live: true, __sourceKey: "baidu" });
  }

  return upserted;
}

async function fetchJdLiveAndUpsert(query: string, limit: number, city: string) {
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    console.error("[search] missing SUPABASE_SERVICE_ROLE_KEY");
    return [];
  }

  const source = await getSource("jd");
  if (!source) return [];

  const rawJobs = await searchJdLive(query, limit);
  const validJobs = filterJobsByQueryAndCity(rawJobs, query, city).filter((job: any) =>
    isHighQualityJdUrl(job.jd_url, "jd"),
  );

  const upserted = [];
  for (const job of validJobs) {
    const row = await upsertLiveJob({ ...job, source_id: source.id });
    if (row) upserted.push({ ...row, __live: true, __sourceKey: "jd" });
  }

  return upserted;
}

async function fetchGenericAtsLiveAndUpsert(query: string, limit: number, city: string) {
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    console.error("[search] missing SUPABASE_SERVICE_ROLE_KEY");
    return [];
  }

  const selectedSources = LIVE_ATS_SOURCES.slice(0, ATS_SOURCE_LIMIT);
  const perSourceLimit = Math.max(2, Math.ceil(limit / 8));

  const settled = await Promise.allSettled(
    selectedSources.map((source: any) =>
      fetchOneAtsSourceAndUpsert(source, query, city, perSourceLimit),
    ),
  );

  return settled
    .flatMap((result) => (result.status === "fulfilled" ? result.value : []))
    .slice(0, limit);
}

async function fetchOneAtsSourceAndUpsert(
  source: any,
  query: string,
  city: string,
  limit: number,
) {
  const rawJobs =
    source.provider === "greenhouse"
      ? await searchGreenhouseLive(source)
      : await searchLeverLive(source);
  const filtered = filterJobsByQueryAndCity(rawJobs, query, city)
    .filter((job: any) => isHighQualityJdUrl(job.jd_url, source.provider))
    .slice(0, limit);

  if (filtered.length === 0) return [];

  const sourceRow = await getApprovedLiveSource(source);
  if (!sourceRow) return [];

  const upserted = [];
  for (const job of filtered) {
    const row = await upsertLiveJob({ ...job, source_id: sourceRow.id });
    if (row) {
      upserted.push({
        ...row,
        __live: true,
        __sourceKey: `${source.provider}:${source.slug}`,
      });
    }
  }

  return upserted;
}

async function searchAppleLive(query: string, limit: number) {
  const jobs = [];
  const expandedTerms = expandSearchTerms(query)
    .filter((term: string) => term && term.length <= 32)
    .slice(0, 4);
  const queries = Array.from(new Set([query, ...expandedTerms]));

  for (const q of queries.slice(0, 2)) {
    try {
      const url = new URL(APPLE_SEARCH_URL);
      url.searchParams.set("search", q);
      url.searchParams.set("location", "china-CHN");

      const response = await fetch(url, {
        method: "GET",
        headers: {
          Accept: "text/html,application/xhtml+xml",
          "User-Agent": USER_AGENT,
        },
        signal: AbortSignal.timeout(TIMEOUT),
      });

      if (!response.ok) continue;

      const html = await response.text();
      const rows = extractAppleSearchResultsFromHtml(html);
      for (const row of rows.slice(0, limit)) {
        jobs.push(formatAppleSearchResult(row));
      }
    } catch (error) {
      console.error("[search] apple live query failed", error);
      continue;
    }
    if (jobs.length >= limit) break;
  }

  return jobs.slice(0, limit);
}

async function searchGreenhouseLive(source: any) {
  const url = new URL(
    `https://boards-api.greenhouse.io/v1/boards/${source.slug}/jobs`,
  );
  url.searchParams.set("content", "true");

  try {
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
  } catch (error) {
    console.error(`[search] greenhouse ${source.slug} query failed`, error);
    return [];
  }
}

async function searchLeverLive(source: any) {
  const url = new URL(`https://api.lever.co/v0/postings/${source.slug}`);
  url.searchParams.set("mode", "json");

  try {
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
  } catch (error) {
    console.error(`[search] lever ${source.slug} query failed`, error);
    return [];
  }
}

async function searchBaiduLive(query: string, limit: number) {
  const url = new URL(BAIDU_SEARCH_URL);
  url.searchParams.set("search", query);

  try {
    const response = await fetch(url, {
      method: "GET",
      headers: {
        Accept: "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,en;q=0.9",
        "User-Agent": USER_AGENT,
      },
      signal: AbortSignal.timeout(TIMEOUT),
    });

    if (!response.ok) return [];

    const html = await response.text();
    const rows = extractBaiduInitialDataFromHtml(html);
    return rows
      .slice(0, limit)
      .map((row: any) => formatBaiduSearchResult(row, "SOCIAL"));
  } catch (error) {
    console.error("[search] baidu live query failed", error);
    return [];
  }
}

async function searchJdLive(query: string, limit: number) {
  try {
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
      signal: AbortSignal.timeout(TIMEOUT),
    });

    if (!response.ok) return [];

    const data = await response.json();
    return Array.isArray(data)
      ? data.slice(0, limit).map((row: any) => formatJdJob(row))
      : [];
  } catch (error) {
    console.error("[search] jd live query failed", error);
    return [];
  }
}

async function getApprovedLiveSource(source: any) {
  const service = createServiceClient();
  const sourceUrl =
    source.provider === "greenhouse"
      ? `https://boards-api.greenhouse.io/v1/boards/${source.slug}/jobs`
      : `https://api.lever.co/v0/postings/${source.slug}`;

  const { data: existing, error: existingError } = await service
    .from("sources")
    .select("id")
    .eq("company", source.company)
    .eq("source_url", sourceUrl)
    .eq("enabled", true)
    .limit(1)
    .maybeSingle();

  if (existingError) {
    console.error(`[search] ${source.company} source lookup failed`, existingError.message);
    return null;
  }

  if (existing) return existing;

  console.warn(
    `[search] skipped ${source.company}; ${source.provider} board is not an approved enabled source`,
  );
  return null;
}

async function getSource(adapterName: string) {
  const service = createServiceClient();
  const { data, error } = await service
    .from("sources")
    .select("id")
    .eq("adapter_name", adapterName)
    .eq("enabled", true)
    .single();

  if (error) {
    console.error(`[search] ${adapterName} source lookup failed`, error.message);
    return null;
  }
  return data;
}

async function upsertLiveJob(job: any) {
  const service = createServiceClient();
  const now = new Date().toISOString();
  const { data: existing, error: existingError } = await service
    .from("jobs")
    .select("*")
    .eq("source_id", job.source_id)
    .eq("jd_url", job.jd_url)
    .maybeSingle();

  if (existingError) {
    console.error("[search] live lookup failed", existingError.message);
    return null;
  }

  if (existing) {
    const { data, error } = await service
      .from("jobs")
      .update({
        title: job.title,
        company: job.company,
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
      console.error("[search] live update failed", error.message);
      return { ...existing, __action: "updated" };
    }
    return { ...data, __action: "updated" };
  }

  const { data, error } = await service
    .from("jobs")
    .insert({
      ...job,
      first_seen_at: now,
      last_seen_at: now,
      status: "active",
    })
    .select("*")
    .single();

  if (error) {
    console.error("[search] live insert failed", error.message);
    return null;
  }
  return { ...data, __action: "created" };
}

function createServiceClient() {
  return createClient(
    process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    {
      auth: {
        autoRefreshToken: false,
        persistSession: false,
      },
    },
  );
}

function escapePostgrestLike(value: string) {
  return value.replace(/[%,()]/g, " ").trim();
}

function interleaveJobsBySource(jobs: any[]) {
  const groups = new Map<string, any[]>();
  for (const job of jobs) {
    const key = job.__sourceKey || job.company || "unknown";
    const group = groups.get(key) || [];
    group.push(job);
    groups.set(key, group);
  }

  const merged = [];
  while (groups.size > 0) {
    for (const [key, group] of Array.from(groups.entries())) {
      const next = group.shift();
      if (next) merged.push(next);
      if (group.length === 0) groups.delete(key);
    }
  }

  return merged;
}

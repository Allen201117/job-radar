import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { createServerSupabase } from "@/lib/auth";
import liveSearch from "@/lib/live-search";
import { jobsStoreEnabled } from "@/lib/jobs-store/read";
import { upsertJob as upsertJobToStore } from "@/lib/jobs-store/write";

const {
  selectRelevantSources,
  resolveInlineAtsSource,
  keepForChinaRadar,
  extractAppleSearchResultsFromHtml,
  extractBaiduInitialDataFromHtml,
  filterJobsByQueryAndCity,
  excludeJobs,
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
// on-demand 内联刷新的 greenhouse/lever 源上限（每个源一次 JSON 拉全量，再客户端按 query/city 收窄）。
const INLINE_ATS_CAP = Number(process.env.LIVE_ATS_SOURCE_LIMIT || 8);

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
  const company = (params.get("company") || "").trim();
  const startTime = Date.now();

  // 偏好底层逻辑（核心产品原则 #2）：手动筛选项优先；未填的城市默认用用户已保存偏好；
  // 排除词始终生效——命中 exclude_keywords 的岗位一律不入选（与 crawler 同口径，剔除发生在 upsert 前）。
  const prefs = await loadUserPreferences(supabase, user.id);
  const effCity = city || prefs.city;
  const excludeKeywords = prefs.excludeKeywords;

  // P2：on-demand 定向刷新已知源——除 baidu/jd/apple 三个专用源外，再按用户筛选项从真实 sources 表
  // 挑相关的 greenhouse/lever 外企 ATS（公开 JSON API，Vercel serverless 秒回），只放行在华岗位。
  // 全部并行，Promise.all 不叠加墙钟；各自 在华过滤 + query/city 过滤 + 排除词剔除 + 质量门 + upsert。
  const [cached, liveBaidu, liveJd, liveApple, liveAts] = await Promise.all([
    fetchCached(supabase, query, functionFilter, effCity, limit),
    query ? fetchBaiduLiveAndUpsert(query, limit, effCity, excludeKeywords) : Promise.resolve([]),
    query ? fetchJdLiveAndUpsert(query, limit, effCity, excludeKeywords) : Promise.resolve([]),
    query ? fetchAppleLiveAndUpsert(query, limit, effCity, excludeKeywords) : Promise.resolve([]),
    query
      ? fetchRelevantAtsLiveAndUpsert(query, effCity, company, limit, excludeKeywords)
      : Promise.resolve([]),
  ]);

  const live = interleaveJobsBySource([...liveBaidu, ...liveJd, ...liveApple, ...liveAts]);
  // 缓存命中也走与 live / 看板同一套智能匹配器（词分级 + 组合意图），
  // 消除 fetchCached 宽 SQL（summary.ilike）把正文含关键词的无关岗也带回的泄漏。
  const cachedFiltered = query ? filterJobsByQueryAndCity(cached, query, "") : cached;
  const merged = mergeJobsByUrl(
    query ? live : cachedFiltered,
    query ? cachedFiltered : live,
  ).slice(0, limit);
  const jobsCreated = live.filter((job: any) => job.__action === "created").length;
  const jobsUpdated = live.filter((job: any) => job.__action === "updated").length;
  const atsSourceCount = new Set(liveAts.map((job: any) => job.__sourceKey)).size;
  const knownSourceCount =
    [liveBaidu, liveJd, liveApple].filter((jobs) => jobs.length > 0).length + atsSourceCount;

  return NextResponse.json({
    ok: true,
    mode: "known_sources_refresh",
    jobs: merged.map((job: any) => toApiJob(job, job.__live ? 55 : 35)),
    total: merged.length,
    knownSources: knownSourceCount,
    chinaKnownSources: [liveBaidu, liveJd, liveApple].filter((jobs) => jobs.length > 0).length,
    refreshedSources: [
      { adapter_name: "baidu", jobs_returned: liveBaidu.length },
      { adapter_name: "jd", jobs_returned: liveJd.length },
      { adapter_name: "apple", jobs_returned: liveApple.length },
      { adapter_name: "greenhouse+lever", jobs_returned: liveAts.length },
    ],
    jobs_created: jobsCreated,
    jobs_updated: jobsUpdated,
    atsSupplementSources: atsSourceCount,
    priority: "刷新已确认中国官方源 + 按筛选项命中的在华外企 ATS；浏览器源动态扩源请用 /api/discovery",
    searchedAt: new Date().toISOString(),
    latencyMs: Date.now() - startTime,
  });
}

// 读取用户已保存的求职偏好：城市（手动未填时的默认精准范围）+ 排除词（始终生效）。
// 与 app/api/discovery/dispatch/route.ts 同源，确保同步刷新与异步发现的偏好口径一致。
async function loadUserPreferences(
  supabase: Awaited<ReturnType<typeof createServerSupabase>>,
  userId: string,
): Promise<{ city: string; excludeKeywords: string[] }> {
  const empty = { city: "", excludeKeywords: [] as string[] };
  try {
    const [cpRes, upRes] = await Promise.all([
      supabase
        .from("candidate_profiles")
        .select("target_locations")
        .eq("user_id", userId)
        .maybeSingle(),
      supabase
        .from("user_preferences")
        .select("target_locations, exclude_keywords")
        .eq("user_id", userId)
        .maybeSingle(),
    ]);
    const cp = cpRes.data as any;
    const up = upRes.data as any;
    const clean = (arr: any): string[] =>
      Array.from(
        new Set(
          (Array.isArray(arr) ? arr : [])
            .map((s: any) => String(s || "").trim())
            .filter(Boolean),
        ),
      );
    const cities = clean([...(cp?.target_locations || []), ...(up?.target_locations || [])]);
    return { city: cities[0] || "", excludeKeywords: clean(up?.exclude_keywords) };
  } catch (err) {
    console.error("[search] 读取用户偏好失败", (err as Error).message);
    return empty;
  }
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

async function fetchAppleLiveAndUpsert(
  query: string,
  limit: number,
  city: string,
  exclude: string[] = [],
) {
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    console.error("[search] missing SUPABASE_SERVICE_ROLE_KEY");
    return [];
  }

  const source = await getSource("apple");
  if (!source) return [];

  const rawJobs = await searchAppleLive(query, limit);
  const validJobs = excludeJobs(
    filterJobsByQueryAndCity(rawJobs, query, city),
    exclude,
  ).filter((job: any) => isHighQualityJdUrl(job.jd_url, "apple"));

  const upserted = [];
  for (const job of validJobs) {
    const row = await upsertLiveJob({ ...job, source_id: source.id });
    if (row) upserted.push({ ...row, __live: true, __sourceKey: "apple" });
  }

  return upserted;
}

async function fetchBaiduLiveAndUpsert(
  query: string,
  limit: number,
  city: string,
  exclude: string[] = [],
) {
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    console.error("[search] missing SUPABASE_SERVICE_ROLE_KEY");
    return [];
  }

  const source = await getSource("baidu");
  if (!source) return [];

  const rawJobs = await searchBaiduLive(query, limit);
  const validJobs = excludeJobs(
    filterJobsByQueryAndCity(rawJobs, query, city),
    exclude,
  ).filter((job: any) => isHighQualityJdUrl(job.jd_url, "baidu"));

  const upserted = [];
  for (const job of validJobs) {
    const row = await upsertLiveJob({ ...job, source_id: source.id });
    if (row) upserted.push({ ...row, __live: true, __sourceKey: "baidu" });
  }

  return upserted;
}

async function fetchJdLiveAndUpsert(
  query: string,
  limit: number,
  city: string,
  exclude: string[] = [],
) {
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    console.error("[search] missing SUPABASE_SERVICE_ROLE_KEY");
    return [];
  }

  const source = await getSource("jd");
  if (!source) return [];

  const rawJobs = await searchJdLive(query, limit);
  const validJobs = excludeJobs(
    filterJobsByQueryAndCity(rawJobs, query, city),
    exclude,
  ).filter((job: any) => isHighQualityJdUrl(job.jd_url, "jd"));

  const upserted = [];
  for (const job of validJobs) {
    const row = await upsertLiveJob({ ...job, source_id: source.id });
    if (row) upserted.push({ ...row, __live: true, __sourceKey: "jd" });
  }

  return upserted;
}

// on-demand 定向刷新已知外企 ATS：从真实 sources 表取 enabled 的 greenhouse/lever，
// 按用户筛选项挑相关源，每源直连公开 JSON API 拉全量 → 在华过滤 → query/city 过滤 → 质量门 → upsert。
async function fetchRelevantAtsLiveAndUpsert(
  query: string,
  city: string,
  company: string,
  limit: number,
  exclude: string[] = [],
) {
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    console.error("[search] missing SUPABASE_SERVICE_ROLE_KEY");
    return [];
  }

  const service = createServiceClient();
  const { data: sources, error } = await service
    .from("sources")
    .select("id, company, adapter_name, source_url, industry, segment")
    .eq("enabled", true)
    .in("adapter_name", ["greenhouse", "lever"]);
  if (error) {
    console.error("[search] ats sources lookup failed", error.message);
    return [];
  }
  if (!sources || sources.length === 0) return [];

  // 按用户筛选项（公司/关键词→行业/segment）挑相关源，cap 控制单次 on-demand 的外呼数。
  const selected = selectRelevantSources(
    sources,
    { keyword: query, company },
    { cap: INLINE_ATS_CAP },
  );
  const perSourceLimit = Math.max(3, Math.ceil(limit / 3));

  const settled = await Promise.allSettled(
    selected.map(({ source }: any) =>
      fetchOneAtsSourceAndUpsert(source, query, city, perSourceLimit, exclude),
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
  exclude: string[] = [],
) {
  const resolved = resolveInlineAtsSource(source);
  if (!resolved) return [];

  const rawJobs = await searchAtsLiveByUrl(resolved, source);
  const filtered = excludeJobs(filterJobsByQueryAndCity(rawJobs, query, city), exclude)
    .filter((job: any) => isHighQualityJdUrl(job.jd_url, resolved.provider))
    .slice(0, limit);

  if (filtered.length === 0) return [];

  const upserted = [];
  for (const job of filtered) {
    const row = await upsertLiveJob({ ...job, source_id: source.id });
    if (row) {
      upserted.push({
        ...row,
        __live: true,
        __sourceKey: `${resolved.provider}:${source.company}`,
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

// 直连真实源 source_url（已由 resolveInlineAtsSource 校验 host + 补 content/mode 参数）。
// 在华过滤放在原始行级别（greenhouse=location.name / lever=categories.location），逐字对齐 crawler，
// 避免格式化后 normalizeChinaLocation 改写地点导致与抓取端口径漂移。
async function searchAtsLiveByUrl(
  resolved: { provider: string; url: string },
  source: any,
) {
  try {
    const response = await fetch(resolved.url, {
      method: "GET",
      headers: {
        Accept: "application/json",
        "User-Agent": USER_AGENT,
      },
      signal: AbortSignal.timeout(ATS_TIMEOUT),
    });

    if (!response.ok) return [];

    const data = await response.json();
    if (resolved.provider === "greenhouse") {
      const rows = Array.isArray(data?.jobs) ? data.jobs : [];
      return rows
        .filter((row: any) => keepForChinaRadar(row?.location?.name))
        .map((row: any) => formatGreenhouseJob(row, source));
    }
    const rows = Array.isArray(data) ? data : [];
    return rows
      .filter((row: any) => keepForChinaRadar(row?.categories?.location))
      .map((row: any) => formatLeverPosting(row, source));
  } catch (error) {
    console.error(`[search] ats ${source.company} fetch failed`, error);
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
  // jobs 已迁自建香港 PG：配了 env 写香港库（canonical upsert，复活语义同爬虫）。写入端不回退 Supabase
  //（避免写孤儿数据）；本岗失败返回 null，不炸整轮刷新。job 带真实 source_id（getSource），原样传入。
  if (jobsStoreEnabled()) {
    try {
      const r = await upsertJobToStore(job);
      return r ? { ...r.row, __action: r.action } : null;
    } catch (e: any) {
      console.error("[search] HK upsert failed", e?.message || e);
      return null;
    }
  }
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

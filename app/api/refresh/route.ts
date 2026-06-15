import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { createServerSupabase } from "@/lib/auth";
import discoveryDispatch from "@/lib/discovery-dispatch";
import { resolveRefreshScope } from "@/lib/refresh-scope";
import { evaluateRefreshThrottle } from "@/lib/refresh-throttle";
import { jobMatchesFilters, DEFAULT_FILTERS } from "@/lib/job-filter";
import { CITY_ALIASES, normalizeChinaCity } from "@/lib/china-keyword-expansion";

export const runtime = "nodejs";

const { buildWorkflowDispatchRequest, resolveDispatchConfig, isDispatchAccepted } =
  discoveryDispatch as any;

const DISPATCH_TIMEOUT_MS = 20000; // 抬到 20s（原 discovery 10s 偏紧），靠读时 staleness 兜底卡死
const SCOPE_CAP = Number(process.env.REFRESH_SCOPE_CAP || 25);
// 主动刷新不设每日/冷却上限（用户诉求：别限制主动爬取次数）。默认 0=关闭冷却；
// 并发由下方 in-flight「reuse」幂等守卫挡住（同一时刻只跑一个，避免重复 dispatch），不算次数限制。
// 真要重新限流可设 REFRESH_COOLDOWN_MIN>0。外部限流（GitHub/百度）仍如实反馈给用户。
const COOLDOWN_MS = Number(process.env.REFRESH_COOLDOWN_MIN || 0) * 60 * 1000;

/**
 * POST /api/refresh —— on-demand「刷新公司库」（全异步·流式）。
 *
 * 解析 scope（当前筛选 + 偏好兜底，cap N）→ 节流/幂等 → 插 discovery_runs(mode=company_refresh,
 * diagnostics={source_ids,filters,click_time}) → workflow_dispatch → 返回 run_id；
 * 前端用 /api/discovery/status?runId= 轮询，结果按 produced_jd_urls 流式回灌。
 */
export async function POST(request: NextRequest) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    return NextResponse.json(
      { ok: false, error: "Missing SUPABASE_SERVICE_ROLE_KEY", mode: "company_refresh" },
      { status: 500 },
    );
  }

  let body: any = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  const filters = {
    company: String(body.company || "").trim(),
    keyword: String(body.keyword || body.query || "").trim(),
    city: String(body.city || "").trim(),
    jobType: String(body.jobType || body.job_type || "").trim(),
  };

  const service = createServiceClient();
  const prefs = await loadRefreshPrefs(service, user.id);

  // 1) 解析 scope（手动筛选优先；未配用偏好兜底；按相关性 + 每平台多样性 cap 前 N）。
  const { data: sources, error: srcErr } = await service
    .from("sources")
    .select("id, company, adapter_name, source_url, industry, segment, enabled, notes")
    .eq("enabled", true);
  if (srcErr) {
    return NextResponse.json(
      { ok: false, error: "sources_lookup_failed", detail: srcErr.message, mode: "company_refresh" },
      { status: 500 },
    );
  }

  // 「已收录公司」最强相关信号：用 jobs 表反查「真有命中 城市+关键词(+类型) 岗位」的公司，
  // 交给 scope 置顶重爬。修根因：metadata/notes 选源选不到真有该岗位的公司（深圳·产品经理曾 0/33 命中）。
  // 仅在「无显式公司筛选 + 有城市」时启用：显式公司时尊重用户点名；无城市时全表 ilike 太重。
  const { provenCompanies, provenExactCompanies } = await resolveProvenCompanies(
    service,
    filters.company ? "" : filters.city || prefs.city,
    filters.keyword,
    filters.jobType || prefs.experienceStage,
  );

  const scope = resolveRefreshScope(
    {
      filters,
      preferences: {
        targetCompanies: prefs.targetCompanies,
        targetKeywords: prefs.targetKeywords,
        targetRoles: prefs.targetRoles,
        excludeKeywords: prefs.excludeKeywords,
        city: prefs.city, // 未填城市时用偏好城市兜底（海外意图判定 + notes 城市信号）
      },
      provenCompanies,
      provenExactCompanies,
      sources: sources || [],
    },
    { cap: SCOPE_CAP },
  );

  // scope 内 distinct 公司数（透明化「本轮抓了多少家公司」用，区别于 source 行数）。
  const scopeCompanies = new Set(
    (scope.sources || []).map((s: any) => String(s.company || "").trim()).filter(Boolean),
  ).size;

  if (scope.sourceIds.length === 0) {
    return NextResponse.json(
      {
        ok: false,
        error: "empty_scope",
        mode: "company_refresh",
        hint: "未命中任何公司源——请在筛选器里填公司/关键词，或在偏好里设置目标公司。",
      },
      { status: 422 },
    );
  }

  // 2) 节流 / 幂等：查该用户近 10min 的 company_refresh run。
  const sinceIso = new Date(Date.now() - COOLDOWN_MS).toISOString();
  const { data: recentRuns } = await service
    .from("discovery_runs")
    .select("id, status, created_at, started_at")
    .eq("user_id", user.id)
    .eq("mode", "company_refresh")
    .gte("created_at", sinceIso)
    .order("created_at", { ascending: false })
    .limit(10);

  const decision = evaluateRefreshThrottle(recentRuns || [], Date.now(), { cooldownMs: COOLDOWN_MS });
  if (decision.action === "reuse") {
    return NextResponse.json({
      ok: true,
      mode: "company_refresh",
      reused: true,
      run_id: decision.run.id,
      status: decision.run.status,
      poll: `/api/discovery/status?runId=${decision.run.id}`,
      message: "已有一次刷新在进行中，复用它。",
    });
  }
  if (decision.action === "cooldown") {
    return NextResponse.json(
      {
        ok: false,
        error: "cooldown_active",
        mode: "company_refresh",
        retry_after_sec: decision.retryAfterSec,
        hint: `刚刷过，${decision.retryAfterSec} 秒后可再刷。`,
      },
      { status: 429, headers: { "Retry-After": String(decision.retryAfterSec) } },
    );
  }

  // 3) 有效过滤条件（手动优先、未配用偏好；exclude 始终生效）—— 存进 diagnostics 供 CI 逐岗过滤。
  const effFilters = {
    query: filters.keyword,
    city: filters.city || prefs.city,
    job_type: filters.jobType || prefs.experienceStage,
    exclude: prefs.excludeKeywords,
  };

  const config = resolveDispatchConfig(process.env);
  if (!config.configured) {
    return NextResponse.json(
      {
        ok: false,
        error: "dispatch_not_configured",
        missing_env: config.missing,
        mode: "company_refresh",
        hint: "Set GITHUB_DISPATCH_TOKEN (actions:write PAT) + GITHUB_DISPATCH_REPO (owner/name).",
      },
      { status: 503 },
    );
  }

  // 4) 插 queued 行（scope + filters + click_time 存 diagnostics，CI 按 run_id 读取）。
  const runId = randomUUID();
  const startedAt = new Date().toISOString();
  const { error: insertError } = await service.from("discovery_runs").insert({
    id: runId,
    user_id: user.id,
    mode: "company_refresh",
    status: "queued",
    provider_name: "company_refresh",
    // discovery_runs.query 是 NOT NULL（005）；company_refresh 关键词可空 → 用公司/占位兜底。
    query: filters.keyword || filters.company || "公司库刷新",
    city: effFilters.city || null,
    job_type: effFilters.job_type || null,
    started_at: startedAt,
    candidates_found: 0,
    jobs_created: 0,
    jobs_updated: 0,
    failure_reason: null,
    diagnostics: {
      source_ids: scope.sourceIds,
      scope_companies: scopeCompanies, // 本轮抓取的 distinct 公司数（前端透明化漏斗）
      filters: effFilters,
      click_time: startedAt,
      progress: { done: 0, total: scope.sourceIds.length },
      produced_jd_urls: [],
    },
  });
  if (insertError) {
    return NextResponse.json(
      {
        ok: false,
        error: "run_insert_failed",
        detail: insertError.message,
        mode: "company_refresh",
        hint: "Apply migration 009_discovery_async_runs.sql (queued/running + diagnostics jsonb).",
      },
      { status: 500 },
    );
  }

  // 5) workflow_dispatch（只传 mode + run_id；scope 太长走 diagnostics）。失败则标 run failed。
  let dispatchHttpStatus: number | null = null;
  let dispatchError: string | null = null;
  try {
    const req = buildWorkflowDispatchRequest({
      slug: config.slug,
      workflowFile: config.workflowFile,
      ref: config.ref,
      token: config.token,
      inputs: { mode: "company_refresh", run_id: runId },
    });
    const resp = await fetch(req.url, {
      method: req.method,
      headers: req.headers,
      body: req.body,
      signal: AbortSignal.timeout(DISPATCH_TIMEOUT_MS),
    });
    dispatchHttpStatus = resp.status;
    if (!isDispatchAccepted(resp.status)) {
      const text = await resp.text().catch(() => "");
      // 抹掉任何 Bearer token 再入错误信息（minor 修：日志不泄露凭证）。
      const safe = text.replace(/Bearer\s+[A-Za-z0-9._-]+/gi, "Bearer ***").slice(0, 300);
      dispatchError = `GitHub workflow_dispatch HTTP ${resp.status}${safe ? `: ${safe}` : ""}`;
    }
  } catch (err) {
    dispatchError = err instanceof Error ? err.message : String(err);
  }

  if (dispatchError) {
    // 平台限流（GitHub Actions 403/429）单独标记，如实反馈给用户（区别于一般触发失败）。
    const rateLimited = dispatchHttpStatus === 403 || dispatchHttpStatus === 429;
    const errorCode = rateLimited ? "dispatch_rate_limited" : "dispatch_failed";
    await service
      .from("discovery_runs")
      .update({
        status: "failed",
        failure_reason: errorCode,
        error_message: dispatchError.slice(0, 1000),
        finished_at: new Date().toISOString(),
      })
      .eq("id", runId);
    return NextResponse.json(
      {
        ok: false,
        error: errorCode,
        detail: dispatchError,
        run_id: runId,
        mode: "company_refresh",
        ...(rateLimited
          ? { hint: "GitHub Actions 平台限流（非每日额度），稍等几分钟再试。" }
          : {}),
      },
      { status: rateLimited ? 429 : 502 },
    );
  }

  return NextResponse.json({
    ok: true,
    mode: "company_refresh",
    run_id: runId,
    status: "queued",
    scope: {
      total: scope.sourceIds.length,
      matched: scope.matchedCount,
      dropped: scope.droppedCount,
    },
    preference_defaults: {
      city_from_pref: !filters.city && Boolean(effFilters.city),
      job_type_from_pref: !filters.jobType && Boolean(effFilters.job_type),
      companies_from_pref: !filters.company && prefs.targetCompanies.length > 0,
      exclude_count: prefs.excludeKeywords.length,
    },
    poll: `/api/discovery/status?runId=${runId}`,
    estimated_seconds: { min: 60, max: 300 },
    started_at: startedAt,
  });
}

function createServiceClient(): SupabaseClient {
  const supabaseUrl = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !serviceKey) {
    throw new Error("Missing Supabase service credentials");
  }
  return createClient(supabaseUrl, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

// 反查「已收录里真有命中该筛选岗位」的公司：按城市 ilike 取候选，再用与本地搜索同一份匹配器
// （jobMatchesFilters）按 城市+关键词(+类型) 精筛 → distinct 公司名。空城市/空关键词时返回空（不全表扫）。
async function resolveProvenCompanies(
  service: SupabaseClient,
  city: string,
  keyword: string,
  jobType: string,
): Promise<{ provenCompanies: string[]; provenExactCompanies: string[] }> {
  const empty = { provenCompanies: [], provenExactCompanies: [] };
  if (!city || !keyword) return empty;
  try {
    // 城市预筛用全部别名（中/英/带"市"后缀），避免漏掉 location 存英文（如 "Shenzhen"）的源——
    // 否则像 OPPO 这种英文地点的雇主会被预筛挡在 proven 之外。逐岗精筛仍由 jobMatchesFilters 兜底。
    const norm = normalizeChinaCity(city);
    const aliasKeys = Array.from((CITY_ALIASES as Map<string, string>).entries())
      .filter(([, v]) => v === norm)
      .map(([k]) => k);
    const aliases = Array.from(
      new Set(
        [city, norm, ...aliasKeys]
          .map((s) => String(s || "").trim())
          .filter((s) => s.length >= 2),
      ),
    );
    const orFilter = aliases.map((a) => `location.ilike.%${a}%`).join(",");
    const { data: cityJobs } = await service
      .from("jobs")
      // 注意：jobs 表无 hidden_reason 列（它是读时按 job_actions 派生的）；选它会整条 query 报错→proven 静默失效。
      .select("company, title, location, job_type, summary, salary_text, first_seen_at, posted_at")
      .eq("status", "active")
      .or(orFilter)
      .limit(8000);
    const baseF = { ...DEFAULT_FILTERS, city, keyword } as any;
    const exactF = { ...baseF, jobType } as any;
    const rel = new Set<string>();
    const exact = new Set<string>();
    for (const j of cityJobs || []) {
      const company = String((j as any).company || "").trim();
      if (!company) continue;
      if (jobMatchesFilters(j as any, baseF)) rel.add(company);
      if (jobType && jobMatchesFilters(j as any, exactF)) exact.add(company);
    }
    return { provenCompanies: Array.from(rel), provenExactCompanies: Array.from(exact) };
  } catch (err) {
    console.error("[refresh] proven-company lookup failed", (err as Error).message);
    return empty;
  }
}

// 读用户偏好：scope 用 target_companies/keywords/roles；逐岗过滤兜底用 city/experience_stage/exclude。
async function loadRefreshPrefs(
  service: SupabaseClient,
  userId: string,
): Promise<{
  targetCompanies: string[];
  targetKeywords: string[];
  targetRoles: string[];
  city: string;
  experienceStage: string;
  excludeKeywords: string[];
}> {
  const empty = {
    targetCompanies: [] as string[],
    targetKeywords: [] as string[],
    targetRoles: [] as string[],
    city: "",
    experienceStage: "",
    excludeKeywords: [] as string[],
  };
  try {
    const [cpRes, upRes] = await Promise.all([
      service
        .from("candidate_profiles")
        .select("experience_stage, target_locations, target_roles")
        .eq("user_id", userId)
        .maybeSingle(),
      service
        .from("user_preferences")
        .select("target_companies, target_keywords, target_roles, target_locations, exclude_keywords")
        .eq("user_id", userId)
        .maybeSingle(),
    ]);
    const cp = (cpRes.data || {}) as any;
    const up = (upRes.data || {}) as any;
    const clean = (arr: any): string[] =>
      Array.from(
        new Set((Array.isArray(arr) ? arr : []).map((s: any) => String(s || "").trim()).filter(Boolean)),
      );
    const cities = clean([...(cp.target_locations || []), ...(up.target_locations || [])]);
    return {
      targetCompanies: clean(up.target_companies),
      targetKeywords: clean(up.target_keywords),
      targetRoles: clean([...(up.target_roles || []), ...(cp.target_roles || [])]),
      city: cities[0] || "",
      experienceStage: String(cp.experience_stage || "").trim(),
      excludeKeywords: clean(up.exclude_keywords),
    };
  } catch (err) {
    console.error("[refresh] 读取用户偏好失败", (err as Error).message);
    return empty;
  }
}

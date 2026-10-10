import { NextRequest, NextResponse, after } from "next/server";
import { randomUUID } from "crypto";
import { requireAdmin, requireUser } from "@/lib/apiAuth";
import discoveryDispatch from "@/lib/discovery-dispatch";
import insightEnrichNow from "@/lib/insight-enrich-now";
import { createServiceClient } from "@/lib/supabaseService";
import { findCompanyProfile } from "@/lib/insight-match";
import { evaluateInsight, resolveInsightFailure } from "@/lib/insight-verification";
import {
  INSIGHT_DIMENSIONS,
  DATA_LAYER_ORIGINS_FILTER,
  ITEM_COLUMNS,
  emptyDimensions,
  groupGatedInsights,
} from "@/lib/insight-bundle";
import { deriveCompanyInsights } from "@/lib/insight-derive";
import {
  aggregateFirstParty,
  FIRST_PARTY_MIN_COUNT,
  type FirstPartyAggregate,
  type InsightSubmissionRow,
} from "@/lib/insight-submission";
import { jobsStoreEnabled, activeJobsByCompanies } from "@/lib/jobs-store/read";
import { getCachedCompanyProfilesLight } from "@/lib/insight-availability-cache";
import type {
  CompanyProfile,
  InsightDimension,
  InsightItem,
  InsightSource,
  Job,
} from "@/lib/types";

export const runtime = "nodejs";
// 现查派发在响应之后跑（after），其中调 GitHub 最长等 10s。不显式给时限的话，函数可能在
// 「台账已写 queued、还没回写 failed」之间被杀，那家公司会被冷却期白挡 6 小时。
export const maxDuration = 30;
// 派生统计最多取这么多行在招岗位做样本；取满了就说明真实数量不止这些（见 deriveHiring 的 sampleCapped）。
const DERIVE_JOB_CAP = 3000;

const { buildWorkflowDispatchRequest, resolveDispatchConfig, isDispatchAccepted } =
  discoveryDispatch as any;
const {
  buildInsightEnrichRunRecord,
  buildInsightWorkflowInputs,
  evaluateInsightEnrichDispatch,
} = insightEnrichNow as any;

function numberEnv(name: string, fallback: number): number {
  const value = Number(process.env[name]);
  return Number.isFinite(value) ? value : fallback;
}

const ENRICH_NOW_COOLDOWN_HOURS = numberEnv("INSIGHT_ENRICH_COOLDOWN_HOURS", 6);
const ENRICH_NOW_HOURLY_CAP = numberEnv("INSIGHT_ENRICH_HOURLY_CAP", 5);
const FIRST_PARTY_DISPLAY_MIN_COUNT = numberEnv(
  "INSIGHT_FIRST_PARTY_MIN_COUNT",
  FIRST_PARTY_MIN_COUNT,
);
const ENRICH_DISPATCH_TIMEOUT_MS = 10000;

export async function GET(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;
  const { supabase, user } = auth;

  const company = (request.nextUrl.searchParams.get("company") || "").trim();
  if (!company) {
    return NextResponse.json(
      { ok: false, error: "missing_company" },
      { status: 400 },
    );
  }

  // 1) 取全部公司画像，归一化匹配（苹果↔Apple、字节↔ByteDance）。可能无画像（95% 公司）。
  //    走跨实例缓存（10min），轻列足够 findCompanyProfile + deriveCompanyInsights 使用。
  let profilesLight: CompanyProfile[];
  try {
    profilesLight = (await getCachedCompanyProfilesLight()) as CompanyProfile[];
  } catch (profileError: any) {
    console.error("[insights] 读取 company_profiles 失败", profileError?.message);
    return NextResponse.json(
      { ok: false, error: profileError?.message || "profiles_unavailable" },
      { status: 500 },
    );
  }
  const profileLight = findCompanyProfile(profilesLight, company);

  // 2) 匹配候选 = 查询词 + 画像 company/aliases。只用轻列里就有的两项，
  //    这样下面五路读都不必排在「补取画像全列」后面。
  const candidates = Array.from(
    new Set(
      profileLight
        ? [profileLight.company, ...(profileLight.aliases || []), company]
        : [company],
    ),
  );

  // 3) 五路读互不依赖 → 并行。
  //    2026-10-10 线上实测（单请求、同一条链路上 /api/preferences 基线 ~600ms）：改前这五步 + 现查派发
  //    是一条接一条串行的，腾讯 2.26 / 2.34s、美团 3.26s、小红书 2.39s —— 用户每点开一次洞察抽屉都要
  //    对着骨架屏等 2~3 秒。函数在香港、Supabase 在悉尼，每多串一步就多一趟跨区往返。
  const today = new Date().toISOString().slice(0, 10);
  const [fullProfileRes, jobRows, itemsRes, firstParty, recruitmentCycles] = await Promise.all([
    // 轻列只够做归一化匹配；抽屉还要展示 industry / founded_year / hq_location 等全列字段，
    // 命中后按 id 单行补取（主键读），未命中或读失败则回落轻列。
    profileLight
      ? supabase.from("company_profiles").select("*").eq("id", profileLight.id).maybeSingle()
      : null,
    // Tier1 派生用的在招岗位（无需画像，保证 100% 覆盖）；限 active，cap 3000 行足够代表性聚合。
    loadDeriveJobRows(supabase, candidates),
    // 存储型洞察（仅当有画像）。
    profileLight
      ? supabase
          .from("insight_items")
          .select(`${ITEM_COLUMNS}, insight_item_sources(insight_sources(*))`)
          .eq("company_id", profileLight.id)
          .eq("status", "active")
          // 排除「数据层」两类 origin（共用 lib/insight-bundle 的 DATA_LAYER_ORIGINS）：
          //   · derived —— 抽屉的第一方数字由下面 deriveCompanyInsights 读时算，而
          //     crawler/bu_signals.py 把同一批指标物化进 insight_items 供洞察库按指标筛选。
          //     两者同源，不排除就会在抽屉里把同一个数字显示两遍。
          //     （后续若把抽屉也切成读物化行，删掉这一行并同时去掉读时派生，不要两者都留。）
          //   · official_filing —— 年报数字（在职员工数 / 技术人员占比 / 人均薪酬）。
          //     2026-09-07 创始人定：这类「年报里写着、自己查一下就有」的不算信息差，
          //     洞察库撤了之后抽屉也一并撤，两个面共用同一份名单。
          .not("origin", "in", DATA_LAYER_ORIGINS_FILTER)
      : null,
    loadFirstPartyInsights(candidates),
    // 招聘周期观测（校招洞察 P2）：仅 verified 且未过期，新表唯一源，不与 insight_items timing 混同。
    profileLight ? loadRecruitmentCycles(profileLight.id, today) : [],
  ]);

  let profile: CompanyProfile | null = profileLight;
  if (fullProfileRes?.error) {
    console.warn("[insights] 补取画像全列失败，回落轻列", fullProfileRes.error.message);
  } else if (fullProfileRes?.data) {
    profile = fullProfileRes.data as CompanyProfile;
  }

  const derived = deriveCompanyInsights((jobRows || []) as Job[], new Date(), {
    headcountBand: profile?.headcount_band ?? null,
    sampleCapped: (jobRows?.length || 0) >= DERIVE_JOB_CAP,
  });

  // 过校验门 + 分组（共享 insight-bundle）。
  let storedDims = emptyDimensions();
  let evaluations: ReturnType<typeof groupGatedInsights>["evaluations"] = [];
  if (itemsRes) {
    if (itemsRes.error) {
      console.error("[insights] 读取 insight_items 失败", itemsRes.error.message);
      return NextResponse.json(
        { ok: false, error: itemsRes.error.message },
        { status: 500 },
      );
    }
    const grouped = groupGatedInsights((itemsRes.data || []) as any[], new Date());
    storedDims = grouped.dimensions;
    evaluations = grouped.evaluations;
  }
  const storedHasAny = INSIGHT_DIMENSIONS.some((dim) => storedDims[dim].length > 0);

  // 4) 合并：每维度「派生在前、存储在后」。
  const dimensions = emptyDimensions();
  for (const dim of INSIGHT_DIMENSIONS) {
    dimensions[dim] = [...(derived[dim] || []), ...storedDims[dim]];
  }
  const hasAny = INSIGHT_DIMENSIONS.some((dim) => dimensions[dim].length > 0);

  // 5) 现查快车道：用户主动点开、有真实在招岗位、但没有新鲜存储型洞察时，触发单公司富化。
  //    挪到响应之后跑：它要读节流台账、写一行台账、再调一次 GitHub（超时 10s），而它的返回值
  //    没有任何调用方在读（全仓无 enrich_now 的消费者）—— 此前却让用户陪着等完才看到抽屉内容。
  //    结果照旧落在 discovery_runs 台账里（成功 / 失败 / 被节流都有记录）。
  const jobCount = jobRows?.length || 0;
  if (jobCount > 0 && !storedHasAny) {
    // 派发与占位一律用**画像里的规范名**，不用查询词原文。
    // 用原文的后果（2026-10-10 实测踩到）：查「星巴克」命中的是画像「星巴克 Starbucks」，占位却按
    // 「星巴克」另建了一行空画像；之后再查「星巴克」精确命中这行空的，候选名里没有真正的公司名，
    // 一个岗位都取不到 —— 抽屉从「有 2 条洞察」变成「暂无洞察」。
    const enrichCompany = profileLight?.company ?? company;
    after(async () => {
      try {
        await maybeDispatchInsightEnrich({ userId: user.id, company: enrichCompany, jobCount, storedHasAny });
      } catch (e) {
        console.error("[insights] 现查派发异常", (e as Error).message);
      }
    });
  }

  return NextResponse.json({
    ok: true,
    company: profile,
    query: company,
    dimensions,
    // 有任何可展示条目（含派生）→ 无失败；否则沿用存储项的 bundle 级判定
    failure_reason: hasAny ? null : resolveInsightFailure(evaluations),
    first_party: firstParty,
    recruitment_cycles: recruitmentCycles,
  });
}

// jobs 已迁自建香港 PG：配了 env 走 jobs-store（按 company 取 active），异常或未配则 Supabase 兜底。
async function loadDeriveJobRows(supabase: any, candidates: string[]): Promise<any[]> {
  if (jobsStoreEnabled()) {
    try {
      return await activeJobsByCompanies(candidates, DERIVE_JOB_CAP);
    } catch (e) {
      console.error("[insights] 读取香港库 jobs（派生）失败", (e as Error).message);
    }
  }
  const { data, error: jobError } = await supabase
    .from("jobs")
    .select(
      "company,title,location,job_type,salary_text,posted_at,first_seen_at,last_seen_at,status",
    )
    .in("company", candidates)
    .eq("status", "active")
    .limit(DERIVE_JOB_CAP);
  if (jobError) {
    console.error("[insights] 读取 jobs（派生）失败", jobError.message);
  }
  return data || [];
}

async function loadRecruitmentCycles(companyId: string, today: string): Promise<any[]> {
  const { data: cycleRows } = await createServiceClient()
    .from("recruitment_cycle_observations")
    .select(
      "id, grad_class, season, batch, event, time_expr_type, value_text, month_start, month_end, confidence, evidence_url, evidence_excerpt, valid_until",
    )
    .eq("company_id", companyId)
    .eq("verify_status", "verified")
    .or(`valid_until.is.null,valid_until.gte.${today}`)
    .order("season")
    .order("month_start");
  return cycleRows || [];
}

function emptyFirstParty(): FirstPartyAggregate {
  return {
    visible: false,
    summary: { count: 0, average_rating: null },
    items: [],
  };
}

async function loadFirstPartyInsights(candidates: string[]): Promise<FirstPartyAggregate> {
  if (candidates.length === 0) return emptyFirstParty();

  let service: ReturnType<typeof createServiceClient>;
  try {
    service = createServiceClient();
  } catch {
    return emptyFirstParty();
  }

  const { data, error } = await service
    .from("insight_submissions")
    .select(
      "id,company,company_id,dimension,topic,rating,content,payload,status,employment_verified,created_at,updated_at",
    )
    .in("company", candidates)
    .eq("status", "approved")
    .order("created_at", { ascending: false });

  if (error) {
    console.error("[insights] 读取 first_party submissions 失败", error.message);
    return emptyFirstParty();
  }

  return aggregateFirstParty((data || []) as InsightSubmissionRow[], {
    minCount: FIRST_PARTY_DISPLAY_MIN_COUNT,
  });
}

async function maybeDispatchInsightEnrich({
  userId,
  company,
  jobCount,
  storedHasAny,
}: {
  userId: string;
  company: string;
  jobCount: number;
  storedHasAny: boolean;
}) {
  if (jobCount <= 0 || storedHasAny) return null;

  let service: ReturnType<typeof createServiceClient>;
  try {
    service = createServiceClient();
  } catch (e) {
    return { status: "skipped", reason: "service_not_configured" };
  }

  try {
    await service
      .from("company_profiles")
      .upsert({ company, insight_checked_at: null }, { onConflict: "company" });
  } catch (e) {
    console.error("[insights] 现查画像占位失败（不影响展示）", (e as Error).message);
  }

  const nowMs = Date.now();
  const lookbackHours = Math.max(1, ENRICH_NOW_COOLDOWN_HOURS);
  const sinceIso = new Date(nowMs - lookbackHours * 60 * 60 * 1000).toISOString();
  const { data: recentRuns, error: recentError } = await service
    .from("discovery_runs")
    .select("id,status,created_at,started_at,company,query,diagnostics")
    .eq("mode", "insight_enrich")
    .gte("created_at", sinceIso)
    .order("created_at", { ascending: false })
    .limit(100);
  if (recentError) {
    console.error("[insights] 读取现查节流台账失败", recentError.message);
    return { status: "skipped", reason: "ledger_unavailable" };
  }

  const decision = evaluateInsightEnrichDispatch(recentRuns || [], company, nowMs, {
    cooldownHours: ENRICH_NOW_COOLDOWN_HOURS,
    hourlyCap: ENRICH_NOW_HOURLY_CAP,
  });
  if (decision.action === "reuse") {
    return { status: "reused", run_id: decision.run.id };
  }
  if (decision.action === "cooldown" || decision.action === "global_cap") {
    return {
      status: "throttled",
      reason: decision.action,
      retry_after_sec: decision.retryAfterSec,
    };
  }
  if (decision.action !== "dispatch") {
    return { status: "skipped", reason: decision.reason || decision.action };
  }

  const config = resolveDispatchConfig({
    ...process.env,
    GITHUB_DISPATCH_WORKFLOW: process.env.INSIGHT_ENRICH_WORKFLOW || "insight-enrich.yml",
  });
  if (!config.configured) {
    return { status: "skipped", reason: "dispatch_not_configured", missing_env: config.missing };
  }

  const runId = randomUUID();
  const startedAt = new Date(nowMs).toISOString();
  const record = buildInsightEnrichRunRecord({ runId, userId, company, startedAt });
  const { error: insertError } = await service.from("discovery_runs").insert(record);
  if (insertError) {
    console.error("[insights] 写入现查台账失败", insertError.message);
    return { status: "skipped", reason: "ledger_insert_failed" };
  }

  let dispatchHttpStatus: number | null = null;
  let dispatchError: string | null = null;
  try {
    const req = buildWorkflowDispatchRequest({
      slug: config.slug,
      workflowFile: config.workflowFile,
      ref: config.ref,
      token: config.token,
      inputs: buildInsightWorkflowInputs({ company, runId }),
      userAgent: "job-radar-insight-enrich",
    });
    const resp = await fetch(req.url, {
      method: req.method,
      headers: req.headers,
      body: req.body,
      signal: AbortSignal.timeout(ENRICH_DISPATCH_TIMEOUT_MS),
    });
    dispatchHttpStatus = resp.status;
    if (!isDispatchAccepted(resp.status)) {
      const text = await resp.text().catch(() => "");
      dispatchError = `GitHub workflow_dispatch HTTP ${resp.status}${text ? `: ${text.slice(0, 300)}` : ""}`;
    }
  } catch (err) {
    dispatchError = err instanceof Error ? err.message : String(err);
  }

  if (dispatchError) {
    await service
      .from("discovery_runs")
      .update({
        status: "failed",
        failure_reason: "dispatch_failed",
        error_message: dispatchError.slice(0, 1000),
        finished_at: new Date().toISOString(),
      })
      .eq("id", runId);
    return {
      status: "failed",
      reason: "dispatch_failed",
      run_id: runId,
      dispatch_http_status: dispatchHttpStatus,
    };
  }

  return { status: "queued", run_id: runId, dispatch_http_status: dispatchHttpStatus };
}

export async function POST(request: NextRequest) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }

  const company = String(body.company || "").trim();
  const dimension = body.dimension as InsightDimension;
  const grade = body.grade;
  const content = String(body.content || "").trim();
  const sources = Array.isArray(body.sources) ? body.sources : [];

  if (!company || !INSIGHT_DIMENSIONS.includes(dimension) || !content) {
    return NextResponse.json(
      { ok: false, error: "missing_required_fields" },
      { status: 400 },
    );
  }

  // 用校验门预检（构造一个临时 item + sources 视图）
  const draftItem = {
    id: "draft",
    company_id: "draft",
    dimension,
    grade,
    title: body.title ?? null,
    content,
    sample_size: body.sample_size ?? null,
    payload: body.payload ?? {},
    time_window: body.time_window ?? null,
    valid_from: body.valid_from ?? null,
    valid_until: body.valid_until ?? null,
    last_verified_at: new Date().toISOString(),
    deidentified: body.deidentified === true,
    status: "active",
    created_at: "",
    updated_at: "",
  } as InsightItem;
  const draftSources: InsightSource[] = sources.map((s: any, i: number) => ({
    id: `draft-${i}`,
    url: String(s.url || ""),
    publisher: s.publisher ?? null,
    source_kind: s.source_kind ?? null,
    excerpt: s.excerpt ?? null,
    collected_at: s.collected_at ?? null,
    deidentified: s.deidentified === true,
    created_at: "",
  }));

  const ev = evaluateInsight(draftItem, draftSources, new Date());
  if (!ev.displayable) {
    return NextResponse.json(
      { ok: false, error: "validation_failed", failure_reason: ev.failure_reason },
      { status: 422 },
    );
  }

  const service = createServiceClient();

  // upsert 公司画像
  const { data: companyRow, error: companyError } = await service
    .from("company_profiles")
    .upsert({ company }, { onConflict: "company" })
    .select("id")
    .single();
  if (companyError) {
    console.error("[insights] upsert company_profiles 失败", companyError.message);
    return NextResponse.json({ ok: false, error: companyError.message }, { status: 500 });
  }

  // 插入条目
  const { data: itemRow, error: insertError } = await service
    .from("insight_items")
    .insert({
      company_id: companyRow.id,
      dimension,
      grade,
      title: draftItem.title,
      content,
      sample_size: draftItem.sample_size,
      payload: draftItem.payload,
      time_window: draftItem.time_window,
      valid_from: draftItem.valid_from,
      valid_until: draftItem.valid_until,
      last_verified_at: draftItem.last_verified_at,
      deidentified: draftItem.deidentified,
      status: "active",
    })
    .select("id")
    .single();
  if (insertError) {
    console.error("[insights] 插入 insight_items 失败", insertError.message);
    return NextResponse.json({ ok: false, error: insertError.message }, { status: 500 });
  }

  // 插入来源 + 关联
  for (const s of draftSources) {
    const { data: srcRow, error: srcError } = await service
      .from("insight_sources")
      .insert({
        url: s.url,
        publisher: s.publisher,
        source_kind: s.source_kind,
        excerpt: s.excerpt,
        collected_at: s.collected_at,
        deidentified: s.deidentified,
      })
      .select("id")
      .single();
    if (srcError) {
      console.error("[insights] 插入 insight_sources 失败", srcError.message);
      continue;
    }
    await service
      .from("insight_item_sources")
      .insert({ item_id: itemRow.id, source_id: srcRow.id });
  }

  return NextResponse.json({ ok: true, item_id: itemRow.id });
}

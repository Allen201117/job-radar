import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "crypto";
import { requireAdmin, requireUser } from "@/lib/apiAuth";
import discoveryDispatch from "@/lib/discovery-dispatch";
import insightEnrichNow from "@/lib/insight-enrich-now";
import { createServiceClient } from "@/lib/supabaseService";
import { findCompanyProfile } from "@/lib/insight-match";
import { evaluateInsight, resolveInsightFailure } from "@/lib/insight-verification";
import {
  INSIGHT_DIMENSIONS,
  ITEM_COLUMNS,
  emptyDimensions,
  groupGatedInsights,
} from "@/lib/insight-bundle";
import { deriveCompanyInsights } from "@/lib/insight-derive";
import { jobsStoreEnabled, activeJobsByCompanies } from "@/lib/jobs-store/read";
import type {
  CompanyProfile,
  InsightDimension,
  InsightItem,
  InsightSource,
  Job,
} from "@/lib/types";

export const runtime = "nodejs";

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
  const { data: profiles, error: profileError } = await supabase
    .from("company_profiles")
    .select("*");
  if (profileError) {
    console.error("[insights] 读取 company_profiles 失败", profileError.message);
    return NextResponse.json(
      { ok: false, error: profileError.message },
      { status: 500 },
    );
  }
  const profile = findCompanyProfile((profiles || []) as CompanyProfile[], company);

  // 2) Tier1 派生：从自有 jobs 直接算事实洞察（无需画像，保证 100% 覆盖）。
  //    匹配候选 = 查询词 + 画像 company/aliases；限 active，cap 3000 行足够代表性聚合。
  const candidates = Array.from(
    new Set(
      profile ? [profile.company, ...(profile.aliases || []), company] : [company],
    ),
  );
  // jobs 已迁自建香港 PG：配了 env 走 jobs-store（按 company 取 active），否则 Supabase 兜底。
  let jobRows: any[] | null = null;
  if (jobsStoreEnabled()) {
    try {
      jobRows = await activeJobsByCompanies(candidates, 3000);
    } catch (e) {
      console.error("[insights] 读取香港库 jobs（派生）失败", (e as Error).message);
      jobRows = null; // 异常 → Supabase 兜底
    }
  }
  if (jobRows === null) {
    const { data, error: jobError } = await supabase
      .from("jobs")
      .select(
        "company,title,location,job_type,salary_text,posted_at,first_seen_at,last_seen_at,status",
      )
      .in("company", candidates)
      .eq("status", "active")
      .limit(3000);
    if (jobError) {
      console.error("[insights] 读取 jobs（派生）失败", jobError.message);
    }
    jobRows = data || [];
  }
  const derived = deriveCompanyInsights((jobRows || []) as Job[], new Date(), {
    headcountBand: profile?.headcount_band ?? null,
  });

  // 3) 存储型洞察（仅当有画像）：过校验门 + 分组（共享 insight-bundle）。
  let storedDims = emptyDimensions();
  let evaluations: ReturnType<typeof groupGatedInsights>["evaluations"] = [];
  if (profile) {
    const { data: items, error: itemError } = await supabase
      .from("insight_items")
      .select(`${ITEM_COLUMNS}, insight_item_sources(insight_sources(*))`)
      .eq("company_id", profile.id)
      .eq("status", "active");
    if (itemError) {
      console.error("[insights] 读取 insight_items 失败", itemError.message);
      return NextResponse.json(
        { ok: false, error: itemError.message },
        { status: 500 },
      );
    }
    const grouped = groupGatedInsights((items || []) as any[], new Date());
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

  // 5) 现查快车道：用户主动点开、有真实在招岗位、但没有新鲜存储型洞察时，非阻塞触发单公司富化。
  const enrichNow = await maybeDispatchInsightEnrich({
    userId: user.id,
    company,
    jobCount: jobRows?.length || 0,
    storedHasAny,
  });

  return NextResponse.json({
    ok: true,
    company: profile,
    query: company,
    dimensions,
    // 有任何可展示条目（含派生）→ 无失败；否则沿用存储项的 bundle 级判定
    failure_reason: hasAny ? null : resolveInsightFailure(evaluations),
    enrich_now: enrichNow,
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

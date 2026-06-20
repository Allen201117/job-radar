import { NextRequest, NextResponse } from "next/server";
import { assertOwnership, requireUser } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import liveSearch from "@/lib/live-search";
import discoveryDispatch from "@/lib/discovery-dispatch";
import { jobsStoreEnabled, jobsByUrls } from "@/lib/jobs-store/read";

export const runtime = "nodejs";

const { toApiJob } = liveSearch as any;
const { summarizeDiscoveryRunStatus, extractProducedJdUrls } = discoveryDispatch as any;

/**
 * GET /api/discovery/status?runId=...
 *
 * 轮询一次按需发现的进度。返回 phase（queued/running/done/failed）+ 计数 + 时间戳，
 * 终态时附带本次产出的岗位（按 diagnostics.produced_jd_urls 回查 jobs）。
 */
export async function GET(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;
  const { user } = auth;

  const params = request.nextUrl.searchParams;
  const runId = (params.get("runId") || params.get("run_id") || "").trim();
  if (!runId) {
    return NextResponse.json(
      { ok: false, error: "missing_run_id", mode: "browser_discovery" },
      { status: 400 },
    );
  }

  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    return NextResponse.json(
      { ok: false, error: "Missing SUPABASE_SERVICE_ROLE_KEY", mode: "browser_discovery" },
      { status: 500 },
    );
  }

  const service = createServiceClient();
  const { data: run, error } = await service
    .from("discovery_runs")
    .select("*")
    .eq("id", runId)
    .maybeSingle();

  if (error) {
    return NextResponse.json(
      { ok: false, error: "run_lookup_failed", detail: error.message, mode: "browser_discovery" },
      { status: 500 },
    );
  }
  if (!run) {
    return NextResponse.json(
      { ok: false, error: "run_not_found", run_id: runId, mode: "browser_discovery" },
      { status: 404 },
    );
  }
  // service-role 绕过 RLS：按 id 查到行后必须显式复核归属。
  const ownershipError = assertOwnership(run, user.id);
  if (ownershipError) return ownershipError;

  let summary = summarizeDiscoveryRunStatus(run);
  const diag = (run.diagnostics || {}) as any;

  // 读时 staleness 自愈：running 但心跳(diagnostics.last_update_at)超 15min → CI 已死（SIGKILL 时
  // Python except 不触发，run 会永卡 running）。无 cron，读时判定最省；并尽力回写 failed 让节流也解封。
  const STALE_MS = 15 * 60 * 1000;
  const lastBeat = Date.parse(
    String(diag.last_update_at || run.started_at || run.created_at || ""),
  );
  if (summary.status === "running" && Number.isFinite(lastBeat) && Date.now() - lastBeat > STALE_MS) {
    summary = { ...summary, status: "failed", phase: "failed", isTerminal: true, failureReason: "stale_no_heartbeat" };
    service
      .from("discovery_runs")
      .update({ status: "failed", failure_reason: "stale_no_heartbeat", finished_at: new Date().toISOString() })
      .eq("id", runId)
      .eq("user_id", user.id)
      .eq("status", "running")
      .then(undefined, () => {}); // best-effort，不阻塞响应
  }

  // 流式：每次轮询都按 diagnostics.produced_jd_urls 回查已入库岗位（不再只在终态），让结果边跑边冒。
  // jobs 已迁自建香港 PG（刷新公司库的 crawler 也写香港库）：配了 env 走 jobs-store；异常落回 Supabase 兜底。
  let jobs: any[] = [];
  const urls = extractProducedJdUrls(run);
  if (urls.length > 0) {
    let fetched = false;
    if (jobsStoreEnabled()) {
      try {
        jobs = await jobsByUrls(urls, true);
        fetched = true;
      } catch {
        /* 香港库异常 → 走 Supabase 兜底 */
      }
    }
    if (!fetched) {
      const { data: jobRows } = await service
        .from("jobs")
        .select("*")
        .in("jd_url", urls)
        .eq("status", "active");
      jobs = jobRows || [];
    }
  }

  const progress =
    diag.progress && typeof diag.progress === "object"
      ? { done: Number(diag.progress.done || 0), total: Number(diag.progress.total || 0) }
      : null;

  return NextResponse.json({
    ok: true,
    mode: run.mode || "browser_discovery",
    run_id: runId,
    status: summary.status,
    phase: summary.phase,
    is_terminal: summary.isTerminal,
    progress, // { done, total } —— 前端真实进度条（替代硬编码）
    scope_companies: diag.scope_companies ?? null, // 本轮抓取的 distinct 公司数（漏斗透明化）
    query: run.query,
    city: run.city,
    company: run.company,
    job_type: run.job_type,
    jobs_created: summary.jobsCreated,
    jobs_updated: summary.jobsUpdated,
    candidates_found: summary.candidatesFound,
    failure_reason: summary.failureReason,
    error_message: summary.errorMessage,
    started_at: summary.startedAt,
    finished_at: summary.finishedAt,
    jobs: jobs.map((job: any) => toApiJob(job, 60)),
    total: jobs.length,
  });
}

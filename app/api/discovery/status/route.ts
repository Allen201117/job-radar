import { NextRequest, NextResponse } from "next/server";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { createServerSupabase } from "@/lib/auth";
import liveSearch from "@/lib/live-search";
import discoveryDispatch from "@/lib/discovery-dispatch";

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
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

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
  // Scope to the requesting user (service client bypasses RLS, so check manually).
  if (run.user_id && run.user_id !== user.id) {
    return NextResponse.json(
      { ok: false, error: "forbidden", run_id: runId, mode: "browser_discovery" },
      { status: 403 },
    );
  }

  const summary = summarizeDiscoveryRunStatus(run);

  let jobs: any[] = [];
  if (summary.isTerminal) {
    const urls = extractProducedJdUrls(run);
    if (urls.length > 0) {
      const { data: jobRows } = await service
        .from("jobs")
        .select("*")
        .in("jd_url", urls)
        .eq("status", "active");
      jobs = jobRows || [];
    }
  }

  return NextResponse.json({
    ok: true,
    mode: "browser_discovery",
    run_id: runId,
    status: summary.status,
    phase: summary.phase,
    is_terminal: summary.isTerminal,
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

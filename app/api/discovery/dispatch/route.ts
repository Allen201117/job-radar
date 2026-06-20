import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "crypto";
import type { SupabaseClient } from "@supabase/supabase-js";
import { requireUser } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import discoveryDispatch from "@/lib/discovery-dispatch";

export const runtime = "nodejs";

const {
  validateDiscoveryDispatchInput,
  buildBrowserDiscoveryRunRecord,
  buildWorkflowDispatchRequest,
  resolveDispatchConfig,
  isDispatchAccepted,
} = discoveryDispatch as any;

const DISPATCH_TIMEOUT_MS = 10000;

/**
 * POST /api/discovery/dispatch
 *
 * 按需「浏览器发现」入口：插入一条 'queued' 的 discovery_runs，触发 GitHub Actions
 * workflow_dispatch 跑 Playwright 拦截，立即返回 run_id；前端用 /api/discovery/status 轮询。
 */
export async function POST(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;
  const { user, supabase } = auth;

  let body: any = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }

  const validation = validateDiscoveryDispatchInput(body);
  if (!validation.ok) {
    return NextResponse.json(
      {
        ok: false,
        error: "invalid_input",
        details: validation.errors,
        mode: "browser_discovery",
      },
      { status: 400 },
    );
  }
  const { query, city, company, jobType, limit } = validation.normalized;

  // 偏好底层逻辑：手动筛选项优先；未填的城市/类型默认用用户已保存偏好；排除词始终生效。
  const prefs = await loadUserPreferences(supabase, user.id);
  const effCity = city || prefs.city;
  const effJobType = jobType || prefs.experienceStage;
  const excludeKeywords = prefs.excludeKeywords;

  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    return NextResponse.json(
      { ok: false, error: "Missing SUPABASE_SERVICE_ROLE_KEY", mode: "browser_discovery" },
      { status: 500 },
    );
  }

  const config = resolveDispatchConfig(process.env);
  if (!config.configured) {
    return NextResponse.json(
      {
        ok: false,
        error: "dispatch_not_configured",
        missing_env: config.missing,
        mode: "browser_discovery",
        hint:
          "Set GITHUB_DISPATCH_TOKEN (PAT with actions:write) + GITHUB_DISPATCH_REPO (owner/name) " +
          "to enable on-demand browser discovery.",
      },
      { status: 503 },
    );
  }

  const service = createServiceClient();
  const runId = randomUUID();
  const startedAt = new Date().toISOString();
  const record = buildBrowserDiscoveryRunRecord({
    runId,
    userId: user.id,
    query,
    city: effCity,
    company,
    jobType: effJobType,
    startedAt,
  });

  const { error: insertError } = await service.from("discovery_runs").insert(record);
  if (insertError) {
    return NextResponse.json(
      {
        ok: false,
        error: "run_insert_failed",
        detail: insertError.message,
        mode: "browser_discovery",
        hint: "Apply migration 009_discovery_async_runs.sql (status 'queued'/'running' + async columns).",
      },
      { status: 500 },
    );
  }

  // Fire the workflow_dispatch. On any failure, mark the run failed so the poller sees a terminal state.
  let dispatchHttpStatus: number | null = null;
  let dispatchError: string | null = null;
  try {
    const req = buildWorkflowDispatchRequest({
      slug: config.slug,
      workflowFile: config.workflowFile,
      ref: config.ref,
      token: config.token,
      inputs: {
        mode: "discovery",
        run_id: runId,
        query,
        city: effCity,
        job_type: effJobType,
        exclude: JSON.stringify(excludeKeywords),
        limit,
      },
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
      dispatchError = `GitHub workflow_dispatch returned HTTP ${resp.status}`;
      if (text) dispatchError += `: ${text.slice(0, 300)}`;
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
      .eq("id", runId)
      .eq("user_id", user.id);
    return NextResponse.json(
      {
        ok: false,
        error: "dispatch_failed",
        detail: dispatchError,
        run_id: runId,
        dispatch_http_status: dispatchHttpStatus,
        mode: "browser_discovery",
      },
      { status: 502 },
    );
  }

  return NextResponse.json({
    ok: true,
    mode: "browser_discovery",
    run_id: runId,
    status: "queued",
    query,
    city: effCity,
    company,
    job_type: effJobType,
    // 让前端可提示「城市/类型未填，已用你的求职偏好默认」。
    preference_defaults: {
      city_from_pref: !city && Boolean(effCity),
      job_type_from_pref: !jobType && Boolean(effJobType),
      exclude_count: excludeKeywords.length,
    },
    limit,
    dispatch_http_status: dispatchHttpStatus,
    poll: `/api/discovery/status?runId=${runId}`,
    estimated_seconds: { min: 60, max: 300 },
    started_at: startedAt,
  });
}

// 读取用户已保存的求职偏好（简历画像 + 偏好表），用于「未手动配置则默认按偏好」。
async function loadUserPreferences(
  supabase: SupabaseClient,
  userId: string,
): Promise<{ city: string; experienceStage: string; excludeKeywords: string[] }> {
  const empty = { city: "", experienceStage: "", excludeKeywords: [] as string[] };
  try {
    const [cpRes, upRes] = await Promise.all([
      supabase
        .from("candidate_profiles")
        .select("experience_stage, target_locations")
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
    return {
      city: cities[0] || "",
      experienceStage: String(cp?.experience_stage || "").trim(),
      excludeKeywords: clean(up?.exclude_keywords),
    };
  } catch (err) {
    console.error("[dispatch] 读取用户偏好失败", (err as Error).message);
    return empty;
  }
}

// 偏好读写 + 关注公司覆盖同步（§4.4 / §10.3）。取代 PreferenceForm 直连 Supabase。
// 偏好本体走用户上下文 supabase（RLS 限本人）；覆盖请求 company_watch_requests 走 service role 代写。
// P0-2：coverage 必须**真实写入 + read-back 成功**才算成功；任一 DB 操作出错 → 诚实部分成功，绝不内存伪造 badge。
import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import { buildRadarProfile, profileReadiness } from "@/lib/opportunities/profile";
import { parsePreferenceScopeInput, parsePreferencesInput } from "@/lib/opportunities/preferences-input";
import { isMissingRelation } from "@/lib/opportunities/schema-errors";
import { fetchAllSources } from "@/lib/supabase-paginate";
import { buildCoverageRows } from "@/lib/sync-coverage";
import type { CandidateProfile, UserPreferences } from "@/lib/types";

export const runtime = "nodejs";

type Coverage = { company: string; status: string; matched_sources: number; resolution_note: string | null };

class CoverageError extends Error {
  code: string;
  constructor(code: string) {
    super(code);
    this.code = code;
  }
}

// §10.3：按 normalized company 比对 enabled sources；命中→covered，否则保留管理员态或 queued；删不再 target 的。
// 仅在所有写入 + read-back 成功后返回；任一出错 throw CoverageError（区分 schema 缺失 vs 其它）。
async function syncCoverage(userId: string, targetCompanies: string[]): Promise<Coverage[]> {
  const service = createServiceClient();

  // Step 1：并行读（fetchAllSources 与 existingRes 互不依赖）。
  // ⚠️ 必须分页拉全量 enabled sources（当前 1079 行，越过 PostgREST 单次 1000 行上限）：
  // 截断后落在尾部的公司会被误判「无源覆盖」→ 用户看到 queued 而不是 covered（用户可见错误）。
  // existingRes 多取 id 字段，省去后续单独读 stale 行 id 的一次往返。
  let enabledSources: Array<{ id: string; company: string | null }>;
  let existingRes: { data: Array<{ id: string; normalized_company: string; status: string }> | null; error: any };
  try {
    const [srcs, exRes] = await Promise.all([
      fetchAllSources<{ id: string; company: string | null }>(service, "id, company", { enabledOnly: true }),
      service
        .from("company_watch_requests")
        .select("id, normalized_company, status")
        .eq("user_id", userId),
    ]);
    enabledSources = srcs;
    existingRes = exRes as typeof existingRes;
  } catch {
    throw new CoverageError("coverage_sync_failed");
  }
  if (existingRes.error)
    throw new CoverageError(
      isMissingRelation(existingRes.error) ? "coverage_schema_unavailable" : "coverage_sync_failed",
    );

  // Step 2：纯计算，无 DB 调用。
  const updatedAt = new Date().toISOString();
  const { rows: baseRows, staleIds } = buildCoverageRows(
    targetCompanies,
    enabledSources,
    existingRes.data || [],
  );
  const rows = baseRows.map((r) => ({ ...r, user_id: userId, updated_at: updatedAt }));

  // Step 3：并行写（upsert 与 delete 作用于不相交行集，互不冲突）。
  const writes: Promise<{ error: any }>[] = [];
  if (rows.length)
    writes.push(
      (service
        .from("company_watch_requests")
        .upsert(rows, { onConflict: "user_id,normalized_company" }) as unknown) as Promise<{ error: any }>,
    );
  if (staleIds.length)
    writes.push(
      (service.from("company_watch_requests").delete().in("id", staleIds) as unknown) as Promise<{
        error: any;
      }>,
    );
  if (writes.length) {
    const results = await Promise.all(writes);
    for (const res of results) {
      if (res.error)
        throw new CoverageError(
          isMissingRelation(res.error) ? "coverage_schema_unavailable" : "coverage_sync_failed",
        );
    }
  }

  // Step 4：权威 coverage 来自 read-back（不是内存计算）。
  const back = await service
    .from("company_watch_requests")
    .select("company, status, matched_source_ids, resolution_note")
    .eq("user_id", userId)
    .order("created_at", { ascending: true });
  if (back.error) throw new CoverageError("coverage_sync_failed");
  return (back.data || []).map((r: any) => ({
    company: r.company,
    status: r.status,
    matched_sources: (r.matched_source_ids || []).length,
    resolution_note: r.resolution_note ?? null,
  }));
}

export async function GET() {
  const auth = await requireUser();
  if (auth.error) return auth.error;
  const { supabase, user } = auth;

  const [prefsRes, candRes, watchRes] = await Promise.all([
    supabase.from("user_preferences").select("*").eq("user_id", user.id).maybeSingle(),
    supabase.from("candidate_profiles").select("*").eq("user_id", user.id).maybeSingle(),
    supabase
      .from("company_watch_requests")
      .select("company, status, matched_source_ids, resolution_note")
      .eq("user_id", user.id)
      .order("created_at", { ascending: true }),
  ]);

  const profile = buildRadarProfile(
    user.id,
    prefsRes.data as UserPreferences | null,
    candRes.data as CandidateProfile | null,
  );

  // coverage 查询失败（如迁移未应用）→ 不返回空数组假装"无关注公司"，标 coverage_available=false（§P0-2.5）
  if (watchRes.error) {
    return NextResponse.json({
      ok: true,
      preferences: prefsRes.data || null,
      profile_ready: profileReadiness(profile).ready,
      coverage: [],
      coverage_available: false,
    });
  }

  const coverage: Coverage[] = (watchRes.data || []).map((r: any) => ({
    company: r.company,
    status: r.status,
    matched_sources: (r.matched_source_ids || []).length,
    resolution_note: r.resolution_note ?? null,
  }));

  return NextResponse.json({
    ok: true,
    preferences: prefsRes.data || null,
    profile_ready: profileReadiness(profile).ready,
    coverage,
    coverage_available: true,
  });
}

export async function PUT(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;
  const { supabase, user } = auth;

  const INVALID = Symbol("invalid_json");
  const rawBody = await request.json().catch(() => INVALID);
  const parsed = parsePreferencesInput(rawBody === INVALID ? null : rawBody);
  if (!parsed.ok) {
    return NextResponse.json({ ok: false, error: parsed.error }, { status: 400 });
  }
  const { prefs, intensity } = parsed.value;

  // 强度本次有改 → 写值 + source='user' + updated_at（手动覆盖，行为自调要尊重一段时间，见 intensity.ts）。
  const intensityWrite =
    intensity === null
      ? {}
      : { radar_intensity: intensity, radar_intensity_source: "user", radar_intensity_updated_at: new Date().toISOString() };

  const { error: upErr } = await supabase
    .from("user_preferences")
    .upsert({ user_id: user.id, ...prefs, ...intensityWrite }, { onConflict: "user_id" });
  if (upErr) {
    console.error("[preferences] upsert failed:", upErr.message);
    return NextResponse.json({ ok: false, error: "preferences_unavailable" }, { status: 503 });
  }

  const { data: cand } = await supabase
    .from("candidate_profiles")
    .select("*")
    .eq("user_id", user.id)
    .maybeSingle();
  const profile_ready = profileReadiness(
    buildRadarProfile(user.id, { user_id: user.id, ...prefs } as UserPreferences, cand as CandidateProfile | null),
  ).ready;

  // 覆盖同步：成功才返回 coverage；失败返回诚实部分成功（偏好已存、coverage 未同步），前端不得显示成功 badge。
  let coverage: Coverage[];
  try {
    coverage = await syncCoverage(user.id, prefs.target_companies);
  } catch (e) {
    const code = e instanceof CoverageError ? e.code : "coverage_sync_failed";
    console.error("[preferences] coverage sync failed:", code, (e as Error).message);
    return NextResponse.json({
      ok: false,
      preferences_saved: true,
      coverage_synced: false,
      error: code,
      profile_ready,
    });
  }

  return NextResponse.json({
    ok: true,
    preferences: { ...prefs, ...intensityWrite },
    profile_ready,
    coverage,
    coverage_synced: true,
  });
}

export async function PATCH(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;
  const { supabase, user } = auth;

  const INVALID = Symbol("invalid_json");
  const rawBody = await request.json().catch(() => INVALID);
  const parsed = parsePreferenceScopeInput(rawBody === INVALID ? null : rawBody);
  if (!parsed.ok) {
    return NextResponse.json({ ok: false, error: parsed.error }, { status: 400 });
  }

  const { error } = await supabase
    .from("user_preferences")
    .upsert({ user_id: user.id, ...parsed.value }, { onConflict: "user_id" });
  if (error) {
    console.error("[preferences] scope upsert failed:", error.message);
    return NextResponse.json({ ok: false, error: "preferences_unavailable" }, { status: 503 });
  }

  return NextResponse.json({ ok: true, preferences: parsed.value });
}

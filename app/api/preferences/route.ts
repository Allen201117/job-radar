// 偏好读写 + 关注公司覆盖同步（§4.4 / §10.3）。取代 PreferenceForm 直连 Supabase。
// 偏好本体走用户上下文 supabase（RLS 限本人）；覆盖请求 company_watch_requests 走 service role 代写。
// P0-2：coverage 必须**真实写入 + read-back 成功**才算成功；任一 DB 操作出错 → 诚实部分成功，绝不内存伪造 badge。
import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import { buildRadarProfile, profileReadiness } from "@/lib/opportunities/profile";
import { normalizeCompany } from "@/lib/company-normalize";
import type { CandidateProfile, UserPreferences } from "@/lib/types";

export const runtime = "nodejs";

const MAX_ITEMS = 30;
const MAX_LEN = 80;

function cleanArray(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of v) {
    if (typeof raw !== "string") continue;
    const t = raw.trim().slice(0, MAX_LEN);
    if (!t) continue;
    const k = t.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(t);
    if (out.length >= MAX_ITEMS) break;
  }
  return out;
}

function clampDailyLimit(v: unknown): number {
  const n = typeof v === "number" && Number.isFinite(v) ? Math.round(v) : 20;
  return Math.max(5, Math.min(30, n));
}

type Coverage = { company: string; status: string; matched_sources: number; resolution_note: string | null };

class CoverageError extends Error {
  code: string;
  constructor(code: string) {
    super(code);
    this.code = code;
  }
}

// 表/函数不存在 → 迁移未应用，返回稳定 schema 码（§9）
function isSchemaMissing(err: { code?: string; message?: string } | null | undefined): boolean {
  if (!err) return false;
  if (err.code === "42P01") return true; // undefined_table
  const m = String(err.message || "");
  return /does not exist/i.test(m) && /company_watch_requests/i.test(m);
}

// §10.3：按 normalized company 比对 enabled sources；命中→covered，否则保留管理员态或 queued；删不再 target 的。
// 仅在所有写入 + read-back 成功后返回；任一出错 throw CoverageError（区分 schema 缺失 vs 其它）。
async function syncCoverage(userId: string, targetCompanies: string[]): Promise<Coverage[]> {
  const service = createServiceClient();

  const sourcesRes = await service.from("sources").select("id, company").eq("enabled", true);
  if (sourcesRes.error) throw new CoverageError("coverage_sync_failed");
  const existingRes = await service
    .from("company_watch_requests")
    .select("normalized_company, status")
    .eq("user_id", userId);
  if (existingRes.error)
    throw new CoverageError(isSchemaMissing(existingRes.error) ? "coverage_schema_unavailable" : "coverage_sync_failed");

  const sourceMap = new Map<string, string[]>();
  for (const s of sourcesRes.data || []) {
    const norm = normalizeCompany(s.company);
    if (!norm) continue;
    const arr = sourceMap.get(norm) || [];
    arr.push(s.id);
    sourceMap.set(norm, arr);
  }
  const existingStatus = new Map<string, string>();
  for (const e of existingRes.data || []) existingStatus.set(e.normalized_company, e.status);

  const keptNorms = new Set<string>();
  const rows: any[] = [];
  for (const company of targetCompanies) {
    const norm = normalizeCompany(company);
    if (!norm || keptNorms.has(norm)) continue;
    keptNorms.add(norm);
    const matched = sourceMap.get(norm) || [];
    const prev = existingStatus.get(norm);
    const status = matched.length
      ? "covered"
      : prev === "researching" || prev === "unsupported"
        ? prev
        : "queued";
    rows.push({
      user_id: userId,
      company,
      normalized_company: norm,
      status,
      matched_source_ids: matched,
      updated_at: new Date().toISOString(),
    });
  }

  if (rows.length) {
    const up = await service
      .from("company_watch_requests")
      .upsert(rows, { onConflict: "user_id,normalized_company" });
    if (up.error)
      throw new CoverageError(isSchemaMissing(up.error) ? "coverage_schema_unavailable" : "coverage_sync_failed");
  }

  // 删不再 target 的请求
  const allRes = await service
    .from("company_watch_requests")
    .select("id, normalized_company")
    .eq("user_id", userId);
  if (allRes.error) throw new CoverageError("coverage_sync_failed");
  const stale = (allRes.data || []).filter((r: any) => !keptNorms.has(r.normalized_company)).map((r: any) => r.id);
  if (stale.length) {
    const del = await service.from("company_watch_requests").delete().in("id", stale);
    if (del.error) throw new CoverageError("coverage_sync_failed");
  }

  // 权威 coverage 来自 read-back（不是内存计算）
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

  const body = await request.json().catch(() => ({}));
  const prefs = {
    target_locations: cleanArray(body.target_locations),
    target_roles: cleanArray(body.target_roles),
    target_keywords: cleanArray(body.target_keywords),
    exclude_keywords: cleanArray(body.exclude_keywords),
    target_companies: cleanArray(body.target_companies),
    target_industries: cleanArray(body.target_industries),
    daily_limit: clampDailyLimit(body.daily_limit),
  };

  const { error: upErr } = await supabase
    .from("user_preferences")
    .upsert({ user_id: user.id, ...prefs }, { onConflict: "user_id" });
  if (upErr) {
    return NextResponse.json({ ok: false, error: upErr.message }, { status: 500 });
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

  return NextResponse.json({ ok: true, preferences: prefs, profile_ready, coverage, coverage_synced: true });
}

// 偏好读写 + 关注公司覆盖同步（§4.4 / §10.3）。取代 PreferenceForm 直连 Supabase 的写法。
// 偏好本体走用户上下文 supabase（RLS 限本人）；覆盖请求 company_watch_requests 走 service role 代写（客户端无写策略）。
import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import { buildRadarProfile, profileReadiness } from "@/lib/opportunities/profile";
import { normalizeCompany } from "@/lib/company-normalize";
import type { CandidateProfile, UserPreferences } from "@/lib/types";

export const runtime = "nodejs";

const MAX_ITEMS = 30;
const MAX_LEN = 80;

// trim、去空、单项 ≤80、大小写不敏感去重、≤30 项
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

type Coverage = { company: string; status: string; matched_sources: number };

// §10.3：按 normalized company 比对 enabled sources，命中→covered；未命中→保留管理员态(researching/unsupported)否则 queued；
// 删除不再 target 的请求。覆盖写用 service role。
async function syncCoverage(userId: string, targetCompanies: string[]): Promise<Coverage[]> {
  const service = createServiceClient();

  const [{ data: sources }, { data: existing }] = await Promise.all([
    service.from("sources").select("id, company").eq("enabled", true),
    service.from("company_watch_requests").select("normalized_company, status").eq("user_id", userId),
  ]);

  // normalized source company → source ids
  const sourceMap = new Map<string, string[]>();
  for (const s of sources || []) {
    const norm = normalizeCompany(s.company);
    if (!norm) continue;
    const arr = sourceMap.get(norm) || [];
    arr.push(s.id);
    sourceMap.set(norm, arr);
  }
  const existingStatus = new Map<string, string>();
  for (const e of existing || []) existingStatus.set(e.normalized_company, e.status);

  const keptNorms = new Set<string>();
  const rows: any[] = [];
  const coverage: Coverage[] = [];
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
    coverage.push({ company, status, matched_sources: matched.length });
  }

  if (rows.length) {
    await service.from("company_watch_requests").upsert(rows, { onConflict: "user_id,normalized_company" });
  }
  // 删除不再 target 的请求
  const { data: all } = await service
    .from("company_watch_requests")
    .select("id, normalized_company")
    .eq("user_id", userId);
  const stale = (all || []).filter((r: any) => !keptNorms.has(r.normalized_company)).map((r: any) => r.id);
  if (stale.length) {
    await service.from("company_watch_requests").delete().in("id", stale);
  }

  return coverage;
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
      .select("company, status, matched_source_ids")
      .eq("user_id", user.id)
      .order("created_at", { ascending: true }),
  ]);

  const profile = buildRadarProfile(
    user.id,
    prefsRes.data as UserPreferences | null,
    candRes.data as CandidateProfile | null,
  );
  const coverage: Coverage[] = (watchRes.data || []).map((r: any) => ({
    company: r.company,
    status: r.status,
    matched_sources: (r.matched_source_ids || []).length,
  }));

  return NextResponse.json({
    ok: true,
    preferences: prefsRes.data || null,
    profile_ready: profileReadiness(profile).ready,
    coverage,
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

  let coverage: Coverage[] = [];
  try {
    coverage = await syncCoverage(user.id, prefs.target_companies);
  } catch (e) {
    console.error("[preferences] coverage sync failed:", (e as Error).message);
  }

  const { data: cand } = await supabase
    .from("candidate_profiles")
    .select("*")
    .eq("user_id", user.id)
    .maybeSingle();
  const profile = buildRadarProfile(
    user.id,
    { user_id: user.id, ...prefs } as UserPreferences,
    cand as CandidateProfile | null,
  );

  return NextResponse.json({
    ok: true,
    preferences: prefs,
    profile_ready: profileReadiness(profile).ready,
    coverage,
  });
}

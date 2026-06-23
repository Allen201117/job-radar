// 管理员：关注公司覆盖队列（§10.4）。聚合用户希望监控但未覆盖的公司，按 normalized_company 处理。
// 仅管理员；写入走 service role（company_watch_requests 无 authenticated 写策略）。
import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";

export const runtime = "nodejs";

const STATUSES = new Set(["covered", "queued", "researching", "unsupported"]);
const QUEUE_ORDER: Record<string, number> = { queued: 0, researching: 1, unsupported: 2, covered: 3 };

export async function GET() {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  const service = createServiceClient();
  const { data, error } = await service
    .from("company_watch_requests")
    .select("normalized_company, company, status, resolution_note, created_at, updated_at");
  if (error) {
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }

  // 按 normalized_company 聚合：请求人数、代表展示名、最新状态/说明、首次与最近请求时间。
  const byNorm = new Map<string, any>();
  for (const r of data || []) {
    const key = r.normalized_company;
    const agg = byNorm.get(key) || {
      normalized_company: key,
      company: r.company,
      request_count: 0,
      status: r.status,
      resolution_note: r.resolution_note,
      first_requested: r.created_at,
      last_requested: r.updated_at || r.created_at,
      _latest: r.updated_at || r.created_at,
    };
    agg.request_count += 1;
    if (r.created_at && r.created_at < agg.first_requested) agg.first_requested = r.created_at;
    const last = r.updated_at || r.created_at;
    if (last && last > agg.last_requested) agg.last_requested = last;
    // 用最近更新的那行代表状态/说明/展示名
    if (last && last >= agg._latest) {
      agg._latest = last;
      agg.status = r.status;
      agg.resolution_note = r.resolution_note;
      agg.company = r.company;
    }
    byNorm.set(key, agg);
  }

  const items = Array.from(byNorm.values())
    .map(({ _latest, ...rest }) => rest)
    .sort(
      (a, b) =>
        (QUEUE_ORDER[a.status] ?? 9) - (QUEUE_ORDER[b.status] ?? 9) ||
        b.request_count - a.request_count ||
        String(b.last_requested).localeCompare(String(a.last_requested)),
    );

  return NextResponse.json({ ok: true, items });
}

export async function PATCH(request: NextRequest) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  const body = await request.json().catch(() => ({}));
  const normalized = typeof body.normalized_company === "string" ? body.normalized_company.trim() : "";
  const status = typeof body.status === "string" ? body.status : "";
  if (!normalized) return NextResponse.json({ ok: false, error: "missing_normalized_company" }, { status: 400 });
  if (!STATUSES.has(status)) return NextResponse.json({ ok: false, error: "invalid_status" }, { status: 400 });
  const note = typeof body.resolution_note === "string" ? body.resolution_note.trim().slice(0, 300) || null : null;

  const service = createServiceClient();
  // 批量更新同 normalized_company 的所有用户请求（§10.4）
  const { error } = await service
    .from("company_watch_requests")
    .update({ status, resolution_note: note, updated_at: new Date().toISOString() })
    .eq("normalized_company", normalized);
  if (error) {
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}

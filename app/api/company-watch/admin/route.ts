// 管理员：关注公司覆盖队列（§10.4）。聚合用户希望监控但未覆盖的公司，按 normalized_company 处理。
// 仅管理员；写入走 service role（company_watch_requests 无 authenticated 写策略）。
import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import { normalizeCompany } from "@/lib/company-normalize";
import { fetchAllSources } from "@/lib/supabase-paginate";

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

  // covered 必须关联真实 enabled source（§10.4 / P0-2.7）：优先用传入的 matched_source_ids（校验存在且 enabled），
  // 否则按归一公司名自动关联 enabled sources；一个都没有 → 拒绝，不能空标 covered。
  let matchedSourceIds: string[] = [];
  if (status === "covered") {
    const provided = Array.isArray(body.matched_source_ids)
      ? body.matched_source_ids.filter((s: unknown): s is string => typeof s === "string")
      : [];
    if (provided.length) {
      const { data: srcs, error: srcErr } = await service.from("sources").select("id, enabled").in("id", provided);
      if (srcErr) return NextResponse.json({ ok: false, error: srcErr.message }, { status: 500 });
      const validEnabled = new Set((srcs || []).filter((s: any) => s.enabled).map((s: any) => s.id));
      if (provided.some((id: string) => !validEnabled.has(id))) {
        return NextResponse.json({ ok: false, error: "invalid_source_ids" }, { status: 400 });
      }
      matchedSourceIds = provided;
    } else {
      // ⚠️ 必须分页拉全量 enabled sources（1079 行 > PostgREST 单次 1000 行上限）：
      // 截断后落在尾部的源关联不上 → 明明有源却报 covered_requires_source。
      let srcs: Array<{ id: string; company: string | null }>;
      try {
        srcs = await fetchAllSources(service, "id, company", { enabledOnly: true });
      } catch (e: any) {
        return NextResponse.json({ ok: false, error: e?.message || "sources_lookup_failed" }, { status: 500 });
      }
      matchedSourceIds = srcs.filter((s) => normalizeCompany(s.company) === normalized).map((s) => s.id);
    }
    if (!matchedSourceIds.length) {
      return NextResponse.json({ ok: false, error: "covered_requires_source" }, { status: 400 });
    }
  }

  const patch: Record<string, unknown> = {
    status,
    resolution_note: note,
    matched_source_ids: matchedSourceIds, // covered 写真实 source；非 covered 清空
    updated_at: new Date().toISOString(),
  };

  // 批量更新同 normalized_company 的所有用户请求（§10.4）
  const { error } = await service
    .from("company_watch_requests")
    .update(patch)
    .eq("normalized_company", normalized);
  if (error) {
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true, matched_sources: matchedSourceIds.length });
}

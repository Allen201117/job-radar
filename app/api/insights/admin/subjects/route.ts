// ============================================================
// 洞察主体治理（仅 admin）：下架噪声业务线 / 按指标·强度批量处置。
//
// 为什么必须有：业务线是从岗位标题**抽**出来的，再好的停用词也会漏
// （2026-09-03 全库首跑抽检 100 条噪声率 13%，逐类修完仍有约 2%）。
// 抽取器留了 status='rejected' 这条治理回路——**保留行不删**，下一轮据此跳过；
// 删行的话下次抽取会原样把它抽回来，人工白干。这个接口就是那条回路的入口。
// ============================================================
import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import { fetchAllPages } from "@/lib/supabase-paginate";
import { revalidateTag } from "next/cache";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SUBJECT_STATUSES = ["active", "retired", "rejected"];
const ITEM_STATUSES = ["active", "retired", "pending_review"];

export async function GET(request: NextRequest) {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;

  const service = createServiceClient();
  const status = request.nextUrl.searchParams.get("status") || "";

  try {
    const subjects = await fetchAllPages<any>((from, to) => {
      let q = service
        .from("insight_subjects")
        .select("id,company_id,kind,name,job_count,origin,status,last_seen_at");
      if (status) q = q.eq("status", status);
      return q.order("id", { ascending: true }).range(from, to);
    });
    const companies = await fetchAllPages<any>((from, to) =>
      service
        .from("company_profiles")
        .select("id,company")
        .order("id", { ascending: true })
        .range(from, to),
    );
    const nameById = new Map(companies.map((c: any) => [c.id, c.company]));

    // 按 metric_key / assertion 的条目分布：批量处置前先让 admin 看见影响面。
    const buckets = await fetchAllPages<any>((from, to) =>
      service
        .from("insight_items")
        .select("id,metric_key,assertion,status")
        .eq("status", "active")
        .order("id", { ascending: true })
        .range(from, to),
    );
    const byMetric = new Map<string, number>();
    const byAssertion = new Map<string, number>();
    let pendingReview = 0;
    for (const row of buckets) {
      if (row.metric_key) byMetric.set(row.metric_key, (byMetric.get(row.metric_key) || 0) + 1);
      if (row.assertion) byAssertion.set(row.assertion, (byAssertion.get(row.assertion) || 0) + 1);
    }
    const { count } = await service
      .from("insight_items")
      .select("id", { count: "exact", head: true })
      .eq("status", "pending_review");
    pendingReview = count || 0;

    return NextResponse.json({
      ok: true,
      subjects: subjects
        .map((s: any) => ({ ...s, company: nameById.get(s.company_id) || "（无画像）" }))
        .sort((a: any, b: any) => (b.job_count || 0) - (a.job_count || 0)),
      metric_counts: [...byMetric.entries()].map(([key, n]) => ({ key, count: n }))
        .sort((a, b) => b.count - a.count),
      assertion_counts: [...byAssertion.entries()].map(([key, n]) => ({ key, count: n }))
        .sort((a, b) => b.count - a.count),
      pending_review: pendingReview,
    });
  } catch (err: any) {
    console.error("[insight-subjects-admin] 读取失败", err?.message);
    return NextResponse.json({ ok: false, error: err?.message || "load_failed" }, { status: 500 });
  }
}

/** 单个主体上下架。rejected = 判定为噪声，抽取器据此永久跳过。 */
export async function PATCH(request: NextRequest) {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;

  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }
  const id = String(body.id || "").trim();
  const status = String(body.status || "");
  if (!id || !SUBJECT_STATUSES.includes(status)) {
    return NextResponse.json({ ok: false, error: "invalid_input" }, { status: 400 });
  }

  const service = createServiceClient();
  const now = new Date().toISOString();
  const { error } = await service
    .from("insight_subjects")
    .update({ status, updated_at: now })
    .eq("id", id);
  if (error) {
    console.error("[insight-subjects-admin] 改状态失败", error.message);
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }

  // 下架主体时，它名下的派生条目一起退役——否则条目还留在 active，
  // 只是没有任何页面在展示它们（治理做了一半，比没做更难查）。
  let affectedItems = 0;
  if (status !== "active") {
    const { data } = await service
      .from("insight_items")
      .update({ status: "retired", updated_at: now })
      .eq("subject_id", id)
      .eq("status", "active")
      .select("id");
    affectedItems = (data || []).length;
  }
  revalidateTag("insight-library");
  return NextResponse.json({ ok: true, id, status, retired_items: affectedItems });
}

/** 按 metric_key / assertion 批量处置——枚举化的直接收益。 */
export async function POST(request: NextRequest) {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;

  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }
  const metricKey = String(body.metric_key || "").trim();
  const assertion = String(body.assertion || "").trim();
  const status = String(body.status || "");
  if ((!metricKey && !assertion) || !ITEM_STATUSES.includes(status)) {
    return NextResponse.json({ ok: false, error: "invalid_input" }, { status: 400 });
  }

  const service = createServiceClient();
  let query = service
    .from("insight_items")
    .update({ status, updated_at: new Date().toISOString() });
  if (metricKey) query = query.eq("metric_key", metricKey);
  if (assertion) query = query.eq("assertion", assertion);
  const { data, error } = await query.neq("status", status).select("id");
  if (error) {
    console.error("[insight-subjects-admin] 批量处置失败", error.message);
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }
  revalidateTag("insight-library");
  return NextResponse.json({ ok: true, affected: (data || []).length, status });
}

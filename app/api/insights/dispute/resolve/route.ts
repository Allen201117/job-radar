import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";

export const runtime = "nodejs";

// admin 处理申诉（PRD §7.3 通知-删除）：
//   upheld → 申诉成立，把对应条目下架（status=retired）；rejected → 驳回。
export async function POST(request: NextRequest) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }

  const disputeId = String(body.dispute_id || "").trim();
  const resolution = body.resolution;
  if (!disputeId || (resolution !== "upheld" && resolution !== "rejected")) {
    return NextResponse.json({ ok: false, error: "invalid_input" }, { status: 400 });
  }

  const service = createServiceClient();

  const { data: dispute, error: getErr } = await service
    .from("insight_disputes")
    .select("id, item_id, status")
    .eq("id", disputeId)
    .single();
  if (getErr || !dispute) {
    return NextResponse.json({ ok: false, error: getErr?.message || "not_found" }, { status: 404 });
  }

  // I4 修复（2026-09-08）：先下架被申诉条目，成功后才落申诉终态。
  // 旧顺序反过来——申诉状态先写 upheld，条目下架若失败会返回 500，但申诉已经
  // 提交成功：admin 的 GET 只拉 status='open' 的申诉列表，这条已经从队列里消失，
  // 留下「申诉已成立、条目仍 active」的不一致态且无人会再重试。
  // 两步都是对同一目标值的 update，天然幂等：任一步失败就整体 500、原样返回，
  // 调用方按相同参数重试即可收敛（dispute 仍留在 open 队列可见 / 条目已下架、
  // 补齐申诉终态即可）。没有新增迁移，所以不做「一次 RPC 包两步事务」的方案。
  if (resolution === "upheld" && dispute.item_id) {
    const { error: retireErr } = await service
      .from("insight_items")
      .update({ status: "retired", updated_at: new Date().toISOString() })
      .eq("id", dispute.item_id);
    if (retireErr) {
      console.error("[insights-admin] 下架被申诉条目失败", retireErr.message);
      return NextResponse.json({ ok: false, error: retireErr.message }, { status: 500 });
    }
  }

  const { error: upErr } = await service
    .from("insight_disputes")
    .update({ status: resolution, resolved_at: new Date().toISOString() })
    .eq("id", disputeId);
  if (upErr) {
    console.error("[insights-admin] 更新申诉失败", upErr.message);
    return NextResponse.json({ ok: false, error: upErr.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true, item_id: dispute.item_id, resolution });
}

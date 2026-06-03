import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { createServiceClient } from "@/lib/supabaseService";

export const runtime = "nodejs";

// admin 处理申诉（PRD §7.3 通知-删除）：
//   upheld → 申诉成立，把对应条目下架（status=retired）；rejected → 驳回。
export async function POST(request: NextRequest) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }
  const { data: profileRow } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", user.id)
    .maybeSingle();
  if (profileRow?.role !== "admin") {
    return NextResponse.json({ ok: false, error: "forbidden" }, { status: 403 });
  }

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

  const { error: upErr } = await service
    .from("insight_disputes")
    .update({ status: resolution, resolved_at: new Date().toISOString() })
    .eq("id", disputeId);
  if (upErr) {
    console.error("[insights-admin] 更新申诉失败", upErr.message);
    return NextResponse.json({ ok: false, error: upErr.message }, { status: 500 });
  }

  // 申诉成立：下架对应条目，停止展示。
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

  return NextResponse.json({ ok: true, item_id: dispute.item_id, resolution });
}

import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";

export const runtime = "nodejs";

// 通知-删除通道（PRD §7.3）：任意登录用户对某条洞察提异议，admin 后续处理下架。
export async function POST(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;
  const { user, supabase } = auth;

  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }

  const itemId = String(body.item_id || "").trim();
  if (!itemId) {
    return NextResponse.json({ ok: false, error: "missing_item_id" }, { status: 400 });
  }

  const { error } = await supabase.from("insight_disputes").insert({
    item_id: itemId,
    reporter_user_id: user.id,
    reason: body.reason ? String(body.reason).slice(0, 2000) : null,
    contact: body.contact ? String(body.contact).slice(0, 200) : null,
  });
  if (error) {
    console.error("[insights] 申诉写入失败", error.message);
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true });
}

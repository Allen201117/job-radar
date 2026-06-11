import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { parseEventInput } from "@/lib/track";

export const runtime = "nodejs";

// 轻量埋点收集：登录用户的行为事件。
// 未登录 → 直接 204 丢弃；任何失败静默（仅 console.warn），绝不影响主流程，永远 204。
// 写入走用户上下文客户端，由 RLS 保证 user_id = auth.uid()（migration 136）。
export async function POST(request: NextRequest) {
  try {
    const supabase = await createServerSupabase();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) {
      return new NextResponse(null, { status: 204 });
    }

    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return new NextResponse(null, { status: 204 });
    }

    const input = parseEventInput(body);
    if (!input) {
      return new NextResponse(null, { status: 204 });
    }

    const { error } = await supabase.from("events").insert({
      user_id: user.id,
      event: input.event,
      payload: input.payload,
    });
    if (error) {
      console.warn("[events] insert failed:", error.message);
    }
  } catch (e) {
    console.warn("[events] tracking error:", (e as Error).message);
  }
  return new NextResponse(null, { status: 204 });
}

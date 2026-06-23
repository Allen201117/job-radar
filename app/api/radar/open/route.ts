// 记录「上次打开今日机会」（§7.2）：客户端首次成功渲染 feed 后 fire-and-forget 调用。
// 用于「自上次访问新增」计算——故 SSR 读到的是更新前的 last_opened_at，本请求不提前清零当次新增。
import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { parseRadarOpenInput } from "@/lib/opportunities/action-input";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;

  const body = await request.json().catch(() => ({}));
  const now = Date.now();
  const parsed = parseRadarOpenInput(body, now);
  if (!parsed.ok) {
    return NextResponse.json({ ok: false, error: parsed.error }, { status: 400 });
  }

  const nowIso = new Date(now).toISOString();
  const { error } = await auth.supabase.from("user_radar_state").upsert(
    {
      user_id: auth.user.id,
      last_opened_at: nowIso,
      last_feed_generated_at: parsed.value.lastFeedGeneratedAt,
      last_feed_count: parsed.value.feedCount,
      updated_at: nowIso,
    },
    { onConflict: "user_id" },
  );
  if (error) {
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }
  return new NextResponse(null, { status: 204 });
}

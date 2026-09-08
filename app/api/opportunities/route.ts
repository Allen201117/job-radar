// 今日机会 Feed（§7.1）：读 profile/preferences/actions/radar state → buildOpportunityFeed。
// GET 不更新 last_opened_at（那是 /api/radar/open 的事）。
import { NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { buildRadarProfile } from "@/lib/opportunities/profile";
import { resolveIntensityForUser } from "@/lib/opportunities/intensity";
import { buildOpportunityFeed } from "@/lib/opportunities/service";
import { loadRadarContext } from "@/lib/opportunities/context";

export const runtime = "nodejs";
// 须 ≥ jobs 池 statement_timeout(25s)，同 today 页：慢召回要能以 503 feed_unavailable 返回，而非函数被杀。
export const maxDuration = 30;

export async function GET() {
  const auth = await requireUser();
  if (auth.error) return auth.error;
  const { supabase, user } = auth;

  // 上下文读取失败 ≠ 用户没填。失败必须显式 503，让前端重试；静默当空值会丢掉排除词与已处理记录
  // （见 lib/opportunities/context.ts 的口径说明）。
  let ctx;
  try {
    ctx = await loadRadarContext(supabase, user.id);
  } catch (e) {
    console.error("[opportunities] context load failed:", (e as Error).message);
    return NextResponse.json({ ok: false, error: "context_unavailable" }, { status: 503 });
  }

  const profile = buildRadarProfile(user.id, ctx.preferences, ctx.candidate);
  const actions = ctx.actions;
  const radarState = ctx.radarState;
  const now = new Date();
  const { intensity } = resolveIntensityForUser(
    ctx.preferences,
    radarState,
    actions,
    profile.targetCompanies.length > 0,
    now,
  );

  try {
    const feed = await buildOpportunityFeed(supabase, profile, actions, radarState, { surface: "today", intensity, now });
    return NextResponse.json({ ok: true, ...feed });
  } catch (e) {
    console.error("[opportunities] feed build failed:", (e as Error).message);
    return NextResponse.json({ ok: false, error: "feed_unavailable" }, { status: 503 });
  }
}

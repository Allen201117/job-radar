// 临时事故排障路由（用完即删）：用 service role 跑指定用户的 buildOpportunityFeed，把**真实异常 + 栈 + 计时**
// 直接返回，绕过 today 页 try/catch 的吞错（线上看不到 Vercel 日志时的取真相手段）。secret 门控、只返错误文本不返岗位数据。
import { NextRequest, NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabaseService";
import { buildRadarProfile } from "@/lib/opportunities/profile";
import { resolveIntensityForUser } from "@/lib/opportunities/intensity";
import { buildOpportunityFeed } from "@/lib/opportunities/service";
import { recallOpportunityCandidates } from "@/lib/jobs-store/opportunities";
import { jobsStoreEnabled } from "@/lib/jobs-store/read";
import type { UserPreferences, CandidateProfile, JobAction } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 60;

const SECRET = "jr-incident-0626-x7k2";
const DEFAULT_UID = "298146bb-ab6e-4c09-a2bb-87f27cabfadf";

export async function GET(request: NextRequest) {
  if (request.nextUrl.searchParams.get("key") !== SECRET) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }
  const uid = request.nextUrl.searchParams.get("uid") || DEFAULT_UID;
  const out: Record<string, unknown> = { uid, jobsStoreEnabled: jobsStoreEnabled() };
  try {
    const supabase = createServiceClient();
    const [prefsRes, candRes, actsRes, stateRes] = await Promise.all([
      supabase.from("user_preferences").select("*").eq("user_id", uid).maybeSingle(),
      supabase.from("candidate_profiles").select("*").eq("user_id", uid).maybeSingle(),
      supabase.from("job_actions").select("*").eq("user_id", uid),
      supabase.from("user_radar_state").select("last_opened_at").eq("user_id", uid).maybeSingle(),
    ]);
    const profile = buildRadarProfile(uid, prefsRes.data as UserPreferences | null, candRes.data as CandidateProfile | null);
    const actions = (actsRes.data as JobAction[]) || [];
    const radarState = (stateRes.data as { last_opened_at: string | null } | null) ?? null;
    const now = new Date();
    const { intensity } = resolveIntensityForUser(prefsRes.data as UserPreferences | null, radarState, actions, profile.targetCompanies.length > 0, now);
    out.actionsCount = actions.length;

    // 1) 单独测召回（最可疑），带计时
    const t0 = Date.now();
    try {
      const recall = await recallOpportunityCandidates(profile, now, supabase);
      out.recall = { ok: true, rows: recall.jobs.length, capped: recall.capped, ms: Date.now() - t0 };
    } catch (e) {
      out.recall = { ok: false, ms: Date.now() - t0, error: (e as Error).message, stack: (e as Error).stack?.split("\n").slice(0, 6) };
    }

    // 2) 完整 feed
    const t1 = Date.now();
    try {
      const feed = await buildOpportunityFeed(supabase, profile, actions, radarState, { surface: "today", intensity, now });
      out.feed = { ok: true, ms: Date.now() - t1, counts: feed.counts };
    } catch (e) {
      out.feed = { ok: false, ms: Date.now() - t1, error: (e as Error).message, stack: (e as Error).stack?.split("\n").slice(0, 8) };
    }
    return NextResponse.json(out);
  } catch (e) {
    out.fatal = { error: (e as Error).message, stack: (e as Error).stack?.split("\n").slice(0, 8) };
    return NextResponse.json(out, { status: 500 });
  }
}

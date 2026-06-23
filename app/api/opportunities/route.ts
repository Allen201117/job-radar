// 今日机会 Feed（§7.1）：读 profile/preferences/actions/radar state → buildOpportunityFeed。
// GET 不更新 last_opened_at（那是 /api/radar/open 的事）。
import { NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { buildRadarProfile } from "@/lib/opportunities/profile";
import { buildOpportunityFeed } from "@/lib/opportunities/service";
import type { UserPreferences, CandidateProfile, JobAction } from "@/lib/types";

export const runtime = "nodejs";

export async function GET() {
  const auth = await requireUser();
  if (auth.error) return auth.error;
  const { supabase, user } = auth;

  const [prefsRes, candRes, actsRes, stateRes] = await Promise.all([
    supabase.from("user_preferences").select("*").eq("user_id", user.id).maybeSingle(),
    supabase.from("candidate_profiles").select("*").eq("user_id", user.id).maybeSingle(),
    supabase.from("job_actions").select("*").eq("user_id", user.id),
    supabase.from("user_radar_state").select("last_opened_at").eq("user_id", user.id).maybeSingle(),
  ]);

  const profile = buildRadarProfile(
    user.id,
    prefsRes.data as UserPreferences | null,
    candRes.data as CandidateProfile | null,
  );
  const actions = (actsRes.data as JobAction[]) || [];
  const radarState = (stateRes.data as { last_opened_at: string | null } | null) ?? null;

  try {
    const feed = await buildOpportunityFeed(supabase, profile, actions, radarState, { surface: "today" });
    return NextResponse.json({ ok: true, ...feed });
  } catch (e) {
    console.error("[opportunities] feed build failed:", (e as Error).message);
    return NextResponse.json({ ok: false, error: "feed_unavailable" }, { status: 503 });
  }
}

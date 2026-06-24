import { redirect } from "next/navigation";
import Navbar from "@/components/Navbar";
import { EmptyPanel, MetricTile, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import { buildRadarProfile, profileReadiness } from "@/lib/opportunities/profile";
import { resolveIntensityForUser } from "@/lib/opportunities/intensity";
import { buildOpportunityFeed } from "@/lib/opportunities/service";
import type { OpportunityFeed } from "@/lib/opportunities/types";
import type { CandidateProfile, JobAction, UserPreferences } from "@/lib/types";
import TodayClient, { OnboardingPanel } from "../today-client";
import { Broadcast, CheckCircle, Crosshair, Sparkle } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

const HERO = {
  eyebrow: "今日机会",
  title: "今天值得处理的官方岗位",
  description:
    "系统已按你的目标、简历和岗位新鲜度完成筛选。先处理最相关的，再决定是否扩大搜索。",
};

export default async function TodayPage() {
  const user = await getRequestUser();
  if (!user) redirect("/login?next=/today");

  const supabase = await createServerSupabase();
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
  const readiness = profileReadiness(profile);

  // 画像不完整 → onboarding（不展示任何岗位）
  if (!readiness.ready) {
    return (
      <div className="min-h-screen bg-editorial">
        <Navbar />
        <ProductPage>
          <ProductHero eyebrow={HERO.eyebrow} title={HERO.title} description={HERO.description} icon={Broadcast} />
          <section className="mt-8">
            <OnboardingPanel missingContent={readiness.missingContent} missingLocation={readiness.missingLocation} />
          </section>
        </ProductPage>
      </div>
    );
  }

  // 画像就绪 → SSR 构建机会 Feed（先渲染，radar/open 由客户端首渲后异步记录，不提前清零当次新增）
  const now = new Date();
  const actions = (actsRes.data as JobAction[]) || [];
  const radarState = (stateRes.data as { last_opened_at: string | null } | null) ?? null;
  const { intensity } = resolveIntensityForUser(
    prefsRes.data as UserPreferences | null,
    radarState,
    actions,
    profile.targetCompanies.length > 0,
    now,
  );

  let feed: OpportunityFeed | null = null;
  try {
    feed = await buildOpportunityFeed(supabase, profile, actions, radarState, { surface: "today", intensity, now });
  } catch (e) {
    console.error("[today] feed build failed:", (e as Error).message);
  }

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero eyebrow={HERO.eyebrow} title={HERO.title} description={HERO.description} icon={Broadcast}>
          {feed && (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
              <MetricTile icon={Sparkle} label="关键提醒" value={feed.counts.critical} tone="sky" />
              <MetricTile icon={Crosshair} label="对口机会" value={feed.counts.main} tone="lime" />
              <MetricTile
                icon={CheckCircle}
                label="最近确认仍在招"
                value={feed.counts.by_signal.STILL_OPEN ?? 0}
                tone="white"
              />
            </div>
          )}
        </ProductHero>

        <section className="mt-8">
          {!feed ? (
            <EmptyPanel
              title="机会队列暂时无法更新"
              description="机会队列暂时无法更新，请稍后重试。你的偏好和历史操作没有丢失。"
            />
          ) : (
            <TodayClient feed={feed} />
          )}
        </section>
      </ProductPage>
    </div>
  );
}

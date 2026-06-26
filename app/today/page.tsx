import { Suspense } from "react";
import { redirect } from "next/navigation";
import Navbar from "@/components/Navbar";
import { EmptyPanel, MetricTile, ProductHero, ProductPage } from "@/components/ProductChrome";
import { JobListSkeleton, MetricTilesSkeleton } from "@/components/Skeletons";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import { buildRadarProfile, profileReadiness } from "@/lib/opportunities/profile";
import { resolveIntensityForUser } from "@/lib/opportunities/intensity";
import { buildOpportunityFeed } from "@/lib/opportunities/service";
import type { OpportunityFeed } from "@/lib/opportunities/types";
import type { CandidateProfile, JobAction, UserPreferences } from "@/lib/types";
import TodayClient, { OnboardingPanel } from "../today-client";
import { Broadcast, CheckCircle, Crosshair, Sparkle } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";
// 须 ≥ jobs 池 statement_timeout(25s)：否则慢的跨区召回会先撞函数时限被杀（平台 504、不被页面 catch），
// 用户看到的就不是「机会队列暂时无法更新」而是白屏错误页。给足余量到 30s（plan 支持，见 /api/jobs/search=60）。
export const maxDuration = 30;

const HERO = {
  eyebrow: "今日机会",
  title: "今天值得处理的官方岗位",
  description:
    "系统已按你的目标、简历和岗位新鲜度完成筛选。先处理最相关的，再决定是否扩大搜索。",
};

const METRICS_GRID = "grid grid-cols-2 gap-3 lg:grid-cols-3";

// 流式：先出页面骨架（导航 + 标题），慢的跨区机会召回单独在 Suspense 边界里流入，不再阻塞整页。
// metrics 与 feed 共用同一次 feed 构建（一个 promise 分给两个边界），构建失败时退化为 null（不双抛）。
export default async function TodayPage() {
  const user = await getRequestUser();
  if (!user) redirect("/login?next=/today");

  const supabase = await createServerSupabase();
  // 决定 onboarding / 强度只需这几张「按用户」的小表，秒回——shell 在这之后即可渲染。
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

  // 画像就绪 → 启动机会 Feed 构建但**不在此 await**（跨区召回慢）；交给下面两个 Suspense 边界流式取用。
  // radar/open 由客户端首渲后异步记录，不提前清零当次新增。
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

  // 一次构建、两处取用：包一层 catch 让 promise 永不 reject（失败=null），避免两个边界各自抛错。
  const feedPromise: Promise<OpportunityFeed | null> = buildOpportunityFeed(
    supabase,
    profile,
    actions,
    radarState,
    { surface: "today", intensity, now },
  ).catch((e) => {
    console.error("[today] feed build failed:", (e as Error).message);
    return null;
  });

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero eyebrow={HERO.eyebrow} title={HERO.title} description={HERO.description} icon={Broadcast}>
          <Suspense fallback={<MetricTilesSkeleton count={3} gridClassName={METRICS_GRID} />}>
            <TodayMetrics feedPromise={feedPromise} />
          </Suspense>
        </ProductHero>

        <section className="mt-8">
          <Suspense fallback={<JobListSkeleton count={6} />}>
            <TodayFeed feedPromise={feedPromise} />
          </Suspense>
        </section>
      </ProductPage>
    </div>
  );
}

// 指标区：随 feed 流入。构建失败则不出指标（错误提示交给下方 feed 区，避免重复报错）。
async function TodayMetrics({ feedPromise }: { feedPromise: Promise<OpportunityFeed | null> }) {
  const feed = await feedPromise;
  if (!feed) return null;
  return (
    <div className={METRICS_GRID}>
      <MetricTile icon={Sparkle} label="关键提醒" value={feed.counts.critical} tone="sky" />
      <MetricTile icon={Crosshair} label="对口机会" value={feed.counts.main} tone="lime" />
      <MetricTile
        icon={CheckCircle}
        label="最近确认仍在招"
        value={feed.counts.by_signal.STILL_OPEN ?? 0}
        tone="white"
      />
    </div>
  );
}

// 机会列表区：随 feed 流入。构建失败 → 友好兜底（偏好/历史未丢）。
async function TodayFeed({ feedPromise }: { feedPromise: Promise<OpportunityFeed | null> }) {
  const feed = await feedPromise;
  if (!feed) {
    return (
      <EmptyPanel
        title="机会队列暂时无法更新"
        description="机会队列暂时无法更新，请稍后重试。你的偏好和历史操作没有丢失。"
      />
    );
  }
  return <TodayClient feed={feed} />;
}

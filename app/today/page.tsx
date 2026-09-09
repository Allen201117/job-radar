import { Suspense } from "react";
import { redirect } from "next/navigation";
import Navbar from "@/components/Navbar";
import { EmptyPanel, ProductHero, ProductPage } from "@/components/ProductChrome";
import { JobListSkeleton } from "@/components/Skeletons";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import { buildRadarProfile, profileReadiness } from "@/lib/opportunities/profile";
import { loadRadarContext } from "@/lib/opportunities/context";
import { resolveIntensityForUser } from "@/lib/opportunities/intensity";
import { buildOpportunityFeed } from "@/lib/opportunities/service";
import { getPopularFeed, type PopularFeed } from "@/lib/popular-feed";
import type { OpportunityFeed } from "@/lib/opportunities/types";
import TodayClient, { OnboardingPanel } from "../today-client";
import TodayPopularClient from "../today-popular-client";
import { TODAY_HERO } from "./hero";
import { Broadcast } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";
// 须 ≥ jobs 池 statement_timeout(25s)：否则慢的跨区召回会先撞函数时限被杀（平台 504、不被页面 catch），
// 用户看到的就不是「机会队列暂时无法更新」而是白屏错误页。给足余量到 30s（plan 支持，见 /api/jobs/search=60）。
export const maxDuration = 30;

/** 页面主体所需的一切；一次构建、各 Suspense 边界共用。构建过程中的失败都在内部兜住，promise 永不 reject。 */
type TodayBundle = {
  readiness: ReturnType<typeof profileReadiness>;
  /** 画像未就绪时为 null（此时不发个人召回，改走 popular 兜底）。 */
  feed: OpportunityFeed | null;
  /** 画像未就绪时的「热门在招」兜底清单；画像就绪时为 null（不白付一次查询）。 */
  popular: PopularFeed | null;
  /** 用户已存过的目标行业（兜底位的「设为我的行业」用它避免重复追问）。 */
  savedIndustries: string[];
  /** shell 之前那 4 条 Supabase(悉尼) 并行查询耗时，诊断用。 */
  userRowsMs: number;
};

/**
 * 取「按用户」的小表 + 构建机会 Feed。
 *
 * ⚠️ 这个函数**不能**在页面组件里 await —— 它开头那 4 条 Supabase 查询要打到悉尼，
 * live 实测 1,169ms（载荷合计才 24KB，纯跨洋 RTT）。页面组件一 await 它，导航 + 页头 + 骨架
 * 就全被这 1.2s 拖住；而它们本来不需要任何用户数据就能画。所以整块放进 Suspense 边界里流入。
 */
async function loadTodayBundle(
  supabase: Awaited<ReturnType<typeof createServerSupabase>>,
  userId: string,
  now: Date,
): Promise<TodayBundle> {
  const tUserRows = performance.now();
  // 读取失败必须抛（见 lib/opportunities/context.ts）：外层 .catch 会把它变成「暂时无法更新，
  // 请稍后重试」的错误面板。**不能**像以前那样把失败当成空偏好继续往下走——那会静默丢掉
  // 排除词与已处理记录，还会把老用户打回填表引导页。
  const ctx = await loadRadarContext(supabase, userId);
  const userRowsMs = Math.round(performance.now() - tUserRows);

  const profile = buildRadarProfile(userId, ctx.preferences, ctx.candidate);
  const readiness = profileReadiness(profile);
  // 画像未就绪 → 不做个人召回（没有目标可召回），改取与用户无关、跨请求共享缓存的「热门在招」。
  // 这是新用户的第一屏：给不出对口机会，也要给得出**能点开的真岗位**，而不是一堵表单墙。
  if (!readiness.ready) {
    return {
      readiness,
      feed: null,
      popular: await getPopularFeed(),
      savedIndustries: profile.targetIndustries,
      userRowsMs,
    };
  }

  // radar/open 由客户端首渲后异步记录，不提前清零当次新增。
  const actions = ctx.actions;
  const radarState = ctx.radarState;
  const { intensity } = resolveIntensityForUser(
    ctx.preferences,
    radarState,
    actions,
    profile.targetCompanies.length > 0,
    now,
  );

  const feed = await buildOpportunityFeed(supabase, profile, actions, radarState, {
    surface: "today",
    intensity,
    now,
  }).catch((e) => {
    console.error("[today] feed build failed:", (e as Error).message);
    return null;
  });
  return { readiness, feed, popular: null, savedIndustries: profile.targetIndustries, userRowsMs };
}

// 流式：先出页面骨架（导航 + 标题），用户小表查询与慢的跨区机会召回都在 Suspense 边界里流入，不阻塞整页。
// hero narrative 与主体共用同一次构建（一个 promise 分给多个边界），构建失败时退化为 null（不双抛）。
export default async function TodayPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const tPageStart = performance.now();
  const sp = searchParams ? await searchParams : undefined;
  // 诊断开关：只有显式带 ?__timing=1 才把各阶段耗时渲染进页面，普通用户永远拿不到。
  const wantTiming = sp?.__timing === "1";

  const user = await getRequestUser();
  if (!user) redirect("/login?next=/today");

  const supabase = await createServerSupabase();
  // 故意不 await：见 loadTodayBundle 的注释。包 catch 让它永不 reject，避免多个边界各自抛错。
  const bundlePromise: Promise<TodayBundle | null> = loadTodayBundle(supabase, user.id, new Date()).catch(
    (e) => {
      console.error("[today] bundle load failed:", (e as Error).message);
      return null;
    },
  );

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        {/* 页头下原本挂着一条「今日已为你考察 1,348 个，替你剔除 1,274 个：已失效 · 不对口 · 信息不全」
            的计分板。2026-09-02 创始人明确要求下线：它把内部漏斗的中间数当卖点讲给用户听，
            而用户只关心「今天有什么值得投的」——「剔除 1,274 个」既不可验证，也容易让人觉得
            系统在自夸工作量。要衡量漏斗健康度请看 /admin/health，别放在用户面前。 */}
        <ProductHero
          eyebrow={TODAY_HERO.eyebrow}
          title={TODAY_HERO.title}
          icon={Broadcast}
        />

        <section className="mt-8">
          <Suspense fallback={<JobListSkeleton count={6} />}>
            <TodayBody bundlePromise={bundlePromise} />
          </Suspense>
        </section>
        {wantTiming && (
          // 放在最后一个 Suspense 边界里 → 它在主体完成后才 flush，因此能带上各阶段耗时，
          // 且它自身的 server_total_ms 就是「首字节之后还等了多久」。
          <Suspense fallback={null}>
            <TimingProbe bundlePromise={bundlePromise} tPageStart={tPageStart} />
          </Suspense>
        )}
      </ProductPage>
    </div>
  );
}

/** 诊断探针：仅 ?__timing=1 时渲染。输出隐藏的 JSON，供 curl 读取，不影响可见 UI。 */
async function TimingProbe({
  bundlePromise,
  tPageStart,
}: {
  bundlePromise: Promise<TodayBundle | null>;
  tPageStart: number;
}) {
  const bundle = await bundlePromise;
  const payload = {
    user_rows_ms: bundle?.userRowsMs ?? null, // shell 之外那 4 条 Supabase(悉尼) 并行查询
    server_total_ms: Math.round(performance.now() - tPageStart), // 页面函数内总耗时（到主体完成）
    feed: bundle?.feed?.timing ?? null, // buildOpportunityFeed 内部分解
  };
  return (
    <script
      type="application/json"
      id="jr-timing"
      // 纯诊断数据（全是毫秒数与条数，无任何用户信息）；type 非 JS，浏览器不执行。
      dangerouslySetInnerHTML={{ __html: JSON.stringify(payload) }}
    />
  );
}

// 主体区：画像不完整 → onboarding（不展示任何岗位）；就绪 → 机会列表；构建失败 → 友好兜底（偏好/历史未丢）。
async function TodayBody({ bundlePromise }: { bundlePromise: Promise<TodayBundle | null> }) {
  const bundle = await bundlePromise;
  if (!bundle) {
    return (
      <EmptyPanel
        tone="error"
        title="机会队列暂时无法更新"
        description="机会队列暂时无法更新，请稍后重试。你的偏好和历史操作没有丢失。"
      />
    );
  }
  if (!bundle.readiness.ready) {
    // 有热门岗位就先给东西看（细引导条在清单顶部）；一条都取不到才退回纯引导页。
    const popular = bundle.popular;
    if (popular && popular.jobs.length > 0) {
      return (
        <TodayPopularClient
          items={popular.jobs.map((p) => ({ job: p.job, industry: p.industry }))}
          industries={popular.industries}
          savedIndustries={bundle.savedIndustries}
        />
      );
    }
    return (
      <OnboardingPanel
        missingContent={bundle.readiness.missingContent}
        missingLocation={bundle.readiness.missingLocation}
      />
    );
  }
  if (!bundle.feed) {
    return (
      <EmptyPanel
        tone="error"
        title="机会队列暂时无法更新"
        description="机会队列暂时无法更新，请稍后重试。你的偏好和历史操作没有丢失。"
      />
    );
  }
  return <TodayClient feed={bundle.feed} />;
}

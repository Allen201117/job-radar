import { Suspense } from "react";
import { redirect } from "next/navigation";
import Navbar from "@/components/Navbar";
import { EmptyPanel, ProductHero, ProductPage } from "@/components/ProductChrome";
import { JobListSkeleton } from "@/components/Skeletons";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import { buildRadarProfile, profileReadiness } from "@/lib/opportunities/profile";
import { resolveIntensityForUser } from "@/lib/opportunities/intensity";
import { buildOpportunityFeed } from "@/lib/opportunities/service";
import type { OpportunityFeed } from "@/lib/opportunities/types";
import type { CandidateProfile, JobAction, UserPreferences } from "@/lib/types";
import TodayClient, { OnboardingPanel } from "../today-client";
import { Broadcast } from "@phosphor-icons/react/ssr";

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

/** 页面主体所需的一切；一次构建、各 Suspense 边界共用。构建过程中的失败都在内部兜住，promise 永不 reject。 */
type TodayBundle = {
  readiness: ReturnType<typeof profileReadiness>;
  /** 画像未就绪时为 null（onboarding 不展示任何岗位，也就不该发召回）。 */
  feed: OpportunityFeed | null;
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
  const [prefsRes, candRes, actsRes, stateRes] = await Promise.all([
    supabase.from("user_preferences").select("*").eq("user_id", userId).maybeSingle(),
    supabase.from("candidate_profiles").select("*").eq("user_id", userId).maybeSingle(),
    supabase.from("job_actions").select("*").eq("user_id", userId),
    supabase.from("user_radar_state").select("last_opened_at").eq("user_id", userId).maybeSingle(),
  ]);
  const userRowsMs = Math.round(performance.now() - tUserRows);

  const profile = buildRadarProfile(
    userId,
    prefsRes.data as UserPreferences | null,
    candRes.data as CandidateProfile | null,
  );
  const readiness = profileReadiness(profile);
  if (!readiness.ready) return { readiness, feed: null, userRowsMs };

  // radar/open 由客户端首渲后异步记录，不提前清零当次新增。
  const actions = (actsRes.data as JobAction[]) || [];
  const radarState = (stateRes.data as { last_opened_at: string | null } | null) ?? null;
  const { intensity } = resolveIntensityForUser(
    prefsRes.data as UserPreferences | null,
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
  return { readiness, feed, userRowsMs };
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
        <ProductHero eyebrow={HERO.eyebrow} title={HERO.title} description={HERO.description} icon={Broadcast}>
          <Suspense fallback={null}>
            <TodayMetrics bundlePromise={bundlePromise} />
          </Suspense>
        </ProductHero>

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

// 价值叙事区：随主体流入。构建失败或画像未就绪则不出文案（错误提示交给下方主体区，避免重复报错）。
async function TodayMetrics({ bundlePromise }: { bundlePromise: Promise<TodayBundle | null> }) {
  const feed = (await bundlePromise)?.feed;
  if (!feed) return null;
  // 计分板置换：把系统替用户做掉的过滤劳动说出来，而不是只报正向计数。
  const f = feed.counts.filtered;
  const screened = feed.counts.screened ?? 0;
  const removed = f ? f.inactive + f.mismatch + f.low_score + f.thin : 0;
  if (!(screened > 0 && removed > 0 && f)) return null;
  return (
    <p className="text-[13px] leading-5 text-[#6b655a] dark:text-[#b6ad9d]">
      今日已为你考察 {screened.toLocaleString()} 个在库岗位，替你剔除 {removed.toLocaleString()} 个：
      已失效 {f.inactive.toLocaleString()} · 不对口 {(f.mismatch + f.low_score).toLocaleString()} · 信息不全{" "}
      {f.thin.toLocaleString()}——剩下的才值得你花时间。
    </p>
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

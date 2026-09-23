import { Suspense } from "react";
import { redirect } from "next/navigation";
import { after } from "next/server";
import Navbar from "@/components/Navbar";
import { EmptyPanel, ProductHero, ProductPage } from "@/components/ProductChrome";
import { deriveCountryCode } from "@/lib/geo";
import { JobListSkeleton } from "@/components/Skeletons";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import { buildRadarProfile, profileReadiness } from "@/lib/opportunities/profile";
import { loadRadarContext, type RadarContextStats } from "@/lib/opportunities/context";
import { kb } from "@/lib/jobs-store/row-bytes";
import { resolveIntensityForUser } from "@/lib/opportunities/intensity";
import { buildOpportunityFeed } from "@/lib/opportunities/service";
import { readRecallSnapshotSafe, writeRecallSnapshot } from "@/lib/jobs-store/recall-snapshot";
import { refreshRecallSnapshot, RECALL_SNAPSHOT_REFRESH_AFTER_MS, type RecallResult } from "@/lib/jobs-store/opportunities";
import { jobsStoreEnabled } from "@/lib/jobs-store/read";
import { recallActionedJobIds } from "@/lib/opportunities/recall-snapshot-upkeep";
import { getPopularFeed, type PopularFeed } from "@/lib/popular-feed";
import type { OpportunityFeed } from "@/lib/opportunities/types";
import type { RadarProfile } from "@/lib/opportunities/types";
import type { CandidateProfile, UserPreferences } from "@/lib/types";
import {
  planWidenings,
  widenProfile,
  summarizeCriteria,
  type EmptyWidening,
} from "@/lib/opportunities/empty-diagnosis";
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
  /** 选了海外/全都要却在海外池里 0 岗（目标城市全是国内、无英文简历）→ 已按国内重算，页面要告诉他。 */
  scopeFallback: "domestic" | null;
  /** 0 岗且不是范围错配时：放宽哪一维之后真的有机会（数字来自同一条召回链路重算，不另写 count SQL）。null = 没有可放宽的维度或放宽了也还是 0。 */
  emptyWidening: EmptyWidening | null;
  /** 用户当前叠着的筛选条件，空态照原样念回去——0 岗几乎总是「几个条件叠太窄」，而他看不见自己叠了什么。 */
  criteria: string[];
  /** 页面级分段账本（见 TodayBundleTiming）。 */
  timing: TodayBundleTiming;
};

/**
 * `[today-page]` 账本：**feed 之外**那几段。
 *
 * 为什么非有不可：`[today-feed]` 只覆盖 buildOpportunityFeed 内部，线上 2026-09-18 02:35 实测它
 * `total=1,880ms`，而真实浏览器里整页流完要 **6.5s**——2/3 的时间没有任何人能指认。
 * 缺的那几段就是这里记的：画像读取（4 条悉尼查询）、海外→国内兜底重算、热门兜底、
 * 以及**交给浏览器的 props 有多少字节**（HTML 里它出现两次：JobCard 渲染出的 markup + RSC payload）。
 *
 * 判读法（照 /campus 那次的先例：`TTFB 快 + responseEnd 慢` = 生成/传输页面本身的问题）：
 *   · 浏览器 responseEnd − (TTFB + total_ms) ≈ **传输 + React 序列化**，用 props_kb 去解释它；
 *   · TTFB 本身偏大 ≈ **函数冷启动**（容器启动 + 首次建库连接），这一段代码里改不掉。
 */
type TodayBundleTiming = {
  /** loadRadarContext：4 条 Supabase(悉尼) 并行查询的墙钟与回传字节。 */
  ctxMs: number;
  ctxBytes: number;
  ctxActions: number;
  /** buildOpportunityFeed 端到端（其内部分解见 `[today-feed]`）。 */
  feedMs: number;
  /** 求职范围错配时按国内重算的**第二次** feed；没触发为 0。 */
  fallbackMs: number;
  /** 0 岗时为了拿「放宽后有几个」重算的 feed（最多 2 次，每次一维）；没触发为 0。 */
  widenMs: number;
  /** 画像未就绪时的「热门在招」（跨请求 unstable_cache）；没触发为 0。 */
  popularMs: number;
  /** loadTodayBundle 端到端。 */
  bundleMs: number;
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
  const tBundleStart = performance.now();
  // 召回快照与悉尼那 4 条查询**并行**发出：它只要 user_id，而它顺手预热的堆块正是紧接着召回要读的
  // （见 lib/jobs-store/recall-snapshot.readRecallSnapshot）。永不 reject；关掉开关 / 没配香港库时不发。
  const snapshotPromise =
    jobsStoreEnabled() && String(process.env.TODAY_RECALL_SNAPSHOT || "").toLowerCase() !== "off"
      ? readRecallSnapshotSafe(userId)
      : Promise.resolve(null);
  const ctxStats: RadarContextStats = { ms: 0, bytes: 0, actionRows: 0 };
  const timing: TodayBundleTiming = {
    ctxMs: 0, ctxBytes: 0, ctxActions: 0, feedMs: 0, fallbackMs: 0, widenMs: 0, popularMs: 0, bundleMs: 0,
  };
  // 读取失败必须抛（见 lib/opportunities/context.ts）：外层 .catch 会把它变成「暂时无法更新，
  // 请稍后重试」的错误面板。**不能**像以前那样把失败当成空偏好继续往下走——那会静默丢掉
  // 排除词与已处理记录，还会把老用户打回填表引导页。
  const ctx = await loadRadarContext(supabase, userId, ctxStats);
  timing.ctxMs = ctxStats.ms;
  timing.ctxBytes = ctxStats.bytes;
  timing.ctxActions = ctxStats.actionRows;

  const profile = buildRadarProfile(userId, ctx.preferences, ctx.candidate);
  const readiness = profileReadiness(profile);
  // 画像未就绪 → 不做个人召回（没有目标可召回），改取与用户无关、跨请求共享缓存的「热门在招」。
  // 这是新用户的第一屏：给不出对口机会，也要给得出**能点开的真岗位**，而不是一堵表单墙。
  if (!readiness.ready) {
    const tPopular = performance.now();
    const popular = await getPopularFeed();
    timing.popularMs = performance.now() - tPopular;
    timing.bundleMs = performance.now() - tBundleStart;
    return {
      readiness,
      feed: null,
      popular,
      savedIndustries: profile.targetIndustries,
      timing,
      scopeFallback: null,
      emptyWidening: null,
      criteria: [],
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

  const tFeed = performance.now();
  let recallInfo: Pick<RecallResult, "snapshot" | "snapshotWrite"> | null = null;
  let feed = await buildOpportunityFeed(supabase, profile, actions, radarState, {
    surface: "today",
    intensity,
    now,
    recallSnapshot: { snapshot: snapshotPromise, onRecall: (info) => { recallInfo = info; } },
  }).catch((e) => {
    console.error("[today] feed build failed:", (e as Error).message);
    return null;
  });
  timing.feedMs = performance.now() - tFeed;
  scheduleRecallSnapshotUpkeep(userId, profile, actions, recallInfo);
  // 求职范围错配兜底（2026-09-17 走查 44 个真实用户，4 个推荐页 0 岗全栽在这）：顶栏一点「海外」，
  // 画像却是「深圳 + 行政 + 没有英文简历」→ 海外池里当然一个都没有，页面就空着、不说为什么。
  // 只在「海外池确实 0 岗 + 目标城市全是国内 + 没英文简历」三件同时成立时按国内重算一次，并把原因交给页面说清。
  let scopeFallback: TodayBundle["scopeFallback"] = null;
  if (feed && feedIsEmpty(feed) && shouldFallbackToDomestic(profile, ctx.candidate)) {
    const tFallback = performance.now();
    const domesticProfile = buildRadarProfile(userId, { ...(ctx.preferences as UserPreferences), job_scope: "domestic" }, ctx.candidate);
    const domesticFeed = await buildOpportunityFeed(supabase, domesticProfile, actions, radarState, {
      surface: "today",
      intensity,
      now,
    }).catch(() => null);
    timing.fallbackMs = performance.now() - tFallback;
    if (domesticFeed && !feedIsEmpty(domesticFeed)) {
      feed = domesticFeed;
      scopeFallback = "domestic";
    }
  }
  // 仍然 0 岗（且不是范围错配那种、已经回落过的）→ 找出「松哪一个条件就有货」，把真原因交给页面说。
  // 为什么要多跑一次召回而不是另写一条 count SQL：提示里的数字必须与用户松了条件后**真能看到**的
  // 一致，自己另算一套就会出现「说有 12 个、点进去 3 个」，那比不给数字更伤信任。
  // 成本可控：0 岗是低频（2026-09-18 走查 44 个真实用户里 3 个），且最多重算 2 次、第一次有货就停。
  let emptyWidening: EmptyWidening | null = null;
  if (feed && feedIsEmpty(feed) && !scopeFallback) {
    const tWiden = performance.now();
    for (const plan of planWidenings(profile)) {
      const widenedFeed = await buildOpportunityFeed(
        supabase,
        widenProfile(profile, plan.dim),
        actions,
        radarState,
        { surface: "today", intensity, now },
      ).catch(() => null);
      const count = widenedFeed?.counts?.total ?? 0;
      if (count > 0) {
        emptyWidening = { ...plan, count };
        break;
      }
    }
    timing.widenMs = performance.now() - tWiden;
  }
  timing.bundleMs = performance.now() - tBundleStart;
  return {
    readiness,
    feed,
    popular: null,
    savedIndustries: profile.targetIndustries,
    timing,
    scopeFallback,
    emptyWidening,
    criteria: summarizeCriteria(profile),
  };
}

/**
 * 快照的写与刷新都放到**响应之后**（after）：写库、以及刷新时那一次冷态可能好几秒的现跑召回，都不许进请求路径。
 *   · 这次是现跑（没快照 / 偏好改了 / 快照过期）→ 把现跑结果原样写成快照，下次打开直接命中；
 *   · 这次用了快照、但它已超过 1 小时 → 顺手现跑一次刷新（新岗本来就靠「首见晚于快照」实时补上，
 *     刷新是为了让「快照之后才掉出去的岗」有人补位，偏差不随快照变老一路累积）。
 * 失败只记日志：快照只是加速层，写不进去下次无非再现跑一次。
 */
function scheduleRecallSnapshotUpkeep(
  userId: string,
  profile: RadarProfile,
  actions: Array<{ job_id: string; action: string }>,
  info: Pick<RecallResult, "snapshot" | "snapshotWrite"> | null,
): void {
  if (!info) return;
  // after() 本身出错（不在请求作用域里等）也只能记日志：这里在 bundle 的 promise 链上，
  // 一抛就会把整页打成「机会队列暂时无法更新」——为一个加速层赔上页面不值。
  const later = (task: () => Promise<unknown>) => {
    try {
      after(task);
    } catch (e) {
      console.warn("[recall-snapshot] after() 不可用，本次不维护快照：", (e as Error).message);
    }
  };
  const write = info.snapshotWrite;
  if (write) {
    later(() =>
      writeRecallSnapshot(userId, write).catch((e) =>
        console.warn("[recall-snapshot] 回写失败：", (e as Error).message),
      ),
    );
    return;
  }
  const ageMs = info.snapshot?.used ? info.snapshot.ageMs : null;
  if (ageMs == null || ageMs <= RECALL_SNAPSHOT_REFRESH_AFTER_MS) return;
  later(() =>
    refreshRecallSnapshot(userId, profile, new Date(), recallActionedJobIds(actions), "request").catch((e) =>
      console.warn("[recall-snapshot] 刷新失败：", (e as Error).message),
    ),
  );
}

function feedIsEmpty(feed: OpportunityFeed): boolean {
  return (feed.counts?.total ?? Object.values(feed.sections).reduce((n, arr) => n + arr.length, 0)) === 0;
}

function shouldFallbackToDomestic(profile: RadarProfile, candidate: CandidateProfile | null): boolean {
  if (profile.jobScope === "domestic") return false;
  if (candidate?.has_en_resume) return false;
  const cities = profile.targetLocations;
  return cities.length > 0 && cities.every((c: string) => deriveCountryCode(c) === "CN");
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
  // shell（导航 + 页头 + 骨架）此刻就能 flush —— 这一段约等于浏览器看到的 TTFB 里**属于本函数**的部分。
  // 它与真实 TTFB 的差 = 平台冷启动（容器启动 + bundle 加载），代码里改不掉。
  const shellMs = performance.now() - tPageStart;

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        {/* 页头下原本挂着一条「今日已为你考察 1,348 个，替你剔除 1,274 个：已失效 · 不对口 · 信息不全」
            的计分板。2026-09-02 创始人明确要求下线：它把内部漏斗的中间数当卖点讲给用户听，
            而用户只关心「今天有什么值得投的」——「剔除 1,274 个」既不可验证，也容易让人觉得
            系统在自夸工作量。要衡量漏斗健康度请看 /admin/health，别放在用户面前。 */}
        <ProductHero
          title={TODAY_HERO.title}
          icon={Broadcast}
        />

        <section className="mt-8">
          <Suspense fallback={<JobListSkeleton count={6} />}>
            <TodayBody bundlePromise={bundlePromise} tPageStart={tPageStart} shellMs={shellMs} userId={user.id} />
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
    user_rows_ms: bundle ? Math.round(bundle.timing.ctxMs) : null, // shell 之外那 4 条 Supabase(悉尼) 并行查询
    page: bundle ? roundTiming(bundle.timing) : null, // 页面级分段（feed 之外的那几段）
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

function roundTiming(t: TodayBundleTiming) {
  return {
    ctx_ms: Math.round(t.ctxMs),
    ctx_kb: kb(t.ctxBytes),
    ctx_actions: t.ctxActions,
    feed_ms: Math.round(t.feedMs),
    fallback_ms: Math.round(t.fallbackMs),
    widen_ms: Math.round(t.widenMs),
    popular_ms: Math.round(t.popularMs),
    bundle_ms: Math.round(t.bundleMs),
  };
}

/**
 * 交给浏览器的 props 有多少字节。**这是本页最该常开观测的数字**：
 * 它在 HTML 里出现两次（JobCard 渲染出的 markup + RSC payload），是「TTFB 很快、整页却要 6.5s」
 * 这个形态的第一嫌疑人。JSON.stringify 一遍约 1ms（React 紧接着还要做同样的事），相对 6.5s 是噪声。
 * 估算失败不许影响页面渲染。
 */
function payloadKb(value: unknown): number {
  try {
    return kb(Buffer.byteLength(JSON.stringify(value) ?? ""));
  } catch {
    return -1;
  }
}

// 主体区：画像不完整 → onboarding（不展示任何岗位）；就绪 → 机会列表；构建失败 → 友好兜底（偏好/历史未丢）。
async function TodayBody({
  bundlePromise,
  tPageStart,
  shellMs,
  userId,
}: {
  bundlePromise: Promise<TodayBundle | null>;
  tPageStart: number;
  shellMs: number;
  userId: string;
}) {
  const bundle = await bundlePromise;
  // 一行可 grep 的页面级账本（与 `[today-feed]` / `[today-recall]` 同款；/today 要登录，外部 curl 不到）。
  // user 只留前 8 位：够把两条日志串成一次请求，又不是可用的用户标识。
  {
    const t = bundle?.timing;
    const cards = bundle?.feed
      ? Object.values(bundle.feed.sections).reduce((n, arr) => n + arr.length, 0)
      : (bundle?.popular?.jobs.length ?? 0);
    console.log(
      `[today-page] user=${userId.slice(0, 8)} ready=${bundle?.readiness.ready ? 1 : 0} ` +
        `shell_ms=${Math.round(shellMs)} ctx_ms=${Math.round(t?.ctxMs ?? 0)} ctx_kb=${kb(t?.ctxBytes ?? 0)} ` +
        `ctx_actions=${t?.ctxActions ?? 0} feed_ms=${Math.round(t?.feedMs ?? 0)} ` +
        `fallback_ms=${Math.round(t?.fallbackMs ?? 0)} widen_ms=${Math.round(t?.widenMs ?? 0)} popular_ms=${Math.round(t?.popularMs ?? 0)} ` +
        `bundle_ms=${Math.round(t?.bundleMs ?? 0)} cards=${cards} ` +
        `props_kb=${payloadKb(bundle?.feed ?? bundle?.popular ?? null)} ` +
        `total_ms=${Math.round(performance.now() - tPageStart)}`,
    );
  }
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
  return (
    <>
      {bundle.scopeFallback === "domestic" && (
        <p className="t-body-sm ink-2 mb-3 rounded-xl border border-black/[0.08] px-4 py-3 dark:border-white/[0.12]">
          你把求职范围设成了海外，但目标城市都在国内、也还没有英文简历，海外岗位里没有匹配的机会。
          下面按国内范围展示；要看海外机会，先在个人中心补一份英文简历。
        </p>
      )}
      <TodayClient
        feed={bundle.feed}
        emptyWidening={bundle.emptyWidening}
        criteria={bundle.criteria}
      />
    </>
  );
}

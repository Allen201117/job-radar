"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import Link from "next/link";
import JobCard from "@/components/JobCard";
import { jobActionToastText } from "@/components/ActionToast";
import { track } from "@/lib/track";
import type { ScoredJob } from "@/lib/types";
import type { Opportunity, OpportunityFeed, OpportunitySignal } from "@/lib/opportunities/types";
import { WIDEN_DIM_LABEL, type EmptyWidening } from "@/lib/opportunities/empty-diagnosis";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui";
import {
  todayReducer,
  initTodayState,
  type PrimaryAction,
  type SectionKey,
} from "@/lib/opportunities/today-reducer";

type DisplaySectionKey = Exclude<SectionKey, "waiting">;

const SECTION_META: Record<DisplaySectionKey, { title: string; subtitle?: string }> = {
  critical: { title: "关键提醒", subtitle: "截止与关闭优先处理" },
  main: {
    title: "对口机会",
    subtitle: "最贴合你的目标",
  },
  explore: { title: "可以拓展看看", subtitle: "相关方向，按需查看" },
  momentum: { title: "本周招聘动量", subtitle: "近期持续放岗" },
};

const ORDER: DisplaySectionKey[] = ["critical", "main", "explore", "momentum"];

const ACTION_LABEL: Record<PrimaryAction, string> = {
  saved: "已收藏",
  applied: "已记为「已投递」",
  ignored: "已标记不适合",
};

// 距上次核验小时数（点击有效率埋点用）；null=从未核验。
function checkedAgeHours(lastCheckedAt: string | null): number | null {
  if (!lastCheckedAt) return null;
  const t = new Date(lastCheckedAt).getTime();
  if (Number.isNaN(t)) return null;
  return Math.round((Date.now() - t) / 3_600_000);
}

// Opportunity → JobCard 需要的 ScoredJob 形（match_* 仅为类型兼容，opportunity 变体不读它们）
function toScoredJob(opp: Opportunity): ScoredJob {
  return {
    ...(opp.job as ScoredJob),
    // Today uses explicit signal chips; suppress JobCard's separate age/status sentence here.
    last_seen_at: "",
    match_score: opp.score,
    matched_keywords: [],
    match_reasons: [],
    hidden_reason: null,
    user_action: opp.userAction,
  };
}

function visibleOpportunitySignals(opp: Opportunity): OpportunitySignal[] {
  return opp.signals
    .filter((s) => s.type !== "OPEN_UNVERIFIED")
    .map((s) => (s.type === "STILL_OPEN" ? { ...s, label: "仍在招" } : s));
}

// 画像不完整空状态（§4.3）：只引导设目标，不展示任何随机岗位。
export function OnboardingPanel({
  missingContent,
  missingLocation,
}: {
  missingContent: boolean;
  missingLocation: boolean;
}) {
  const firedRef = useRef(false);
  useEffect(() => {
    if (firedRef.current) return;
    firedRef.current = true;
    track("radar_onboarding_required", { missing_roles: missingContent, missing_locations: missingLocation });
  }, [missingContent, missingLocation]);

  return (
    <div className="rounded-[1.5rem] border border-dashed border-black/[0.12] bg-white/45 px-6 py-14 text-center dark:border-white/[0.1] dark:bg-white/[0.05]">
      <h2 className="t-h2 ink-1">先告诉我们你想找什么</h2>
      <p className="t-body-sm mx-auto mt-2 max-w-md text-pretty ink-2">
        设置目标岗位和城市后，系统会每天从企业官网中筛出值得处理的机会。
      </p>
      <div className="mt-6 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Link
          href="/me"
          className={cn(buttonVariants({ variant: "ink", size: "md" }), "inline-flex items-center justify-center")}
        >
          设置求职目标
        </Link>
        <Link
          href="/me#resume"
          className={cn(buttonVariants({ variant: "soft", size: "md" }), "inline-flex items-center justify-center")}
        >
          上传简历生成画像
        </Link>
      </div>
      {/* 给「先随便逛逛」的新用户留出口：不设目标也能看岗位库，别把首次访问堵死在表单前 */}
      <p className="t-caption mt-4 ink-3">
        还没想好？
        <Link href="/jobs" className="t-label ml-1 underline underline-offset-2 hover:opacity-80">
          先去岗位库随便逛逛
        </Link>
      </p>
    </div>
  );
}

// 空队列仍要回答「为什么是 0」，但**不报内部漏斗的中间数**（2026-09-02 创始人要求下线
// 「考察 N 个 / 剔除 M 个：已失效·不对口·信息不全」那套话术——那是给运营看的漏斗，
// 不是给求职者看的价值）。这里只说结论 + 下一步动作，语气仍是「宁缺毋滥」而非「系统没干活」。
function EmptyQueue({
  counts,
  widening,
  criteria,
}: {
  counts?: OpportunityFeed["counts"];
  widening?: EmptyWidening | null;
  criteria?: string[];
}) {
  const screened = counts?.screened ?? 0;
  const conditions = (criteria || []).filter(Boolean);
  // 「今天没有新的」会被读成「明天再来」，而 0 岗的真实原因几乎总是几个条件叠太窄 ——
  // 那样他明天、后天还是空。所以先把他自己叠的条件念回去，再说松哪一个就有货。
  const explain =
    screened > 0
      ? "今天的官方在招岗位都过了一遍，没有一条同时满足这些条件——宁可空着，也不硬凑。"
      : "系统持续在监控你关注的官方招聘源，暂时还没有同时满足这些条件的岗位。";
  return (
    <div className="rounded-[1.5rem] border border-dashed border-black/[0.12] bg-white/45 px-6 py-14 text-center dark:border-white/[0.1] dark:bg-white/[0.05]">
      <h2 className="t-h2 ink-1">今天暂时没有新的对口机会</h2>
      {conditions.length > 0 && (
        <p className="t-body-sm mx-auto mt-2 max-w-md text-pretty ink-2">
          你现在的条件是
          <span className="ink-1 font-medium">{conditions.join(" · ")}</span>。
        </p>
      )}
      <p className="t-body-sm mx-auto mt-2 max-w-md text-pretty ink-2">{explain}</p>
      {widening ? (
        <p className="t-body-sm mx-auto mt-3 max-w-md text-pretty ink-2">
          放宽<span className="ink-1 font-medium">{WIDEN_DIM_LABEL[widening.dim]}</span>
          （现在是 {widening.from}）之后有
          <span className="t-num ink-1 font-semibold"> {widening.count} </span>
          个机会。
        </p>
      ) : conditions.length > 0 ? (
        <p className="t-body-sm mx-auto mt-3 max-w-md text-pretty ink-2">
          放宽城市或求职阶段也还是没有，多半是目标岗位写得太具体了——换个更常见的说法试试。
        </p>
      ) : null}
      <div className="mt-6 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Link href="/me" className={buttonVariants({ variant: "soft", size: "sm" })}>
          调整求职目标
        </Link>
        <Link href="/jobs" className={buttonVariants({ variant: "soft", size: "sm" })}>
          搜索完整岗位库
        </Link>
        {/* 带锚点：此前和「调整求职目标」都落在 /me 顶部，两颗按钮看着是两件事、点完是同一个地方。 */}
        <Link href="/me#watch-companies" className={buttonVariants({ variant: "soft", size: "sm" })}>
          添加关注公司
        </Link>
      </div>
    </div>
  );
}

// 今天这批是用户自己处理完的（收藏 / 投递 / 不适合），不是「没有对口机会」。
// 两种 0 必须分开说：把刚处理完的人打发成「你的条件太窄」，既不对也挺气人。
function AllHandled() {
  return (
    <div className="rounded-[1.5rem] border border-dashed border-black/[0.12] bg-white/45 px-6 py-14 text-center dark:border-white/[0.1] dark:bg-white/[0.05]">
      <h2 className="t-h2 ink-1">今天的机会都处理完了</h2>
      <p className="t-body-sm mx-auto mt-2 max-w-md text-pretty ink-2">
        收藏和标记投递的岗位都在「收藏」「投递记录」里。有新的对口岗位会排到这里；想现在接着看，可以去岗位库搜。
      </p>
      <div className="mt-6 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Link href="/saved" className={buttonVariants({ variant: "soft", size: "sm" })}>
          看看收藏
        </Link>
        <Link href="/jobs" className={buttonVariants({ variant: "soft", size: "sm" })}>
          搜索完整岗位库
        </Link>
      </div>
    </div>
  );
}

const TOAST_MS = 5000;

export default function TodayClient({
  feed,
  emptyWidening,
  criteria,
}: {
  feed: OpportunityFeed;
  emptyWidening?: EmptyWidening | null;
  criteria?: string[];
}) {
  const [state, dispatch] = useReducer(todayReducer, feed.sections, initTodayState);
  const [deadIds, setDeadIds] = useState<Set<string>>(new Set());
  // 动作没落库（接口失败）的提示。JobCard 自己的行内报错这里看不到：卡片在乐观移除时已经卸载，
  // 回滚后挂回来的是一张新卡 —— 不单独提示的话，用户只看到卡片消失又悄悄回来。
  const [actionFailed, setActionFailed] = useState(false);
  useEffect(() => {
    if (!actionFailed) return;
    const t = setTimeout(() => setActionFailed(false), 3000);
    return () => clearTimeout(t);
  }, [actionFailed]);

  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  // 本次会话里已处理（收藏 / 投递 / 不适合）的岗。切求职范围触发的刷新在请求开头就读了操作记录，
  // 刷新途中刚点的那一下还没落库 —— 新 feed 里仍带着这张卡，不滤掉它会在重置后「复活」。
  const actedRef = useRef<Set<string>>(new Set());
  // 三本小账，都是为了「动作请求的结果回来时，队列该不该动、怎么动」：
  //   inflight  每张卡还有几个动作请求在路上（计数而不是有 / 无：撤销后重新操作时会同时有两个）。
  //   removed   本页已乐观移除、结果还没定的岗。
  //   awaiting  提示条 5 秒已到点、但请求还没回来的岗 —— 落定留给结果回来那一刻。
  // 提示条到点就直接「落定」会丢掉回滚所需的位置信息：请求第 6 秒才失败时，卡片回不来、
  // 页面却提示「已恢复原状态」，而数据库里其实什么都没存上。
  const inflightRef = useRef<Map<string, number>>(new Map());
  const removedRef = useRef<Set<string>>(new Set());
  const awaitingResultRef = useRef<Set<string>>(new Set());
  const openedRef = useRef(false);
  const livenessRequested = useRef<Set<string>>(new Set());

  function clearTimer(jobId: string) {
    const t = timers.current.get(jobId);
    if (t) {
      clearTimeout(t);
      timers.current.delete(jobId);
    }
  }
  // 清理所有计时器
  useEffect(() => {
    const map = timers.current;
    return () => {
      for (const t of Array.from(map.values())) clearTimeout(t);
      map.clear();
    };
  }, []);

  // 服务端换了一批机会（顶栏切「求职范围」后 router.refresh）→ 队列跟着换。
  // useReducer 的初值只在挂载时读一次，不同步的话页面上半截是新范围的说明、下半截还是旧范围的卡片
  // （2026-10-10 线上实测：切到海外后说明写「4 个海外岗排在最前」，列表仍是原来那 30 个国内岗）。
  // 用 generated_at 而不是 feed 对象引用判断：同一份结果的重渲染不该清掉正在进行的撤销。
  const feedStampRef = useRef(feed.generated_at);
  useEffect(() => {
    if (feedStampRef.current === feed.generated_at) return;
    feedStampRef.current = feed.generated_at;
    for (const t of Array.from(timers.current.values())) clearTimeout(t);
    timers.current.clear();
    awaitingResultRef.current.clear();
    removedRef.current.clear();
    const acted = actedRef.current;
    const keep = (list: Opportunity[]) => (acted.size ? list.filter((o) => !acted.has(o.job.id)) : list);
    const s = feed.sections;
    dispatch({
      type: "reset",
      sections: {
        critical: keep(s.critical),
        main: keep(s.main),
        explore: keep(s.explore),
        momentum: keep(s.momentum),
        waiting: keep(s.waiting),
      },
    });
  }, [feed]);

  // 首渲后记录「上次打开」+ radar_open（Strict Mode 下 ref 去重）
  useEffect(() => {
    if (openedRef.current) return;
    openedRef.current = true;
    const mainCount = feed.sections.critical.length + feed.sections.main.length + feed.sections.explore.length;
    const source = new URLSearchParams(window.location.search).get("source") || "direct";
    track("radar_open", { counts: feed.counts, source });
    void fetch("/api/radar/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ generated_at: feed.generated_at, feed_count: Math.min(30, mainCount) }),
    }).catch(() => {});
  }, [feed]);

  // 展示时校验（②层）：异步探活可见岗位，死的当场隐藏（复用 /api/jobs/liveness-check）
  useEffect(() => {
    const visible = ORDER.flatMap((k) => displayItemsFor(k));
    const ids = visible
      .map((o) => o.job.id)
      .filter((id) => id && !livenessRequested.current.has(id) && !deadIds.has(id))
      .slice(0, 25);
    if (ids.length === 0) return;
    ids.forEach((id) => livenessRequested.current.add(id));
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/jobs/liveness-check", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids }),
        });
        const data = await resp.json();
        if (!cancelled && data?.ok && Array.isArray(data.dead) && data.dead.length) {
          setDeadIds((prev) => {
            const next = new Set(prev);
            (data.dead as string[]).forEach((id) => next.add(id));
            return next;
          });
        }
      } catch {
        /* 静默：后台 sweep 兜底 */
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.sections]);

  // JobCard 乐观回调：非空动作 → 乐观移除 + 5s 后落定；null（正向 API 失败）→ 还原（reducer 保证可靠移除/还原）
  function handleActionChange(jobId: string, action: PrimaryAction | null) {
    // JobCard 在请求失败时会再调一次 onActionChange(原来的动作) 通知回滚。回滚统一放在
    // handleActionResult 里做（那里明确知道 ok=false）：在这里按「非空 = 又一次乐观移除」处理的话，
    // 原动作非空的卡（关键提醒区里已收藏的岗）失败后不是回来，而是被再「移除」一次并提示「已收藏」。
    if (removedRef.current.has(jobId)) return;
    // 空动作且没有待定的移除 = 在卡片上取消了已有动作（如取消收藏）：卡片留在原地，队列无事可做。
    if (action === null) return;
    removedRef.current.add(jobId);
    actedRef.current.add(jobId);
    inflightRef.current.set(jobId, (inflightRef.current.get(jobId) ?? 0) + 1);
    dispatch({ type: "removeOptimistic", jobId, action });
    clearTimer(jobId);
    timers.current.set(
      jobId,
      setTimeout(() => {
        timers.current.delete(jobId);
        if ((inflightRef.current.get(jobId) ?? 0) > 0) {
          // 请求还在路上：只把提示条收掉，落定留给 handleActionResult。
          awaitingResultRef.current.add(jobId);
          dispatch({ type: "expireToast", jobId });
        } else {
          removedRef.current.delete(jobId);
          dispatch({ type: "finalizeRemove", jobId });
        }
      }, TOAST_MS),
    );
  }

  // 落库结果：成功不用再说一遍（乐观移除时已经弹了「已收藏 · 撤销」），失败在这里回滚并说出来。
  function handleActionResult({ jobId, ok }: { jobId: string; ok: boolean }) {
    const left = Math.max(0, (inflightRef.current.get(jobId) ?? 0) - 1);
    if (left > 0) inflightRef.current.set(jobId, left);
    else inflightRef.current.delete(jobId);
    // 没有待定的移除（已撤销 / 只是在卡片上取消了动作）→ 队列没什么可做的，卡片自己会显示行内报错。
    if (!removedRef.current.has(jobId)) return;
    // 还有更晚发出的请求在路上（撤销后又操作了一次）→ 这是前一个请求的结果，已被那次撤销作废。
    if (left > 0) return;
    if (!ok) {
      removedRef.current.delete(jobId);
      actedRef.current.delete(jobId);
      awaitingResultRef.current.delete(jobId);
      clearTimer(jobId);
      dispatch({ type: "removeRollback", jobId });
      setActionFailed(true);
      return;
    }
    if (awaitingResultRef.current.delete(jobId)) {
      removedRef.current.delete(jobId);
      dispatch({ type: "finalizeRemove", jobId });
    }
  }

  async function undo() {
    const t = state.toast;
    if (!t || t.undoFailed) return;
    const jobId = t.jobId;
    clearTimer(jobId);
    // 卡片回到队列里了：之后晚到的那个请求结果不该再动它。
    removedRef.current.delete(jobId);
    awaitingResultRef.current.delete(jobId);
    dispatch({ type: "undoOptimistic", jobId });
    try {
      const resp = await fetch(`/api/job-actions/${jobId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: null }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      dispatch({ type: "undoCommit", jobId });
      actedRef.current.delete(jobId);
      // 撤销成功后才记事件（失败不记成功，P0-4 同口径）
      track("opportunity_undo", { previous_action: t.action, surface: "today" });
    } catch {
      // 撤销 API 失败 → 重新移出 + 提示，不让 UI 与数据库长期相反
      dispatch({ type: "undoRollback", jobId });
      setTimeout(() => dispatch({ type: "dismissToast" }), TOAST_MS);
    }
  }

  function displayItemsFor(key: DisplaySectionKey): Opportunity[] {
    return key === "main" ? [...state.sections.main, ...state.sections.waiting] : state.sections[key];
  }

  const visibleCounts = ORDER.map((k) => displayItemsFor(k).filter((o) => !deadIds.has(o.job.id)).length);
  const total = visibleCounts.reduce((a, b) => a + b, 0);

  // 提示条要在「还有卡」和「卡清空了」两种页面上都在：此前它只写在有卡的那个 return 里，
  // 处理完最后一张卡时整页换成空状态，「已收藏 · 撤销」跟着一起没了，撤销无从点起。
  // 两条提示叠放而不是二选一：A 卡失败的那 3 秒里用户可能刚收藏了 B 卡，B 的「撤销」不能被盖住。
  const toastNode =
    actionFailed || state.toast ? (
      <div className="above-mobile-nav fixed inset-x-0 z-50 flex flex-col items-center gap-2 px-4">
        {actionFailed && (
          <div
            role="status"
            aria-live="polite"
            className="t-body-sm rounded-full border border-tone-rose-border bg-tone-rose-bg px-4 py-2.5 text-tone-rose-fg shadow-lg"
          >
            {jobActionToastText(null, false)}
          </div>
        )}
        {state.toast && (
          <div className="t-body-sm flex items-center gap-3 rounded-full border border-black/[0.1] bg-[#1a1714] px-4 py-2.5 text-[#f7f1e6] shadow-lg dark:bg-[#f3ecdf] dark:text-[#16130f]">
            {state.toast.undoFailed ? (
              <span>撤销失败，已重新移出</span>
            ) : (
              <>
                <span>{state.toast.action ? ACTION_LABEL[state.toast.action] : "已处理"}</span>
                <button type="button" onClick={undo} className="t-label text-[#f7f1e6] underline underline-offset-2 hover:opacity-80 dark:text-[#16130f]">
                  撤销
                </button>
              </>
            )}
          </div>
        )}
      </div>
    ) : null;

  if (total === 0) {
    // 服务端给过卡、现在队列里一张不剩 = 用户自己处理完的；被实时复核隐藏的不算（那些还在队列里）。
    const served = ORDER.reduce((n, k) => n + feed.sections[k].length, 0) + feed.sections.waiting.length;
    const remaining = ORDER.reduce((n, k) => n + displayItemsFor(k).length, 0);
    return (
      <>
        {served > 0 && remaining === 0 ? (
          <AllHandled />
        ) : (
          <EmptyQueue counts={feed.counts} widening={emptyWidening} criteria={criteria} />
        )}
        {toastNode}
      </>
    );
  }

  return (
    <div className="space-y-10">
      {deadIds.size > 0 && (
        <p className="t-body-sm rounded-full border border-black/[0.08] bg-white/60 px-4 py-2 ink-2 dark:border-white/[0.1] dark:bg-white/[0.05]">
          刚刚实时复核发现 {deadIds.size} 个岗位已失效，已自动为你隐藏，帮你省一次白点。
        </p>
      )}
      {ORDER.map((key) => {
        const items = displayItemsFor(key).filter((o) => !deadIds.has(o.job.id));
        if (items.length === 0) return null;
        const meta = SECTION_META[key];
        return (
          <section key={key}>
            <div className="mb-3">
              <h2 className="t-h2 ink-1">
                {meta.title}
                <span className="t-num ml-2 ink-3">{items.length}</span>
              </h2>
              {meta.subtitle && (
                <p className="t-caption mt-1 ink-3">{meta.subtitle}</p>
              )}
            </div>
            <div className="space-y-3">
              {items.map((opp) => (
                <JobCard
                  key={opp.job.id}
                  job={toScoredJob(opp)}
                  variant="opportunity"
                  opportunityTier={opp.tier}
                  opportunityReasons={opp.reasons}
                  freshnessState={opp.freshness}
                  opportunitySignals={visibleOpportunitySignals(opp)}
                  opportunityCheckedAgeHours={checkedAgeHours(opp.lastCheckedAt)}
                  onActionChange={handleActionChange}
                  onActionResult={handleActionResult}
                />
              ))}
            </div>
          </section>
        );
      })}

      {toastNode}
    </div>
  );
}

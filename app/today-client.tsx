"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import Link from "next/link";
import JobCard from "@/components/JobCard";
import { track } from "@/lib/track";
import type { ScoredJob } from "@/lib/types";
import type { Opportunity, OpportunityFeed, OpportunitySignal } from "@/lib/opportunities/types";
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
  saved: "已加入「值得投」",
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
          href="/preferences#resume"
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
function EmptyQueue({ counts }: { counts?: OpportunityFeed["counts"] }) {
  const screened = counts?.screened ?? 0;
  const explain =
    screened > 0
      ? "今天的官方在招岗位都过了一遍，没有一条达到推荐门槛——宁可空着，也不硬凑。你可以："
      : "系统持续在监控你关注的官方招聘源，有新机会会第一时间出现在这里。你也可以：";
  return (
    <div className="rounded-[1.5rem] border border-dashed border-black/[0.12] bg-white/45 px-6 py-14 text-center dark:border-white/[0.1] dark:bg-white/[0.05]">
      <h2 className="t-h2 ink-1">今天暂时没有新的对口机会</h2>
      <p className="t-body-sm mx-auto mt-2 max-w-md text-pretty ink-2">
        {explain}
      </p>
      <div className="mt-6 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Link href="/me" className={buttonVariants({ variant: "soft", size: "sm" })}>
          调整求职目标
        </Link>
        <Link href="/jobs" className={buttonVariants({ variant: "soft", size: "sm" })}>
          搜索完整岗位库
        </Link>
        <Link href="/me" className={buttonVariants({ variant: "soft", size: "sm" })}>
          添加关注公司
        </Link>
      </div>
    </div>
  );
}

const TOAST_MS = 5000;

export default function TodayClient({ feed }: { feed: OpportunityFeed }) {
  const [state, dispatch] = useReducer(todayReducer, feed.sections, initTodayState);
  const [deadIds, setDeadIds] = useState<Set<string>>(new Set());

  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
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
    if (action !== null) {
      dispatch({ type: "removeOptimistic", jobId, action });
      clearTimer(jobId);
      timers.current.set(
        jobId,
        setTimeout(() => {
          timers.current.delete(jobId);
          dispatch({ type: "finalizeRemove", jobId });
        }, TOAST_MS),
      );
    } else {
      clearTimer(jobId);
      dispatch({ type: "removeRollback", jobId });
    }
  }

  async function undo() {
    const t = state.toast;
    if (!t || t.undoFailed) return;
    const jobId = t.jobId;
    clearTimer(jobId);
    dispatch({ type: "undoOptimistic", jobId });
    try {
      const resp = await fetch(`/api/job-actions/${jobId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: null }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      dispatch({ type: "undoCommit", jobId });
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

  if (total === 0) {
    return <EmptyQueue counts={feed.counts} />;
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
                />
              ))}
            </div>
          </section>
        );
      })}

      {state.toast && (
        <div className="above-mobile-nav fixed inset-x-0 z-50 flex justify-center px-4">
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
        </div>
      )}
    </div>
  );
}

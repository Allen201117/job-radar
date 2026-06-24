"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import Link from "next/link";
import JobCard from "@/components/JobCard";
import { track } from "@/lib/track";
import type { ScoredJob } from "@/lib/types";
import type { Opportunity, OpportunityFeed } from "@/lib/opportunities/types";
import {
  todayReducer,
  initTodayState,
  type PrimaryAction,
  type SectionKey,
} from "@/lib/opportunities/today-reducer";

const SECTION_META: Record<SectionKey, { title: string; subtitle?: string }> = {
  critical: { title: "关键提醒", subtitle: "和你已表达的关注强相关：收藏岗位的截止或关闭、需要尽快处理的机会。" },
  main: { title: "刚核验仍在招的对口机会", subtitle: "最近确认仍在招、和你目标贴合的官方岗位。" },
  explore: { title: "可以拓展看看", subtitle: "相关方向或你关注的公司，匹配度稍低，按需查看。" },
  momentum: { title: "本周招聘动量", subtitle: "这些公司近期在持续放岗。" },
  waiting: {
    title: "等待再次确认",
    subtitle: "以下岗位距上次核验已超过常规时限，建议以官网状态为准。",
  },
};

const ORDER: SectionKey[] = ["critical", "main", "explore", "momentum", "waiting"];

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
    match_score: opp.score,
    matched_keywords: [],
    match_reasons: [],
    hidden_reason: null,
    user_action: opp.userAction,
  };
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
      <h2 className="text-lg font-semibold text-[#1a1714] dark:text-[#f3ecdf]">先告诉我们你想找什么</h2>
      <p className="mx-auto mt-2 max-w-md text-pretty text-[14px] leading-6 text-[#6b655a] dark:text-[#b6ad9d]">
        设置目标岗位和城市后，系统会每天从企业官网中筛出值得处理的机会。
      </p>
      <div className="mt-6 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Link
          href="/preferences"
          className="inline-flex items-center justify-center rounded-full bg-[#1a1714] px-5 py-2.5 text-sm font-semibold text-[#f7f1e6] transition hover:bg-[#2b2520] dark:bg-[#f3ecdf] dark:text-[#16130f] dark:hover:bg-[#e8ddca]"
        >
          设置求职目标
        </Link>
        <Link
          href="/preferences#resume"
          className="inline-flex items-center justify-center rounded-full border border-black/[0.1] bg-white/70 px-5 py-2.5 text-sm font-semibold text-[#3f3a33] transition hover:bg-white dark:border-white/[0.12] dark:bg-white/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.08]"
        >
          上传简历生成画像
        </Link>
      </div>
    </div>
  );
}

function EmptyQueue() {
  return (
    <div className="rounded-[1.5rem] border border-dashed border-black/[0.12] bg-white/45 px-6 py-14 text-center dark:border-white/[0.1] dark:bg-white/[0.05]">
      <h2 className="text-lg font-semibold text-[#1a1714] dark:text-[#f3ecdf]">今天暂时没有新的对口机会</h2>
      <p className="mx-auto mt-2 max-w-md text-pretty text-[14px] leading-6 text-[#6b655a] dark:text-[#b6ad9d]">
        系统持续在监控你关注的官方招聘源，有新机会会第一时间出现在这里。你也可以：
      </p>
      <div className="mt-6 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Link href="/preferences" className="rounded-full border border-black/[0.1] bg-white/70 px-4 py-2 text-sm font-medium text-[#3f3a33] transition hover:bg-white dark:border-white/[0.12] dark:bg-white/[0.05] dark:text-[#d9d0c2]">
          调整求职目标
        </Link>
        <Link href="/jobs" className="rounded-full border border-black/[0.1] bg-white/70 px-4 py-2 text-sm font-medium text-[#3f3a33] transition hover:bg-white dark:border-white/[0.12] dark:bg-white/[0.05] dark:text-[#d9d0c2]">
          搜索完整岗位库
        </Link>
        <Link href="/preferences" className="rounded-full border border-black/[0.1] bg-white/70 px-4 py-2 text-sm font-medium text-[#3f3a33] transition hover:bg-white dark:border-white/[0.12] dark:bg-white/[0.05] dark:text-[#d9d0c2]">
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
    const visible = ORDER.flatMap((k) => state.sections[k]);
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

  const visibleCounts = ORDER.map((k) => state.sections[k].filter((o) => !deadIds.has(o.job.id)).length);
  const total = visibleCounts.reduce((a, b) => a + b, 0);

  if (total === 0) {
    return <EmptyQueue />;
  }

  return (
    <div className="space-y-10">
      {ORDER.map((key) => {
        const items = state.sections[key].filter((o) => !deadIds.has(o.job.id));
        if (items.length === 0) return null;
        const meta = SECTION_META[key];
        return (
          <section key={key}>
            <div className="mb-3">
              <h2 className="text-lg font-semibold text-[#1a1714] dark:text-[#f3ecdf]">
                {meta.title}
                <span className="ml-2 text-sm font-normal text-[#8a8275] dark:text-[#9a9184]">{items.length}</span>
              </h2>
              {meta.subtitle && (
                <p className="mt-1 text-[13px] leading-5 text-[#8a8275] dark:text-[#9a9184]">{meta.subtitle}</p>
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
                  opportunitySignals={opp.signals}
                  opportunityCheckedAgeHours={checkedAgeHours(opp.lastCheckedAt)}
                  onActionChange={handleActionChange}
                />
              ))}
            </div>
          </section>
        );
      })}

      {state.toast && (
        <div className="fixed inset-x-0 bottom-6 z-50 flex justify-center px-4">
          <div className="flex items-center gap-3 rounded-full border border-black/[0.1] bg-[#1a1714] px-4 py-2.5 text-sm text-[#f7f1e6] shadow-lg dark:bg-[#f3ecdf] dark:text-[#16130f]">
            {state.toast.undoFailed ? (
              <span>撤销失败，已重新移出</span>
            ) : (
              <>
                <span>{state.toast.action ? ACTION_LABEL[state.toast.action] : "已处理"}</span>
                <button type="button" onClick={undo} className="font-semibold underline underline-offset-2 hover:opacity-80">
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

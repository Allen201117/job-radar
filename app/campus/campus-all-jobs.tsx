"use client";

// 校招专区「全部校招岗」视图（2026-09-18 默认态）：**整个校招岗位库**，不是必投那 30 家。
//
// 取数走 /api/jobs/search（jobType 锁定成 校招/实习），理由见
// docs/superpowers/specs/2026-09-18-campus-zone-all-campus-jobs-design.md §3：
// jobType 已是物化列的精确 SQL 下推、往届门已在同一条路上、筛选器与岗位卡整套可复用。
//
// ⚠️ 这里**一条岗位记录都不经 SSR 下发**（CLAUDE.md「校招专区首屏」那块碑：16,494 条逐条
// 序列化 = 单页 2.09MB / responseEnd 10.1s；这个视图是 6.6 万条，只会更糟）。挂载后才发第一次
// 请求，首帧是骨架屏。线上匿名实测 TTFB 1.0~1.9s（分段数字见 spec §7）。

import { useEffect, useRef, useState } from "react";
import ActionToast, { jobActionToastText, useActionToast } from "@/components/ActionToast";
import BackToTop from "@/components/BackToTop";
import JobCard from "@/components/JobCard";
import JobFilters from "@/components/JobFilters";
import { JobListSkeleton } from "@/components/Skeletons";
import { Badge, buttonVariants } from "@/components/ui";
import { DEFAULT_FILTERS, splitMultiValue, type Filters } from "@/lib/job-filter";
import { formatMatchTotal } from "@/lib/match-total";
import { campusResetFilters, withCampusMode, type RecruitMode } from "@/lib/campus-zone";
import { cn } from "@/lib/utils";
import { useJobFilters } from "@/hooks/useJobFilters";
import { CircleNotch, MagnifyingGlass } from "@phosphor-icons/react";

type PrimaryAction = "saved" | "ignored" | "applied";

export default function CampusAllJobs({
  mode,
  jobScope = "domestic",
}: {
  mode: RecruitMode;
  jobScope?: string | null;
}) {
  // 公司输入框的候选清单（与 /jobs 同一份接口）。只在这个视图挂载时拉一次；
  // 「必投 30 家」视图用不到它，所以刻意不放到页面 SSR 里。
  const [companies, setCompanies] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/jobs/companies");
        const data = await resp.json();
        if (!cancelled && data?.ok && Array.isArray(data.companies)) setCompanies(data.companies);
      } catch (err) {
        // 取不到就保持空 datalist（公司框仍可自由输入子串）。但不静默吞：
        // 下拉长期为空时要能从控制台看出是接口挂了还是真没数据。
        console.error("[campus] 公司候选加载失败", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 初值只锁 jobType，**不预填城市/关键词**。/jobs 会按偏好预填，这里刻意不填：
  // 专区的承诺是「这是全部校招岗」，一进来就被关键词硬筛掉一半会让用户以为库里就这么点。
  // 个性化交给 sortBy=match（软排序，不藏东西），不交给硬筛。
  const {
    filters,
    setFilters,
    displayJobs,
    total,
    exactCount,
    relatedSameFunction,
    relatedMissingInfo,
    capped,
    exactTotal,
    loading,
    loadingMore,
    error,
    hasMore,
    loadMore,
  } = useJobFilters({
    officialJobs: [],
    onlyNew: false,
    initialFilters: { jobType: withCampusMode(DEFAULT_FILTERS, mode).jobType },
    initialJobs: [],
    initialTotal: 0,
  });

  // 切「校招 / 实习」→ 把 jobType 写回去。withCampusMode 在已经相等时返回**同一个对象引用**，
  // React 会跳过这次更新，所以挂载那一拍不会白发一次搜索。
  useEffect(() => {
    setFilters((f) => withCampusMode(f, mode));
  }, [mode, setFilters]);

  // 国内范围下「目标地区」是海外专有项，留着会筛出空结果（与 /jobs 同一处理）。
  useEffect(() => {
    if (jobScope !== "domestic") return;
    setFilters((f) => (f.region ? { ...f, region: "" } : f));
  }, [jobScope, setFilters]);

  // ⚠️ 清空按钮不能用 hook 自带的 clearAll —— 那会把 jobType 清成「全部」，专区静默混进社招岗。
  // 三条泄漏路径的另外两条（筛选控件、已选 chip）由 JobFilters 的 lockedJobType 堵。
  function clearAllKeepingMode() {
    setFilters((f) => campusResetFilters(DEFAULT_FILTERS, f, mode));
  }
  function clearOneKeepingMode(key: keyof Filters, value?: string) {
    setFilters((current) => {
      const next =
        value && ["city", "keyword", "jobFunction", "jobRole", "companyTier"].includes(key)
          ? {
              ...current,
              [key]: splitMultiValue(String(current[key])).filter((item) => item !== value).join(","),
            }
          : { ...current, [key]: DEFAULT_FILTERS[key] };
      return withCampusMode(next as Filters, mode);
    });
  }

  // 展示时校验（②层，与 app/jobs/jobs-client.tsx、app/campus/campus-client.tsx 同一套）：
  // 对当下可见的岗位批量探活，死的当场从渲染里隐藏。看板先渲染，不被它阻塞。
  const [deadIds, setDeadIds] = useState<Set<string>>(new Set());
  const livenessRequested = useRef<Set<string>>(new Set());
  useEffect(() => {
    const ids = displayJobs
      .filter((j) => j.id && !livenessRequested.current.has(j.id) && !deadIds.has(j.id))
      .map((j) => j.id)
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
        // 静默：探不动就不动，后台 sweep / 浏览器审计兜底
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayJobs]);

  const { toast, show: showToast, dismiss: dismissToast } = useActionToast();
  function handleActionChange(_jobId: string, _action: PrimaryAction | null) {
    // 本区不预取 job_actions（不做个性化隐藏），JobCard 内部仍会真实写库。
  }

  const visibleJobs = displayJobs.filter((job) => !deadIds.has(job.id));
  // 候选撞上限时 total 只是取数上限，不是真实匹配数 → 交给 formatMatchTotal 决定给不给确定数字。
  const matchTotal = formatMatchTotal(total, capped, exactTotal);
  const breakdown = filters.keyword
    ? [
        exactCount > 0 ? `精确 ${exactCount}` : "",
        relatedSameFunction > 0 ? `同职能相关 ${relatedSameFunction}` : "",
        relatedMissingInfo > 0 ? `信息不全 ${relatedMissingInfo}` : "",
      ].filter(Boolean)
    : [];

  return (
    <div className="space-y-5">
      <BackToTop />
      <JobFilters
        filters={filters}
        onChange={setFilters}
        onClearAll={clearAllKeepingMode}
        onClearOne={clearOneKeepingMode}
        companies={companies}
        resultTotalText={matchTotal.text}
        jobScope={jobScope}
        lockedJobType
      />

      {/* 转圈的颜色走语义令牌（--tone-green-*，明暗自动切换），不写 inline hex ——
          CLAUDE.md「排版与文字颜色」那条：新代码一律用语义类。 */}
      <div className="t-body-sm flex flex-wrap items-start gap-2 rounded-2xl border border-black/[0.06] bg-white/55 px-3.5 py-2.5 ink-2 dark:border-white/[0.1] dark:bg-white/[0.05]">
        {loading ? (
          <CircleNotch size={16} weight="bold" className="mt-0.5 shrink-0 animate-spin text-tone-green-fg" aria-hidden="true" />
        ) : (
          <MagnifyingGlass size={16} weight="bold" className="mt-0.5 shrink-0" aria-hidden="true" />
        )}
        <div className="min-w-0">
          {loading ? (
            <p className="t-label ink-2">正在搜索{mode === "campus" ? "校招" : "实习"}岗位…</p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <p className="t-label ink-2">
                  {matchTotal.text} 个匹配{mode === "campus" ? "校招" : "实习"}岗位 · 已展示 {visibleJobs.length}
                </p>
                {deadIds.size > 0 && (
                  <Badge tone="neutral" size="xs">
                    实时复核拦下 {deadIds.size} 个
                  </Badge>
                )}
              </div>
              {(breakdown.length > 0 || capped) && (
                <p className="t-caption mt-0.5 ink-3">
                  {[...breakdown, capped ? "还有更多，可继续加载" : ""].filter(Boolean).join("·")}
                </p>
              )}
            </>
          )}
        </div>
      </div>

      {error && (
        <p className="t-body-sm rounded-2xl border border-tone-rose-border bg-tone-rose-bg px-3.5 py-2.5 text-tone-rose-fg">
          {error}
        </p>
      )}

      <div className="space-y-3">
        {loading ? (
          <JobListSkeleton count={3} />
        ) : visibleJobs.length === 0 ? (
          <div className="rounded-[1.5rem] border border-dashed border-black/[0.12] bg-white/45 px-6 py-14 text-center dark:border-white/[0.1] dark:bg-white/[0.05]">
            <h2 className="t-h2 ink-1">没有匹配的{mode === "campus" ? "校招" : "实习"}岗位</h2>
            <p className="t-body-sm mx-auto mt-2 max-w-md text-pretty ink-2">
              可以放宽筛选条件；或切到「必投 30 家」，看你目标行业里那几家的招聘窗口。
            </p>
            <button
              type="button"
              onClick={clearAllKeepingMode}
              className={cn(buttonVariants({ variant: "soft", size: "sm" }), "mt-5")}
            >
              放宽筛选条件
            </button>
          </div>
        ) : (
          visibleJobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              matchReason={(job as any).__match}
              onActionChange={handleActionChange}
              onActionResult={({ action, ok }) =>
                showToast({ text: jobActionToastText(action, ok), tone: ok ? "default" : "error" })
              }
            />
          ))
        )}
      </div>

      {hasMore && !loading && (
        <div className="flex justify-center pt-1">
          <button
            type="button"
            onClick={loadMore}
            disabled={loadingMore}
            className={cn(
              buttonVariants({ variant: "soft", size: "md" }),
              "inline-flex items-center gap-2 active:scale-[0.98] disabled:opacity-50",
            )}
          >
            {loadingMore ? (
              <>
                <CircleNotch size={16} weight="bold" className="animate-spin" aria-hidden="true" />
                加载中…
              </>
            ) : (
              <>
                加载更多
                {/* 撞上限时 total 是取数上限，减出来的差值同样是假数字 → 只说「还有更多」。 */}
                <span className="t-num ink-3">
                  {matchTotal.approximate || capped ? "（还有更多）" : `（还有 ${total - displayJobs.length} 个）`}
                </span>
              </>
            )}
          </button>
        </div>
      )}

      <ActionToast toast={toast} onDismiss={dismissToast} />
    </div>
  );
}

"use client";

// 「还没设过求职目标」的新用户在 /today 看到的东西。
//
// 为什么存在：改造前这里是一堵**表单墙**（OnboardingPanel 独占整页，一条岗位都不给），
// 而实测的真实用户行为是「注册完先看今日推荐，不会先去传简历」——于是第一屏拿到的是作业，
// 不是价值。现在改成「细引导条 + 热门在招」：先给东西看，再顺势引导设目标。
//
// 诚实边界（文案里明写、别删）：这些岗**不是按你的目标筛的**。产品的核心价值是精准匹配，
// 兜底位不能假装自己是匹配结果，否则用户会拿它评判匹配质量。
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import JobCard from "@/components/JobCard";
import ActionToast, { jobActionToastText, useActionToast } from "@/components/ActionToast";
import { Segmented, buttonVariants } from "@/components/ui";
import QuickStartGoalBar from "@/components/QuickStartGoalBar";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import type { Job, ScoredJob } from "@/lib/types";

export type PopularJobItem = { job: Job; industry: string };

const ALL = "__all__";

/**
 * 一次渲染多少张卡。清单本身（132 条 ≈ 80KB gzip）整份下发，这样切行业 chips 是纯客户端、零往返；
 * 但**不能一次把 132 张 JobCard 全挂进 DOM**——JobCard 是重卡（洞察抽屉 / 徽章 / 展开正文），
 * 新用户第一屏也不会滚那么远。切行业后计数归位（每个行业本来就只有 12 条，一屏放得下）。
 */
const PAGE_SIZE = 30;

/** 岗位库卡（variant="library"）需要 ScoredJob 形；这里没有画像可比，分数给 0。
 *  matchTier(0) 返回 label=null → 卡上**不出现任何匹配徽标**，不会假装「高匹配」。 */
function toScoredJob(job: Job): ScoredJob {
  return {
    ...(job as ScoredJob),
    match_score: 0,
    matched_keywords: [],
    match_reasons: [],
    hidden_reason: null,
    user_action: null,
  };
}

/** 顶部细引导条：取代原来那堵整页表单墙，但保留两个 CTA（这仍是本页想让用户做的事）。 */
function GoalPrompt({ jobCount }: { jobCount: number }) {
  return (
    <div className="rounded-[1.25rem] border border-dashed border-black/[0.12] bg-white/45 px-5 py-4 dark:border-white/[0.1] dark:bg-white/[0.05] sm:flex sm:items-center sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <h2 className="t-h3 ink-1">先看看在招的机会，随时可以设目标</h2>
        <p className="t-body-sm mt-1 text-pretty ink-2">
          下面是各行业头部公司此刻挂在官网上的岗位，不是按你的目标筛的。
          设置目标岗位和城市后，这里会换成每天为你筛好的对口机会。
        </p>
      </div>
      <div className="mt-3 flex shrink-0 flex-col gap-2 sm:mt-0 sm:flex-row">
        <Link
          href="/me"
          onClick={() => track("radar_popular_cta", { target: "preferences", job_count: jobCount })}
          className={cn(buttonVariants({ variant: "ink", size: "sm" }), "inline-flex items-center justify-center whitespace-nowrap")}
        >
          设置求职目标
        </Link>
        <Link
          href="/preferences#resume"
          onClick={() => track("radar_popular_cta", { target: "resume", job_count: jobCount })}
          className={cn(buttonVariants({ variant: "soft", size: "sm" }), "inline-flex items-center justify-center whitespace-nowrap")}
        >
          上传简历
        </Link>
      </div>
    </div>
  );
}

export default function TodayPopularClient({
  items,
  industries,
  savedIndustries = [],
}: {
  items: PopularJobItem[];
  industries: string[];
  /** 用户已存过的目标行业：用来避免对同一个行业重复追问「设为你的行业吗」。 */
  savedIndustries?: string[];
}) {
  const [industry, setIndustry] = useState<string>(ALL);
  const [shown, setShown] = useState(PAGE_SIZE);
  const [deadIds, setDeadIds] = useState<Set<string>>(new Set());
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());
  const { toast, show: showToast, dismiss: dismissToast } = useActionToast();
  const openedRef = useRef(false);
  const livenessRequested = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (openedRef.current) return;
    openedRef.current = true;
    track("radar_popular_open", { job_count: items.length, industries: industries.length });
  }, [items.length, industries.length]);

  const visible = useMemo(
    () =>
      items.filter(
        (it) =>
          (industry === ALL || it.industry === industry) &&
          !deadIds.has(it.job.id) &&
          !hiddenIds.has(it.job.id),
      ),
    [items, industry, deadIds, hiddenIds],
  );

  const rendered = useMemo(() => visible.slice(0, shown), [visible, shown]);
  const renderedIdsKey = rendered.map((v) => v.job.id).join(",");

  // 展示时校验（②层，与 /today /jobs /campus 同一条链路）：异步探活**真正渲染出来**的那批岗，
  // 死的当场从列表里隐藏。它不阻塞渲染 —— 页面先出来，死岗随后悄悄消失。
  // ⚠️ 这是「能点开」的第二道保险；第一道是候选池只收「源上次抓取时还在列表里」的岗
  // （见 lib/jobs-store/popular.ts 的实测对拍）。
  useEffect(() => {
    const ids = rendered
      .map((v) => v.job.id)
      .filter((id) => id && !livenessRequested.current.has(id))
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
            (data.dead as string[]).forEach((id: string) => next.add(id));
            return next;
          });
        }
      } catch {
        // 静默：探不动就不动，后台 sweep 兜底（与 /jobs 同口径）
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renderedIdsKey]);

  const options = useMemo(
    () => [{ value: ALL, label: "全部" }, ...industries.map((i) => ({ value: i, label: i }))],
    [industries],
  );

  return (
    <div className="space-y-6">
      <GoalPrompt jobCount={items.length} />

      {industries.length > 1 && (
        <div className="-mx-1 overflow-x-auto px-1 pb-1">
          <Segmented
            ariaLabel="按行业筛选热门岗位"
            options={options}
            value={industry}
            onChange={(v) => {
              setIndustry(v);
              setShown(PAGE_SIZE); // 换行业回到第一页，别让上一个行业翻到的页数带过来
              track("radar_popular_industry", { industry: v === ALL ? "all" : v });
            }}
            className="w-max"
          />
        </div>
      )}

      <QuickStartGoalBar industry={industry === ALL ? null : industry} savedIndustries={savedIndustries} />

      <section>
        <div className="mb-3 flex items-baseline gap-2">
          <h2 className="t-h2 ink-1">热门在招</h2>
          <span className="t-num ink-3">{visible.length}</span>
          <span className="t-caption ink-3">
            {industry === ALL ? "各行业头部公司" : industry}
          </span>
        </div>
        <div className="space-y-3">
          {rendered.map((it) => (
            <JobCard
              key={it.job.id}
              job={toScoredJob(it.job)}
              onActionChange={(jobId, action) => {
                // 与 /jobs 同口径：非空动作乐观移出列表，失败回滚由 onActionResult 的 ok=false 兜。
                setHiddenIds((prev) => {
                  const next = new Set(prev);
                  if (action) next.add(jobId);
                  else next.delete(jobId);
                  return next;
                });
              }}
              onActionResult={({ jobId, action, ok }) => {
                if (!ok) {
                  setHiddenIds((prev) => {
                    const next = new Set(prev);
                    next.delete(jobId);
                    return next;
                  });
                }
                showToast({ text: jobActionToastText(action, ok), tone: ok ? "default" : "error" });
              }}
            />
          ))}
          {visible.length > rendered.length && (
            <button
              type="button"
              onClick={() => setShown((n) => n + PAGE_SIZE)}
              className={cn(buttonVariants({ variant: "soft", size: "md" }), "w-full justify-center")}
            >
              显示更多（还有 {visible.length - rendered.length} 个）
            </button>
          )}
          {visible.length === 0 && (
            <div className="rounded-[1.5rem] border border-dashed border-black/[0.12] bg-white/45 px-6 py-12 text-center dark:border-white/[0.1] dark:bg-white/[0.05]">
              <h3 className="t-h3 ink-1">这个行业暂时没有可推荐的在招岗位</h3>
              <p className="t-body-sm mx-auto mt-2 max-w-md text-pretty ink-2">
                换个行业看看，或者直接
                <Link href="/jobs" className="t-label mx-1 underline underline-offset-2 hover:opacity-80">
                  搜索完整岗位库
                </Link>
                。
              </p>
            </div>
          )}
        </div>
      </section>

      <p className="t-caption ink-3">
        以上均为企业官网公开岗位，点击直达官方详情页。
        <Link href="/jobs" className="ml-1 underline underline-offset-2 hover:opacity-80">
          去岗位库按条件搜索
        </Link>
      </p>

      <ActionToast toast={toast} onDismiss={dismissToast} />
    </div>
  );
}

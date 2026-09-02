"use client";

// 校招专区客户端：公司卡 + 徽章 + 校招/实习切换 + 城市/学历/职能筛选 + 展开分组渲染 JobCard + 展示时探活。
// 数据已由服务端按必投清单公司聚合好（app/campus/page.tsx → getCampusZone），本组件只做客户端交互层。
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Briefcase,
  CaretDown,
  Flag,
  GraduationCap,
  MapPin,
} from "@phosphor-icons/react";
import { EmptyPanel } from "@/components/ProductChrome";
import CompanyLogo from "@/components/CompanyLogo";
import CompanyInsightDrawer from "@/components/CompanyInsightDrawer";
import JobCard from "@/components/JobCard";
import SaveToast, { type SaveState } from "@/components/SaveToast";
import {
  requestInsightAvailability,
  getCachedAvailability,
  subscribeAvailability,
} from "@/lib/insight-client";
import { groupCampusJobs } from "@/lib/campus-zone";
import { formatDateLabel } from "@/lib/relative-time";
import {
  campusRowMatches,
  countMatchingFacets,
  selectFacetIndexes,
  type CampusFacet,
  type CampusFilterOptions,
} from "@/lib/campus-facets";
import { cn } from "@/lib/utils";
import type { WindowState } from "@/lib/campus-zone";
import type { ScoredJob } from "@/lib/types";
import type { CampusTimeline } from "@/lib/recruitment-cycle";

/** 一张公司卡。**不含任何单条岗位记录**——只有聚合分面（见 lib/campus-facets.ts）：
 *  逐条下发实测单页 2.09 MB / 16,494 条，而客户端拿它们只做两件事（填筛选下拉、算筛选后计数），
 *  两件事都只依赖分面那四个维度。完整岗位行在用户展开某家公司时经 /api/campus-zone/jobs 按需取回。 */
export type CampusBoardCard = {
  company: string;
  pattern: string;
  campusTotal: number;
  internTotal: number;
  campusFacets: CampusFacet[];
  internFacets: CampusFacet[];
  // windowStatus 的输入：徽章由页面按「此刻」现算，缓存里不放随时间失效的结论
  hasCampusSource: boolean;
  hasAnySource: boolean;
  lastSeenAtMs: number | null;
  window: WindowState;
  nearestDeadlineMs: number | null;
  timeline: CampusTimeline | null;
  preciseDates: { label: string; batch: string }[];
  batchTimingGap: string | null;
  cleanDeadlineMs: number | null;
  // 近 7 天检测到「校招岗一次性放量」= 正式批开闸（判据 crawler/campus_lane.detect_surge）
  surge: { atMs: number; fromCount: number | null; toCount: number } | null;
  // 明确标了往届（如 2026 届）而被移出列表的岗数；不静默丢弃，卡面照实说一句
  pastClassJobCount: number;
};

type RecruitMode = "campus" | "intern";
type PrimaryAction = "saved" | "ignored" | "applied";

const WINDOW_BADGE: Record<
  WindowState["state"],
  { icon: string; label: string; className: string }
> = {
  hiring: {
    icon: "🟢",
    label: "招聘中",
    className:
      "border border-[#bcdcae] dark:border-[#a3d06a]/[0.30] bg-[#e6f2d6] dark:bg-[#a3d06a]/[0.15] text-[#4f6f2a] dark:text-[#a3d06a]",
  },
  no_campus_now: {
    icon: "⚪",
    label: "当前未观测到在招校招岗",
    className:
      "border border-black/[0.08] dark:border-white/[0.1] bg-[#f4efe6] dark:bg-[#16130f] text-[#8a8275] dark:text-[#9a9184]",
  },
  stale: {
    icon: "⏳",
    label: "数据待更新",
    className:
      "border border-[#e7c98a] dark:border-[#e0b15a]/[0.30] bg-[#fbeecb] dark:bg-[#e0b15a]/[0.15] text-[#8a6312] dark:text-[#e0b15a]",
  },
  not_ingested: {
    icon: "⚙️",
    label: "待接入",
    className:
      "border border-[#b7d2ee] dark:border-[#7fb2e8]/[0.30] bg-[#dceafa] dark:bg-[#7fb2e8]/[0.15] text-[#2f6299] dark:text-[#7fb2e8]",
  },
};

// ⚙️ 待接入卡不向用户暴露子原因（no_source / source_only_social）——只在 tooltip 里说一句通用文案。
const NOT_INGESTED_TOOLTIP = "该公司校招源接入中";

function WindowBadge({ window }: { window: WindowState }) {
  const badge = WINDOW_BADGE[window.state];
  const title = window.state === "not_ingested" ? NOT_INGESTED_TOOLTIP : undefined;
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-medium ${badge.className}`}
    >
      <span aria-hidden="true">{badge.icon}</span>
      {badge.label}
    </span>
  );
}

// 把校招专区聚合 SQL 返回的原始岗位行（snake_case，无打分字段）适配成 JobCard 需要的 ScoredJob 形状。
// 该查询没有取 user_action/salary_text/source_id 等字段（专区场景不需要个性化打分），一律填安全默认值；
// match_score=0 + matched_keywords=[] → JobCard 不渲染匹配档位徽标（本区靠窗口徽章，不是相关性打分）。
function toScoredJob(job: any): ScoredJob {
  return {
    id: job.id,
    source_id: job.source_id ?? null,
    company: job.company,
    title: job.title,
    location: job.city ?? null,
    country_code: job.country_code ?? null,
    job_scope: job.job_scope ?? null,
    job_type: job.job_type ?? null,
    grad_class: job.grad_class ?? null,
    summary: job.summary ?? null,
    sponsorship_signal: job.sponsorship_signal ?? null,
    jd_url: job.jd_url,
    apply_url: job.apply_url ?? null,
    salary_text: job.salary_text ?? null,
    posted_at: job.posted_at ?? null,
    experience: job.experience ?? null,
    education: job.education ?? null,
    deadline: job.deadline ?? null,
    first_seen_at: job.first_seen_at,
    last_seen_at: job.last_seen_at,
    enrich_checked_at: job.enrich_checked_at ?? null,
    confirmed_closed_at: job.confirmed_closed_at ?? null,
    status: job.status || "active",
    content_hash: job.content_hash ?? null,
    created_at: job.created_at || job.first_seen_at,
    match_score: 0,
    matched_keywords: [],
    hidden_reason: null,
    user_action: null,
    source_adapter: job.source_adapter ?? null,
  };
}

interface CampusFilters {
  city: string;
  education: string;
  jobFunction: string;
  gradClass: number | null;
}

const EMPTY_FILTERS: CampusFilters = { city: "", education: "", jobFunction: "", gradClass: null };

type DisputeReason = "not_campus" | "dead_link" | "closed";

const DISPUTE_REASONS: { reason: DisputeReason; label: string }[] = [
  { reason: "not_campus", label: "这不是校招" },
  { reason: "dead_link", label: "链接失效" },
  { reason: "closed", label: "已结束" },
];

export default function CampusClient({
  cards,
  industries,
  hasIndustry,
  filterOptions,
}: {
  cards: CampusBoardCard[];
  industries: string[];
  hasIndustry: boolean;
  filterOptions: { campus: CampusFilterOptions; intern: CampusFilterOptions };
}) {
  const [mode, setMode] = useState<RecruitMode>("campus");
  const [filters, setFilters] = useState<CampusFilters>(EMPTY_FILTERS);
  // 手风琴：同一时刻只允许一家公司展开（同时展开多家会把三列网格撑成一长条，页面很乱）。
  const [expandedPattern, setExpandedPattern] = useState<string | null>(null);

  // 公司洞察抽屉（P3a 外露）：公司卡级只拉一次可用性（比每个 JobCard 各拉更省），暂无实录/派生的公司不给点。
  const [insightCompany, setInsightCompany] = useState<string | null>(null);
  const [, forceAvailTick] = useState(0);
  useEffect(() => {
    cards.forEach((c) => requestInsightAvailability(c.company));
    const unsub = subscribeAvailability(() => forceAvailTick((n) => n + 1));
    return unsub;
  }, [cards]);

  function toggleExpand(pattern: string) {
    setExpandedPattern((cur) => (cur === pattern ? null : pattern));
  }

  // 当前态（校招/实习）下每家公司的聚合分面——先按 mode 取桶，其余步骤共用。
  const facetsByMode = useMemo(
    () => cards.map((c) => (mode === "campus" ? c.campusFacets : c.internFacets)),
    [cards, mode],
  );

  // 筛选下拉候选值由**服务端**下发（那边用完整 summary 跑同一份 classifyJobFunction，
  // 值与此前客户端现算的逐字节一致）。客户端因此不再需要 JD 正文，也不需要逐条岗位记录——
  // 分面里的下标就指向这几个数组。见 app/campus/page.tsx 的 buildFacets。
  const { cityOptions, educationOptions, functionOptions, gradClassOptions } =
    mode === "campus" ? filterOptions.campus : filterOptions.intern;

  const activeOptions = mode === "campus" ? filterOptions.campus : filterOptions.intern;
  const selected = useMemo(() => selectFacetIndexes(filters, activeOptions), [filters, activeOptions]);

  // 每家公司在当前态 + 当前筛选下的岗位数（卡面计数）。分面已按四元组去重，
  // 累加它们的计数与逐条过滤的结果逐位相同，但只需遍历约两千条而不是一万六。
  const filteredCountByPattern = useMemo(() => {
    const map = new Map<string, number>();
    cards.forEach((card, i) => {
      map.set(card.pattern, countMatchingFacets(facetsByMode[i], selected));
    });
    return map;
  }, [cards, facetsByMode, selected]);

  const activeFilterCount = [filters.city, filters.education, filters.jobFunction, filters.gradClass]
    .filter((value) => value !== "" && value !== null).length;
  const hasActiveFilter = activeFilterCount > 0;

  // 展开某家公司时按需取回该公司当前桶的完整岗位行（页面一条岗位记录都没下发，见 CampusFacet）。
  // key = `pattern|mode`：校招与实习是两批岗，切模式必须重取（旧实现只按 pattern 存，
  // 且把两桶 id 拼起来截前 200 → 大厂实习桶会被校招桶挤没，展开区空白）。
  // 未取回前展开区显示加载态；失败则清掉请求标记，下次展开可重试。
  type FetchedJobs = { rows: any[]; total: number };
  const [fullJobs, setFullJobs] = useState<Map<string, FetchedJobs>>(new Map());
  const fullJobsRequested = useRef<Set<string>>(new Set());
  // 手风琴同时只可能展开一家（expandedPattern），所以这里只取当前那一家。
  useEffect(() => {
    const pattern = expandedPattern;
    if (!pattern) return;
    const key = `${pattern}|${mode}`;
    if (fullJobsRequested.current.has(key)) return;
    const card = cards.find((c) => c.pattern === pattern);
    if (!card) return;
    if ((mode === "campus" ? card.campusTotal : card.internTotal) === 0) return;
    fullJobsRequested.current.add(key);
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/campus-zone/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pattern, mode }),
        });
        const data = await resp.json().catch(() => null);
        if (cancelled) return;
        if (!data?.ok) {
          fullJobsRequested.current.delete(key); // 失败清标记，收起再展开可重试
          return;
        }
        setFullJobs((prev) =>
          new Map(prev).set(key, { rows: data.jobs || [], total: data.total ?? (data.jobs || []).length }),
        );
      } catch {
        if (!cancelled) fullJobsRequested.current.delete(key);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [expandedPattern, mode, cards]);

  /** 展开区要渲染的完整行：取回后按当前筛选过一遍，口径与卡面计数一致
   *  （`row.fn` 由接口随行返回，与分面里的职能标签同源同值）。 */
  function expandedRows(pattern: string): any[] {
    const fetched = fullJobs.get(`${pattern}|${mode}`);
    if (!fetched) return [];
    return fetched.rows.filter((r: any) => campusRowMatches(r, filters));
  }

  // 展示时探活（②层，复刻 app/jobs/jobs-client.tsx）：对当前展开公司里可见的岗位批量探活，
  // 死的当场从渲染里隐藏。deadIds 全局共享（同一岗位 id 不会同时出现在两家公司下）。
  const [deadIds, setDeadIds] = useState<Set<string>>(new Set());
  const livenessRequested = useRef<Set<string>>(new Set());
  useEffect(() => {
    const visibleIds: string[] = [];
    if (expandedPattern) {
      for (const j of expandedRows(expandedPattern)) {
        if (j.id) visibleIds.push(j.id);
      }
    }
    const ids = visibleIds
      .filter((id) => !livenessRequested.current.has(id) && !deadIds.has(id))
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
        // 静默：探不动就不动，后台 sweep/审计兜底
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedPattern, mode, fullJobs, filters]);

  // JobCard 要求的回调；本区岗位不预取 job_actions（专区场景无需个性化打分/回填 user_action），
  // 值得投/已投递/忽略仍会经 JobCard 内部走 /api/job-actions 真实写库，只是不需要在此处再镜像一份状态。
  function handleActionChange(_jobId: string, _action: PrimaryAction | null) {}

  // 用户纠错入口（这不是校招/链接失效/已结束）：写 /api/campus-zone/dispute → events 复核队列。
  // 只跟踪「哪张卡的反馈菜单展开」+ 一个共享 SaveToast 提交态，不镜像已反馈的岗位集合（允许重复反馈）。
  const [disputeOpenId, setDisputeOpenId] = useState<string | null>(null);
  const [disputeSaveState, setDisputeSaveState] = useState<SaveState>("idle");

  async function submitDispute(jobId: string, reason: DisputeReason) {
    setDisputeOpenId(null);
    setDisputeSaveState("saving");
    try {
      const resp = await fetch("/api/campus-zone/dispute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId, reason }),
      });
      const data = await resp.json().catch(() => null);
      setDisputeSaveState(resp.ok && data?.ok ? "done" : "error");
    } catch {
      setDisputeSaveState("error");
    }
  }

  return (
    <div className="mt-8 space-y-6 text-[#1a1714] dark:text-[#f3ecdf]">
      {!hasIndustry && (
        <p className="rounded-xl border border-[#cfe0f5] dark:border-[#7fb2e8]/[0.30] bg-[#e8f1fc] dark:bg-[#7fb2e8]/[0.15] px-4 py-3 text-sm leading-6 text-[#2f6299] dark:text-[#7fb2e8]">
          你还没设置简历行业，当前按默认行业展示。到
          <Link href="/preferences" className="mx-1 underline underline-offset-2 hover:text-[#1a1714] dark:hover:text-[#f3ecdf]">
            偏好设置
          </Link>
          完善简历行业，可精准锁定你的目标公司。
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-[#5f594e] dark:text-[#b6ad9d]">
          已接入官方校招源并持续验证的岗位 · 按行业「{industries.join("、")}」匹配 {cards.length} 家必投目标公司
        </p>
      </div>

      <div className="surface space-y-3 p-4 sm:p-5">
        {/* 校招 / 实习切换：驱动卡面计数、展开区与探活取哪个桶。 */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-black/[0.06] pb-3 dark:border-white/[0.1]">
          <p className="text-sm font-medium text-[#5f594e] dark:text-[#b6ad9d]">岗位范围与筛选</p>
          <div className="inline-flex shrink-0 rounded-full border border-black/[0.08] bg-white/60 p-1 dark:border-white/[0.1] dark:bg-white/[0.05]">
            {(["campus", "intern"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={cn(
                  "rounded-full px-3.5 py-1.5 text-sm font-medium transition",
                  mode === m
                    ? "bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                    : "text-[#8a8275] hover:text-[#1a1714] dark:text-[#9a9184] dark:hover:text-[#f3ecdf]",
                )}
              >
                {m === "campus" ? "校招" : "实习"}
              </button>
            ))}
          </div>
        </div>

        {/* 选项全部来自当前模式已下发的岗位；往届岗位已在服务端过滤，届别不会出现空结果。 */}
        <div className="flex flex-wrap items-end gap-3" role="group" aria-label="岗位筛选">
          <FilterSelect
            icon={MapPin}
            label="城市"
            value={filters.city}
            onChange={(v) => setFilters((f) => ({ ...f, city: v }))}
            options={cityOptions}
            allLabel="全部城市"
          />
          <FilterSelect
            icon={GraduationCap}
            label="学历"
            value={filters.education}
            onChange={(v) => setFilters((f) => ({ ...f, education: v }))}
            options={educationOptions}
            allLabel="学历不限"
          />
          <FilterSelect
            icon={Briefcase}
            label="职能"
            value={filters.jobFunction}
            onChange={(v) => setFilters((f) => ({ ...f, jobFunction: v }))}
            options={functionOptions}
            allLabel="全部职能"
          />
          <FilterSelect
            icon={GraduationCap}
            label="届别"
            value={filters.gradClass ?? ""}
            onChange={(v) => setFilters((f) => ({ ...f, gradClass: v ? Number(v) : null }))}
            options={gradClassOptions}
            allLabel="全部届别"
            formatOption={(value) => `${value}届`}
          />
          {hasActiveFilter && (
            <div className="flex items-center gap-2 pb-0.5">
              <span className="text-xs font-medium text-[#8a6312] dark:text-[#e0b15a]">已筛选 {activeFilterCount} 项</span>
              <button
                type="button"
                onClick={() => setFilters(EMPTY_FILTERS)}
                className="rounded-full border border-black/[0.08] bg-white/70 px-3.5 py-2 text-sm font-medium text-[#5f594e] transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d] dark:hover:bg-white/[0.08]"
              >
                清空筛选
              </button>
            </div>
          )}
        </div>
      </div>

      {cards.length === 0 ? (
        <EmptyPanel title="暂无匹配公司" description="当前行业下没有必投清单公司，换一个行业试试。" />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {cards.map((card) => {
            const isExpanded = expandedPattern === card.pattern;
            const totalCount = mode === "campus" ? card.campusTotal : card.internTotal;
            const filteredCount = filteredCountByPattern.get(card.pattern) ?? 0;
            // 卡面计数用聚合分面；展开区渲染用按需取回的完整行，两者过同一套筛选口径。
            const fetched = fullJobs.get(`${card.pattern}|${mode}`);
            const rowsLoaded = !isExpanded || !!fetched;
            const visibleRows = isExpanded ? expandedRows(card.pattern) : [];
            const groups = isExpanded ? groupCampusJobs(visibleRows) : [];
            // 大厂一个桶可能上千个岗，展开区最多取回 200 个（见 /api/campus-zone/jobs）。
            // 截断了就照实说一句，不让用户以为「筛选后只剩这些」。
            const cappedBy = fetched && fetched.total > fetched.rows.length ? fetched.rows.length : 0;
            const modeLabel = mode === "campus" ? "校招" : "实习";

            return (
              <div key={card.pattern} className="contents">
                <div className="surface flex flex-col gap-3 p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <CompanyLogo company={card.company} size={28} />
                      <h3 className="min-w-0 truncate text-[15px] font-semibold leading-tight">{card.company}</h3>
                    </div>
                    <WindowBadge window={card.window} />
                  </div>
                  {/* 正式批开闸（近 7 天校招岗一次性放量）——秋招最该立刻行动的信号，放在最上面。
                      不写「新增 N 个」而写「一次性放出 N 个」：放量是校招的形态特征，也解释了为什么值得马上看。 */}
                  {card.surge && (
                    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12px] leading-5 text-[#9a4a1a] dark:text-[#f0a06a]">
                      <span className="inline-flex items-center gap-1 rounded-md border border-[#f0c3a0] bg-[#fce8d8] px-1.5 py-0.5 font-medium dark:border-[#f0a06a]/[0.30] dark:bg-[#f0a06a]/[0.15]">
                        🔥 刚开正式批
                      </span>
                      <span>
                        一次性放出 {card.surge.toCount}
                        {card.surge.fromCount != null && card.surge.fromCount > 0
                          ? `（此前 ${card.surge.fromCount}）`
                          : ""}
                      </span>
                    </div>
                  )}
                  {card.timeline && (
                    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12px] leading-5 text-[#8a8275] dark:text-[#9a9184]">
                      <span className="inline-flex items-center gap-1 rounded-md border border-[#b7d2ee] bg-[#dceafa] px-1.5 py-0.5 font-medium text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]">
                        据往年
                      </span>
                      <span>{card.timeline.gradClass}</span>
                      {card.timeline.batchBits.map((bit) => (
                        <span key={bit}>· {bit}</span>
                      ))}
                      {card.timeline.phaseLabel && (
                        <span className="font-medium text-[#8a6312] dark:text-[#e0b15a]">
                          · {card.timeline.phaseLabel}
                        </span>
                      )}
                    </div>
                  )}
                  {/* P3：今年精确日期（官方公告，绿系强档）。措辞三档：据官方公告 > 据在招岗位 > 据往年。 */}
                  {card.preciseDates.length > 0 && (
                    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12px] leading-5 text-[#4f6f2a] dark:text-[#a3d06a]">
                      <span className="inline-flex items-center gap-1 rounded-md border border-[#bcdcae] bg-[#e6f2d6] px-1.5 py-0.5 font-medium text-[#4f6f2a] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]">
                        今年·据官方公告
                      </span>
                      {card.preciseDates.map((p) => (
                        <span key={p.batch}>· {p.label}</span>
                      ))}
                      {card.batchTimingGap && (
                        <span className="text-[#8a6312] dark:text-[#e0b15a]">· {card.batchTimingGap}</span>
                      )}
                    </div>
                  )}
                  {/* 快路①：无官方精确日期时，用清洗后的自有岗位 deadline 做弱档提示（灰系）。 */}
                  {card.preciseDates.length === 0 && card.cleanDeadlineMs && (
                    <p className="text-[12px] leading-5 text-[#8a8275] dark:text-[#9a9184]">
                      据在招岗位约{" "}
                      {formatDateLabel(card.cleanDeadlineMs, { month: "long", day: "numeric" })}{" "}
                      前截止
                    </p>
                  )}
                  <p className="text-sm text-[#5f594e] dark:text-[#b6ad9d]">
                    {totalCount > 0
                      ? `${totalCount} 个${modeLabel}在招岗位${
                          hasActiveFilter && isExpanded ? ` · 筛选后 ${filteredCount} 个` : ""
                        }`
                      : `暂无${modeLabel}在招岗位`}
                  </p>
                  {/* 往届岗不静默丢弃：说清楚「有但不是这一届」，免得用户以为我们漏抓。
                      只有岗位文本里写明届别（如「2026届」）的才会被挡；届别未知的岗照常在上面列着。 */}
                  {card.pastClassJobCount > 0 && (
                    <p className="text-[12px] leading-5 text-[#8a8275] dark:text-[#9a9184]">
                      另有 {card.pastClassJobCount} 个往届岗位未列出
                    </p>
                  )}
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    {totalCount > 0 && (
                      <button
                        type="button"
                        onClick={() => toggleExpand(card.pattern)}
                        aria-expanded={isExpanded}
                        className="inline-flex items-center justify-center gap-1.5 rounded-full border border-black/[0.08] bg-white/70 px-3.5 py-1.5 text-sm font-medium text-[#3f3a33] transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.08]"
                      >
                        {isExpanded ? "收起岗位" : "展开岗位"}
                        <CaretDown
                          className={cn("size-4 transition-transform", isExpanded && "rotate-180")}
                          aria-hidden="true"
                        />
                      </button>
                    )}
                    {(() => {
                      // P3a：公司卡级洞察入口。有实录(real>0)或岗位聚合派生才显，避免空抽屉。
                      const avail = getCachedAvailability(card.company);
                      if (!avail || (!avail.real && !avail.derived)) return null;
                      return (
                        <button
                          type="button"
                          onClick={() => setInsightCompany(card.company)}
                          className="inline-flex items-center justify-center gap-1.5 rounded-full border border-black/[0.08] bg-white/70 px-3.5 py-1.5 text-sm font-medium text-[#3f3a33] transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.08]"
                        >
                          {avail.real > 0 ? `公司洞察 ${avail.real}` : "公司洞察 · 岗位聚合"}
                        </button>
                      );
                    })()}
                  </div>
                </div>

                {isExpanded && (
                  <div className="sm:col-span-2 lg:col-span-3">
                    {!rowsLoaded ? (
                      <EmptyPanel title="正在加载岗位…" description={`共 ${filteredCount} 个，稍等一下。`} />
                    ) : groups.length === 0 ? (
                      <EmptyPanel title="当前筛选下没有匹配岗位" description="换一个城市、学历、职能或届别试试，或清空筛选。" />
                    ) : (
                      <div className="space-y-5">
                        {groups.map((group) => {
                          const visibleJobs = group.jobs.filter((j: any) => !deadIds.has(j.id));
                          if (visibleJobs.length === 0) return null;
                          return (
                            <div key={group.key} className="space-y-3">
                              <h4 className="flex items-center gap-1.5 text-sm font-semibold text-[#8a8275] dark:text-[#9a9184]">
                                <MapPin size={14} weight="fill" aria-hidden="true" />
                                {group.label} · {visibleJobs.length}
                              </h4>
                              <div className="space-y-3">
                                {visibleJobs.map((job: any) => (
                                  <div key={job.id} className="space-y-1.5">
                                    <JobCard job={toScoredJob(job)} onActionChange={handleActionChange} />
                                    <JobDisputeControl
                                      isOpen={disputeOpenId === job.id}
                                      onToggle={() =>
                                        setDisputeOpenId((cur) => (cur === job.id ? null : job.id))
                                      }
                                      onSubmit={(reason) => submitDispute(job.id, reason)}
                                    />
                                  </div>
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                    {cappedBy > 0 && (
                      <p className="mt-3 text-xs text-[#8a8275] dark:text-[#9a9184]">
                        该公司{modeLabel}岗位较多，这里按临近截止优先展示前 {cappedBy} 个
                      </p>
                    )}
                    {deadIds.size > 0 && (
                      <p className="mt-3 text-xs text-[#8a8275] dark:text-[#9a9184]">
                        实时复核拦下 {visibleRows.filter((j: any) => deadIds.has(j.id)).length} 个
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <SaveToast
        state={disputeSaveState}
        savingText="提交中…"
        doneText="已收到，感谢反馈"
        errorText="提交失败，请重试"
        onDismiss={() => setDisputeSaveState("idle")}
      />

      {insightCompany && (
        <CompanyInsightDrawer
          company={insightCompany}
          open={!!insightCompany}
          onClose={() => setInsightCompany(null)}
        />
      )}
    </div>
  );
}

// 单个岗位的反馈入口：点「反馈」展开三个理由 chip，选中即提交。不改 JobCard，独立渲染在卡片下方。
function JobDisputeControl({
  isOpen,
  onToggle,
  onSubmit,
}: {
  isOpen: boolean;
  onToggle: () => void;
  onSubmit: (reason: DisputeReason) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 px-1">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        className="inline-flex items-center gap-1 rounded-full px-1.5 py-1 text-xs font-medium text-[#8a8275] transition hover:text-[#5f594e] dark:text-[#9a9184] dark:hover:text-[#d9d0c2]"
      >
        <Flag size={12} weight="bold" aria-hidden="true" />
        反馈
      </button>
      {isOpen &&
        DISPUTE_REASONS.map((r) => (
          <button
            key={r.reason}
            type="button"
            onClick={() => onSubmit(r.reason)}
            className="rounded-full border border-black/[0.08] bg-white/70 px-2.5 py-1 text-xs font-medium text-[#5f594e] transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d] dark:hover:bg-white/[0.08]"
          >
            {r.label}
          </button>
        ))}
    </div>
  );
}

function FilterSelect({
  icon: Icon,
  label,
  value,
  onChange,
  options,
  allLabel,
  formatOption,
}: {
  icon: typeof MapPin;
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  options: Array<string | number>;
  allLabel: string;
  formatOption?: (value: string | number) => string;
}) {
  return (
    <label className="flex min-w-[9rem] flex-1 flex-col gap-1 text-xs font-medium text-[#8a8275] dark:text-[#9a9184] sm:flex-none">
      <span className="inline-flex items-center gap-1.5">
        <Icon size={14} weight="fill" aria-hidden="true" />
        {label}
      </span>
      <select
        value={String(value)}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-xl border border-black/[0.09] dark:border-white/[0.1] bg-white dark:bg-[#1e1a15] px-3 py-2 text-sm text-[#1a1714] dark:text-[#f3ecdf] transition duration-200 focus:border-[#1a1714]/55 dark:focus:border-white/55 focus:outline-none"
      >
        <option value="">{allLabel}</option>
        {options.map((opt) => (
          <option key={String(opt)} value={String(opt)}>
            {formatOption ? formatOption(opt) : opt}
          </option>
        ))}
      </select>
    </label>
  );
}

"use client";

// 校招专区客户端：公司卡 + 徽章 + 校招/实习切换 + 城市/学历/职能筛选 + 展开分组渲染 JobCard + 展示时探活。
// 数据已由服务端按必投清单公司聚合好（app/campus/page.tsx → getCampusZone），本组件只做客户端交互层。
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import {
  groupCampusJobs,
  compareCompanyCardsByFit,
  isCampusView,
  CAMPUS_VIEW_STORAGE_KEY,
  type CampusView,
  type RecruitMode,
} from "@/lib/campus-zone";
import CampusAllJobs from "./campus-all-jobs";
import { formatDateLabel } from "@/lib/relative-time";
// 只引类型：该模块带 `server-only`，type-only import 编译期擦除，不会把它拉进客户端包。
import type { CampusIndustrySource } from "@/lib/campus-user-industries";
import { Badge, Segmented } from "@/components/ui";
import {
  countMatchingFacets,
  countUnlabeledInMatch,
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
  /** 「对你有货」：该公司当前校招/实习岗里对得上用户方向（+ 城市）的条数。
   *  `null` = 判不出用户方向（不是 0——0 会被读成「一个都没有」，那是另一回事）。
   *  服务端按用户私有画像现算，不进按行业共享的快照（见 app/campus/page.tsx）。 */
  fitCampusCount: number | null;
  fitInternCount: number | null;
  /** 排序用的「当前模式」视图（compareCompanyCardsByFit 读这两个键）：服务端按校招模式填，
   *  切到实习时客户端换成实习那一列再用同一个比较器重排。 */
  fitCount?: number | null;
  fitTotal?: number;
};

type PrimaryAction = "saved" | "ignored" | "applied";

const WINDOW_BADGE: Record<
  WindowState["state"],
  { icon: string; label: string; className: string }
> = {
  hiring: {
    icon: "🟢",
    label: "招聘中",
    className:
      "border border-tone-green-border bg-tone-green-bg text-tone-green-fg",
  },
  no_campus_now: {
    icon: "⚪",
    label: "当前未观测到在招校招岗",
    className:
      "border border-black/[0.08] dark:border-white/[0.1] bg-[#f4efe6] dark:bg-[#16130f] ink-3",
  },
  stale: {
    icon: "⏳",
    label: "数据待更新",
    className:
      "border border-tone-amber-border bg-tone-amber-bg text-tone-amber-fg",
  },
  not_ingested: {
    icon: "⚙️",
    label: "待接入",
    className:
      "border border-tone-sky-border bg-tone-sky-bg text-[#2f6299] dark:text-[#7fb2e8]",
  },
};

// ⚙️ 待接入卡不向用户暴露子原因（no_source / source_only_social）——只在 tooltip 里说一句通用文案。
const NOT_INGESTED_TOOLTIP = "该公司校招源接入中";

// 时间线依据 → 用户看到的措辞。三档强弱：官方公告 > 公开信息 > 往年规律。
// 由 campusTimelineSummary 算出的 basis 决定，绝不硬编码（见 lib/recruitment-cycle.ts 的注释）。
const TIMELINE_BASIS_LABEL: Record<"official" | "public" | "historical", string> = {
  official: "今年·据官方公告",
  public: "今年·据公开信息",
  historical: "据往年",
};

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
  cards: cardsInput,
  industries,
  industrySource,
  generatedLabel = null,
  filterOptions,
  seasonGradClass,
  fitFunctions = [],
  fitCities = [],
  libraryCounts = null,
  jobScope = "domestic",
}: {
  cards: CampusBoardCard[];
  industries: string[];
  /** 行业来源：偏好手填 / 简历兜底 / 两边都空走默认（见 lib/campus-user-industries）。 */
  industrySource: CampusIndustrySource;
  /** 用户方向（classifyJobFunction 归一后的职能名）。空 = 判不出方向，卡面不提「对口」。 */
  fitFunctions?: string[];
  /** 用户目标城市（原始写法），仅用于在说明行里照实写清这份排序依据了什么。 */
  fitCities?: string[];
  /** 看板快照的年龄（服务端算好的文案，如「12 分钟前」）；null 时不渲染。 */
  generatedLabel?: string | null;
  filterOptions: { campus: CampusFilterOptions; intern: CampusFilterOptions };
  /** 当前校招季的目标届别（服务端 currentGradClass() 算好传入，避免年界处 SSR/hydration 不一致）。
   *  没有官方周期数据的公司，校招卡也用它兜一个「N届」标签，不至于一个标签都没有。 */
  seasonGradClass: number;
  /** 校招岗位库的库存量级（精确计数，来自 countCampusLibrary）；取不到时为 null，界面就不提这句。 */
  libraryCounts?: { campus: number; intern: number } | null;
  jobScope?: string | null;
}) {
  const [mode, setMode] = useState<RecruitMode>("campus");
  // 视图：`all` = 全部校招岗（默认，创始人 2026-09-18 定），`must` = 必投 30 家。
  // ⚠️ 初始值**必须**是常量 `all`，不能在 useState 里读 localStorage —— 服务端渲染不出它，
  // 放初始值就是 hydration 不一致（同 CLAUDE.md 那条 SSR 日期时区的坑）。读取放 useEffect。
  const [view, setView] = useState<CampusView>("all");
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(CAMPUS_VIEW_STORAGE_KEY);
      if (isCampusView(saved)) setView(saved);
    } catch {
      // 隐私窗口 / 站点数据被清时 localStorage 会抛。记不住视图是小事，页面挂了是大事。
    }
  }, []);
  function chooseView(next: CampusView) {
    setView(next);
    try {
      window.localStorage.setItem(CAMPUS_VIEW_STORAGE_KEY, next);
    } catch {
      // 同上：存不住就算了，本次会话内照常生效。
    }
  }
  // 服务端已按「校招模式的对口数」排好；切到实习要按实习那一列重排（同一个比较器，口径不会漂）。
  // 校招模式下结果与服务端逐位相同 → 首屏不会有 hydration 差异。
  const cards = useMemo(() => {
    if (mode === "campus") return cardsInput;
    return cardsInput
      .map((c) => ({ ...c, fitCount: c.fitInternCount, fitTotal: c.internTotal }))
      .sort(compareCompanyCardsByFit);
  }, [cardsInput, mode]);
  const fitKnown = fitFunctions.length > 0;
  const [filters, setFilters] = useState<CampusFilters>(EMPTY_FILTERS);
  // 手风琴：同一时刻只允许一家公司展开（同时展开多家会把三列网格撑成一长条，页面很乱）。
  const [expandedPattern, setExpandedPattern] = useState<string | null>(null);

  // 公司洞察抽屉（P3a 外露）：公司卡级只拉一次可用性（比每个 JobCard 各拉更省），暂无实录/派生的公司不给点。
  const [insightCompany, setInsightCompany] = useState<string | null>(null);
  const [, forceAvailTick] = useState(0);
  useEffect(() => {
    // 只在「必投」视图问可用性：默认的「全部校招岗」视图一张公司卡都不渲染，
    // 预拉 30 家的洞察可用性是纯浪费的一次网络往返。
    if (view !== "must") return;
    // 依赖 cardsInput 而不是排序后的 cards：切模式只换顺序、公司集合没变，不必重问一遍可用性。
    cardsInput.forEach((c) => requestInsightAvailability(c.company));
    const unsub = subscribeAvailability(() => forceAvailTick((n) => n + 1));
    return unsub;
  }, [cardsInput, view]);

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

  // 筛选结果里有多少条是**靠「未标注放行」才进来的**（岗位没写届别/学历/城市）。
  // 放行是对的（库里届别未知占 78.7%，硬筛等于藏掉四分之三），但必须照实说一句，
  // 否则用户会以为筛出来的每一条都确定符合条件 —— 那是另一种形式的骗人。
  const unlabeledInMatch = useMemo(() => {
    if (!hasActiveFilter) return 0;
    let n = 0;
    cards.forEach((_card, i) => {
      n += countUnlabeledInMatch(facetsByMode[i], selected);
    });
    return n;
  }, [cards, facetsByMode, selected, hasActiveFilter]);

  // 被筛的维度里，哪些会产生「未标注」（职能不算——它总有值，「其他」是分类不是缺失）。
  const unlabeledDims = [
    filters.gradClass !== null ? "届别" : null,
    filters.education ? "学历" : null,
    filters.city ? "城市" : null,
  ].filter(Boolean) as string[];

  // 展开某家公司时按需取该公司当前桶 + **当前筛选**下的完整岗位行，按页翻完全部（Phase B，2026-09-15）。
  // key = `pattern|mode|filterKey`：模式、筛选任一变化都是另一批结果，各自独立累计分页。
  // 服务端已按筛选 + 届别门筛好并回**精确 total**（职能/招聘类型已物化成列，数得起），这里只累计页、
  // 按 total 判要不要「加载更多」——去掉了旧的「前 200」硬顶（那正是用户反馈「岗位展示不全」的根因）。
  type DrawerPage = { jobs: any[]; total: number; loading: boolean; error: boolean };
  const [drawer, setDrawer] = useState<Map<string, DrawerPage>>(new Map());
  const drawerRequested = useRef<Set<string>>(new Set()); // 去重键 `key@offset`；失败时删除以便重试
  const filterKey = useMemo(
    () => JSON.stringify([filters.city, filters.education, filters.jobFunction, filters.gradClass]),
    [filters],
  );
  const drawerFor = useCallback(
    (pattern: string): DrawerPage | undefined => drawer.get(`${pattern}|${mode}|${filterKey}`),
    [drawer, mode, filterKey],
  );

  const loadPage = useCallback(
    async (pattern: string, offset: number) => {
      const key = `${pattern}|${mode}|${filterKey}`;
      const reqId = `${key}@${offset}`;
      if (drawerRequested.current.has(reqId)) return;
      drawerRequested.current.add(reqId);
      setDrawer((prev) => {
        const n = new Map(prev);
        const cur = n.get(key) ?? { jobs: [], total: 0, loading: false, error: false };
        n.set(key, { ...cur, loading: true, error: false });
        return n;
      });
      const fail = () => {
        drawerRequested.current.delete(reqId); // 失败可重试
        setDrawer((prev) => {
          const n = new Map(prev);
          const cur = n.get(key) ?? { jobs: [], total: 0, loading: false, error: false };
          n.set(key, { ...cur, loading: false, error: true });
          return n;
        });
      };
      try {
        const resp = await fetch("/api/campus-zone/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pattern, mode, offset, filters }),
        });
        const data = await resp.json().catch(() => null);
        if (!data?.ok) return fail();
        setDrawer((prev) => {
          const n = new Map(prev);
          const cur = n.get(key) ?? { jobs: [], total: 0, loading: false, error: false };
          const jobs = offset === 0 ? data.jobs || [] : [...cur.jobs, ...(data.jobs || [])];
          n.set(key, { jobs, total: data.total ?? jobs.length, loading: false, error: false });
          return n;
        });
      } catch {
        fail();
      }
    },
    [mode, filterKey, filters],
  );

  // 展开 / 切模式 / 改筛选 → 取第 0 页（drawerRequested 去重，不会重复请求同一 key@0）。
  useEffect(() => {
    const pattern = expandedPattern;
    if (!pattern) return;
    const card = cards.find((c) => c.pattern === pattern);
    if (!card) return;
    if ((mode === "campus" ? card.campusTotal : card.internTotal) === 0) return;
    loadPage(pattern, 0);
  }, [expandedPattern, mode, filterKey, cards, loadPage]);

  // 展示时探活（②层，复刻 app/jobs/jobs-client.tsx）：对当前展开公司里可见的岗位批量探活，
  // 死的当场从渲染里隐藏。deadIds 全局共享（同一岗位 id 不会同时出现在两家公司下）。
  const [deadIds, setDeadIds] = useState<Set<string>>(new Set());
  const livenessRequested = useRef<Set<string>>(new Set());
  useEffect(() => {
    const visibleIds: string[] = [];
    if (expandedPattern) {
      for (const j of drawerFor(expandedPattern)?.jobs ?? []) {
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
  }, [expandedPattern, mode, drawer, filterKey]);

  // JobCard 要求的回调；本区岗位不预取 job_actions（专区场景无需个性化打分/回填 user_action），
  // 收藏/已投递/忽略仍会经 JobCard 内部走 /api/job-actions 真实写库，只是不需要在此处再镜像一份状态。
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

  const modeLabelText = mode === "campus" ? "校招" : "实习";
  const libraryCount = libraryCounts ? (mode === "campus" ? libraryCounts.campus : libraryCounts.intern) : null;

  return (
    <div className="mt-8 space-y-6 ink-1">
      {/* 视图 + 模式两个开关横贯全页：视图决定「看全库还是看必投 30 家」，模式决定「校招还是实习」。
          两个视图共用同一个 mode —— 切过去不会莫名其妙回到校招。 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented
          ariaLabel="校招专区视图"
          value={view}
          onChange={chooseView}
          size="md"
          options={[
            { value: "all", label: "全部校招岗" },
            { value: "must", label: `必投 ${cards.length} 家` },
          ]}
        />
        <Segmented
          ariaLabel="招聘类型"
          value={mode}
          onChange={setMode}
          size="md"
          options={[
            { value: "campus", label: "校招" },
            { value: "intern", label: "实习" },
          ]}
        />
      </div>

      {view === "all" ? (
        <>
          {/* 库存量级的**精确**数字（countCampusLibrary）。它和下面列表里的「N 个匹配岗位」
              刻意是两个数、两种措辞：这条说「库里现在有多少」，那条说「你这组筛选匹配到多少」；
              后者撞取数上限时只能给「N+」（见 lib/match-total），不能拿它冒充库存量。 */}
          {libraryCount != null && (
            <p className="t-body-sm ink-2">
              全站在招{modeLabelText}岗 <span className="t-num ink-1">{libraryCount.toLocaleString("zh-CN")}</span> 个
              <span className="ink-3">（已滤掉往届；按你的偏好排序，不做隐藏）</span>
            </p>
          )}
          <CampusAllJobs mode={mode} jobScope={jobScope} mustApplyCount={cards.length} />
        </>
      ) : (
        // ⚠️ 这里是**函数调用**，不是把它当组件渲染。写成组件标签会让 React 每次父组件重渲染
        // 都看到一个**新的组件类型**（函数在 render 体内声明，每次渲染都是新对象）→ 整棵子树卸载重挂：
        // 展开区滚动位置丢、焦点丢、JobCard 的 effect 全部重跑。调用函数则只是把 JSX 内联进来。
        renderMustApplyBoard()
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

  /** 「必投 N 家」视图：原有全部形态原样保留（公司卡 / 窗口徽章 / 时间线 / 展开分页 / 反馈）。
   *  写成渲染函数而不是组件，① 让这次改动的 diff 只有「包一层」，不搬动任何既有逻辑；
   *  ② 避免「render 体内声明的组件每次都是新类型」导致的整棵子树卸载重挂（见调用处注释）。 */
  function renderMustApplyBoard() {
    return (
      <div className="space-y-6">
      {industrySource !== "preference" && (
        <p className="rounded-xl border border-[#cfe0f5] dark:border-[#7fb2e8]/[0.30] bg-[#e8f1fc] dark:bg-[#7fb2e8]/[0.15] px-4 py-3 text-sm leading-6 text-[#2f6299] dark:text-[#7fb2e8]">
          {industrySource === "resume"
            ? "你没填目标行业，这里按简历里识别出的行业展示。想换行业，到"
            : "你没填目标行业，简历里也没识别出行业，当前按默认行业展示。到"}
          <Link href="/me" className="mx-1 underline underline-offset-2 hover:opacity-80">
            个人中心
          </Link>
          的「进阶设置 → 目标行业」里填，可精准锁定你的目标公司。
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <p className="text-sm ink-2">
            已接入官方校招源并持续验证的岗位 · 按{industrySource === "resume" ? "简历行业" : industrySource === "preference" ? "目标行业" : "默认行业"}「{industries.join("、")}」匹配 {cards.length} 家必投目标公司{generatedLabel ? ` · 数据更新于 ${generatedLabel}` : ""}
          </p>
          {/* 排序依据照实写出来：清单是静态的北极星（不随你的方向增删公司），变的只是先看谁。
              判不出方向时不吹这句，改成一句可行动的提示。 */}
          <p className="t-caption ink-3">
            {fitKnown ? (
              <>
                必投清单固定 {cards.length} 家不变，已把「对你有货」的排在前面 —— 方向「{fitFunctions.join("、")}」
                {fitCities.length > 0 ? ` · 城市「${fitCities.join("、")}」` : ""}
              </>
            ) : (
              <>
                还判不出你的求职方向，暂按在招岗位数排序。到
                <Link href="/me" className="mx-1 underline underline-offset-2 hover:opacity-80">
                  偏好设置
                </Link>
                填目标岗位，可把「对你有货」的公司排到前面。
              </>
            )}
          </p>
        </div>
      </div>

      <div className="surface space-y-3 p-4 sm:p-5">
        {/* 校招 / 实习切换已提到页面顶部（两个视图共用同一个 mode），这里只留筛选。 */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-black/[0.06] pb-3 dark:border-white/[0.1]">
          <p className="text-sm font-medium ink-2">岗位范围与筛选</p>
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
              <span className="text-xs font-medium text-tone-amber-fg">已筛选 {activeFilterCount} 项</span>
              <button
                type="button"
                onClick={() => setFilters(EMPTY_FILTERS)}
                className="rounded-full border border-black/[0.08] bg-white/70 px-3.5 py-2 text-sm font-medium ink-2 transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:hover:bg-white/[0.08]"
              >
                清空筛选
              </button>
            </div>
          )}
        </div>

        {/* 诚实说明：岗位没写届别/学历/城市时按「未知」放行，不当作不符合。
            库里届别未知占 78.7%、学历空 38.6%，硬筛会把它们全藏掉（用户看到的「岗位太少」
            有一大半来自这里）；但放行之后必须说清楚，别让用户以为每条都确定符合。 */}
        {unlabeledInMatch > 0 && unlabeledDims.length > 0 && (
          <p className="t-caption ink-3">
            结果含 {unlabeledInMatch} 个未标注{unlabeledDims.join("/")}的岗位 —— 招聘方没写明，已按「可能符合」保留，投递前请看岗位详情确认。
          </p>
        )}
      </div>

      {cards.length === 0 ? (
        <EmptyPanel title="暂无匹配公司" description="当前行业下没有必投清单公司，换一个行业试试。" />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {cards.map((card) => {
            const isExpanded = expandedPattern === card.pattern;
            const totalCount = mode === "campus" ? card.campusTotal : card.internTotal;
            const fitCount = mode === "campus" ? card.fitCampusCount : card.fitInternCount;
            const filteredCount = filteredCountByPattern.get(card.pattern) ?? 0;
            // 展开区：服务端已按当前筛选筛好并分页（Phase B），这里按页累计、按 total 判「加载更多」。
            const page = isExpanded ? drawerFor(card.pattern) : undefined;
            const loadedCount = page?.jobs.length ?? 0;
            const drawerTotal = page?.total ?? filteredCount; // 精确 total（服务端）；未取回前用分面估算兜底
            const initialLoading = isExpanded && (!page || (page.loading && loadedCount === 0));
            const visibleRows = page?.jobs ?? [];
            const groups = isExpanded ? groupCampusJobs(visibleRows) : [];
            const hasMore = !!page && page.jobs.length < page.total;
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
                  {/* 招聘信息一律结构化成小标签（届别 / 提前批·正式批 / 现处阶段 / 截止），
                      不再堆成一串带「·」的长句（用户反馈「很乱」）。措辞仍由数据的 basis 推出、不写死。 */}
                  {card.surge && (
                    <Badge
                      tone="amber"
                      size="sm"
                      icon={<span aria-hidden="true">🔥</span>}
                      className="self-start font-medium"
                    >
                      刚开正式批 · 放出 {card.surge.toCount}
                      {card.surge.fromCount != null && card.surge.fromCount > 0
                        ? `（此前 ${card.surge.fromCount}）`
                        : ""}
                    </Badge>
                  )}
                  {(() => {
                    // 有官方精确日期 → 数据依据是「官方公告」(绿)，日期用官方那档；否则用 timeline 的 basis
                    // （公开信息 sky / 往年 neutral）+ batchBits。⚠️ 往年不可能有当届，措辞交给 basis，别写死。
                    const hasPrecise = card.preciseDates.length > 0;
                    const chips: JSX.Element[] = [];
                    // 数据依据标签：「今年·据官方公告 / 据公开信息」删掉（创始人 2026-09-15：噪音，且和「招聘中」大徽章挤在一起）。
                    // 只保留「据往年」—— 它不是噪音，是「这条时间线是按往年规律推的、今年官方还没确认」的诚实提醒，
                    // 删了会让推测显得像确认（有精确日期的官方档不受影响：绿色日期标签本身就表明是官方来源）。
                    if (!hasPrecise && card.timeline?.basis === "historical") {
                      chips.push(<Badge key="basis" tone="neutral" size="sm">{TIMELINE_BASIS_LABEL.historical}</Badge>);
                    }
                    // 届别：有官方周期数据用它；否则校招卡兜一个当季届别（本区已滤掉往届，剩的就是当季校招），
                    // 让没接入周期数据的公司也不至于「一个标签都没有」。实习不按届别，无数据就不显。
                    const gradLabel =
                      card.timeline?.gradClass ?? (mode === "campus" ? `${seasonGradClass}届` : null);
                    if (gradLabel) {
                      chips.push(<Badge key="gc" tone="neutral" size="sm">{gradLabel}</Badge>);
                    }
                    if (hasPrecise) {
                      card.preciseDates.forEach((p) =>
                        chips.push(<Badge key={`pd-${p.batch}`} tone="green" size="sm">{p.label}</Badge>),
                      );
                    } else if (card.timeline) {
                      card.timeline.batchBits.forEach((bit) =>
                        chips.push(<Badge key={`b-${bit}`} tone="neutral" size="sm">{bit}</Badge>),
                      );
                    }
                    // 「现处正式批/黄金期」标签删掉（创始人 2026-09-15：与「招聘中」大徽章重复）。
                    if (!hasPrecise && card.cleanDeadlineMs) {
                      chips.push(
                        <Badge key="dl" tone="neutral" size="sm">
                          约{formatDateLabel(card.cleanDeadlineMs, { month: "long", day: "numeric" })}截止
                        </Badge>,
                      );
                    }
                    return chips.length ? (
                      <div className="flex flex-wrap items-center gap-1.5">{chips}</div>
                    ) : null;
                  })()}
                  {/* 岗位数：结构化成醒目数字 + 单位，不写成句子。筛选后的数用绿标签另标。 */}
                  <div className="flex flex-wrap items-baseline gap-x-1.5 gap-y-1">
                    {totalCount > 0 ? (
                      <>
                        <span className="t-num text-[20px] font-semibold leading-none ink-1">{totalCount}</span>
                        <span className="text-sm ink-2">个{modeLabel}在招岗位</span>
                        {hasActiveFilter && isExpanded && (
                          <Badge tone="green" size="sm" className="ml-0.5">筛选后 {filteredCount}</Badge>
                        )}
                      </>
                    ) : (
                      <span className="text-sm ink-3">暂无{modeLabel}在招岗位</span>
                    )}
                  </div>
                  {/* 「对你有货」：清单不变，只把「你能投的」说清楚。
                      · 有对口岗 → 绿标给出条数（用户一眼知道这张卡值不值得点开）；
                      · 0 个但有别的岗 → 照实说「本季暂无对口岗」并带上其余岗数，不假装没岗、也不让用户白点。
                      判不出方向（fitCount == null）时两句都不出现 —— 不知道就别说。 */}
                  {fitCount !== null && totalCount > 0 && (
                    fitCount > 0 ? (
                      <Badge tone="green" size="sm" className="self-start font-medium">
                        有你能投的岗 {fitCount} 个
                      </Badge>
                    ) : (
                      <p className="t-caption ink-3">
                        本季暂无对口岗（有 {totalCount} 个其它{modeLabel}岗）
                      </p>
                    )
                  )}
                  {/* 往届岗不静默丢弃：说清楚「有但不是这一届」，免得用户以为我们漏抓。
                      只有岗位文本里写明届别（如「2026届」）的才会被挡；届别未知的岗照常在上面列着。 */}
                  {card.pastClassJobCount > 0 && (
                    <p className="text-[12px] leading-5 ink-3">
                      另有 {card.pastClassJobCount} 个往届岗位未列出
                    </p>
                  )}
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    {totalCount > 0 && (
                      <button
                        type="button"
                        onClick={() => toggleExpand(card.pattern)}
                        aria-expanded={isExpanded}
                        className="inline-flex items-center justify-center gap-1.5 rounded-full border border-black/[0.08] bg-white/70 px-3.5 py-1.5 text-sm font-medium ink-2 transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:hover:bg-white/[0.08]"
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
                          className="inline-flex items-center justify-center gap-1.5 rounded-full border border-black/[0.08] bg-white/70 px-3.5 py-1.5 text-sm font-medium ink-2 transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:hover:bg-white/[0.08]"
                        >
                          {avail.real > 0 ? `公司洞察 ${avail.real}` : "公司洞察 · 岗位聚合"}
                        </button>
                      );
                    })()}
                  </div>
                </div>

                {isExpanded && (
                  <div className="sm:col-span-2 lg:col-span-3">
                    {initialLoading ? (
                      <EmptyPanel title="正在加载岗位…" description={`共 ${drawerTotal} 个，稍等一下。`} />
                    ) : page?.error && loadedCount === 0 ? (
                      <EmptyPanel title="加载失败" description="收起再展开可重试。" />
                    ) : groups.length === 0 ? (
                      <EmptyPanel title="当前筛选下没有匹配岗位" description="换一个城市、学历、职能或届别试试，或清空筛选。" />
                    ) : (
                      <div className="space-y-5">
                        {groups.map((group) => {
                          const visibleJobs = group.jobs.filter((j: any) => !deadIds.has(j.id));
                          if (visibleJobs.length === 0) return null;
                          return (
                            <div key={group.key} className="space-y-3">
                              <h4 className="flex items-center gap-1.5 text-sm font-semibold ink-3">
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
                    {/* 加载更多：按页翻完当前筛选下的**全部**岗位（去掉了旧的「前 200」硬顶）。 */}
                    {hasMore && (
                      <div className="mt-4 flex justify-center">
                        <button
                          type="button"
                          disabled={page?.loading}
                          onClick={() => loadPage(card.pattern, loadedCount)}
                          className="inline-flex items-center justify-center gap-1.5 rounded-full border border-black/[0.08] bg-white/70 px-4 py-2 text-sm font-medium ink-2 transition hover:bg-white disabled:opacity-60 dark:border-white/[0.1] dark:bg-white/[0.05] dark:hover:bg-white/[0.08]"
                        >
                          {page?.loading ? "加载中…" : `加载更多（还有 ${Math.max(0, drawerTotal - loadedCount)} 个）`}
                        </button>
                      </div>
                    )}
                    {!hasMore && loadedCount > 0 && drawerTotal > loadedCount && (
                      // total 与已加载对不上又没有下一页（极少：翻页间隙有岗位下架/被 deadIds 隐藏）——照实说，不假装完整。
                      <p className="mt-3 text-xs ink-3">已加载 {loadedCount} 个（共约 {drawerTotal} 个）</p>
                    )}
                    {deadIds.size > 0 && (
                      <p className="mt-3 text-xs ink-3">
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
      </div>
    );
  }
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
        className="inline-flex items-center gap-1 rounded-full px-1.5 py-1 text-xs font-medium ink-3 transition hover:opacity-80"
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
            className="rounded-full border border-black/[0.08] bg-white/70 px-2.5 py-1 text-xs font-medium ink-2 transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:hover:bg-white/[0.08]"
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
    <label className="flex min-w-[9rem] flex-1 flex-col gap-1 text-xs font-medium ink-3 sm:flex-none">
      <span className="inline-flex items-center gap-1.5">
        <Icon size={14} weight="fill" aria-hidden="true" />
        {label}
      </span>
      <select
        value={String(value)}
        onChange={(e) => onChange(e.target.value)}
        className="min-h-11 rounded-xl border border-black/[0.09] dark:border-white/[0.1] bg-white px-3 py-2 text-sm ink-1 transition duration-200 focus:border-[#1a1714]/55 focus:outline-none dark:bg-[#1e1a15] dark:focus:border-white/55 lg:min-h-0"
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

"use client";

import { useState, useMemo, useEffect, useRef, Fragment } from "react";
import { useRouter } from "next/navigation";
import JobCard from "@/components/JobCard";
import JobFilters from "@/components/JobFilters";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import type { ScoredJob } from "@/lib/types";
import { useJobFilters, JOBS_PAGE_SIZE } from "@/hooks/useJobFilters";
import { useDiscoveryPoll, type BrowserDiscoveryState } from "@/hooks/useDiscoveryPoll";
import {
  ArrowsClockwise,
  CheckCircle,
  Circle,
  CircleNotch,
  Compass,
  Database,
  MagnifyingGlass,
  Sparkle,
} from "@phosphor-icons/react";

type PrimaryAction = "saved" | "ignored" | "applied";

interface Props {
  initialJobs: ScoredJob[];
  // 活跃岗位总数（SSR 查得）；前端据此后台分块拉完剩余岗位（解除展示硬上限）。
  initialTotal: number;
  // 从用户已保存偏好预填的筛选初值（城市/类型/关键词）；用户手动改即覆盖。
  initialFilters?: { city?: string; jobType?: string; keyword?: string };
}

export default function JobsClient({ initialJobs, initialTotal, initialFilters }: Props) {
  const [officialJobs, setOfficialJobs] = useState<ScoredJob[]>([]);
  // 后台分块把岗位库剩余岗位拉完（解除展示硬上限）：SSR 只给第一页，这里补齐到 initialTotal。
  const [extraJobs, setExtraJobs] = useState<ScoredJob[]>([]);
  const [libLoading, setLibLoading] = useState(false);
  const fillRef = useRef(false);
  // 本次搜索/发现完成后默认只看新岗位；用户可切回「查看全部」
  const [onlyNew, setOnlyNew] = useState(false);
  const [searchInfo, setSearchInfo] = useState("");
  const router = useRouter();

  // —— 后台拉全量岗位库（无展示硬上限）——
  // SSR 只渲染第一页；挂载后从第一页之后按 1000 一块拉到 initialTotal，合并进内存库。
  // 现有筛选 / 三桶 / 关键词扩展 / 排序全部在内存全量上跑，故需把全量拉进来（只是不再一次性塞 props）。
  useEffect(() => {
    if (fillRef.current) return;
    if (initialJobs.length >= initialTotal) return;
    fillRef.current = true;
    let cancelled = false;
    (async () => {
      setLibLoading(true);
      let offset = initialJobs.length;
      const LIMIT = 1000;
      for (let i = 0; i < 500 && !cancelled; i++) {
        try {
          const resp = await fetch(`/api/jobs/list?offset=${offset}&limit=${LIMIT}`);
          const data = await resp.json();
          const batch: ScoredJob[] = Array.isArray(data?.jobs) ? data.jobs : [];
          if (!data?.ok || batch.length === 0) break;
          if (cancelled) break;
          setExtraJobs((prev) => [...prev, ...batch]);
          offset += batch.length;
          if (batch.length < LIMIT) break;
        } catch {
          break;
        }
      }
      if (!cancelled) setLibLoading(false);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 内存库 = SSR 第一页 + 后台补齐的剩余页（按 id 去重）。
  const localJobs = useMemo(() => {
    if (extraJobs.length === 0) return initialJobs;
    const seen = new Set(initialJobs.map((j) => j.id));
    return [...initialJobs, ...extraJobs.filter((j) => !seen.has(j.id))];
  }, [initialJobs, extraJobs]);

  // 公司下拉项从内存库实时派生（随后台拉取增长）。
  const companies = useMemo(
    () => Array.from(new Set(localJobs.map((j) => j.company).filter(Boolean))) as string[],
    [localJobs],
  );

  // 筛选 state + 派生过滤链（useMemo 链整体在 hook 内）。
  const {
    filters,
    setFilters,
    sessionNewKeys,
    newViewActive,
    filtered,
    visibleCount,
    setVisibleCount,
    visibleJobs,
    exactCount,
    existingFilteredCount,
    newMatching,
  } = useJobFilters({ localJobs, officialJobs, onlyNew, initialFilters });

  // 「刷新公司库 / 联网爬新公司」状态机 + 轮询 + 持久化 + 超时（整体在 hook 内）。
  const { discovery, refreshing, discoveryActive, startDiscovery, startRefresh } =
    useDiscoveryPoll({ filters, setOfficialJobs, setSearchInfo });

  // P3 on-demand 富化：给用户当下看到的薄卡（无 summary）即时补 JD 正文。
  // 只发 jd_url，服务端只补简单 httpx 源（workday/hotjob）；其余/浏览器源留给后台 drain。
  // overlay 覆盖式打补丁（不改各 job 列表），requested ref 防重复请求/死循环。
  const [summaryOverlay, setSummaryOverlay] = useState<Record<string, string>>({});
  const enrichRequested = useRef<Set<string>>(new Set());
  useEffect(() => {
    const need = visibleJobs
      .filter(
        (j) =>
          j.jd_url &&
          !j.summary &&
          !summaryOverlay[j.jd_url] &&
          !enrichRequested.current.has(j.jd_url),
      )
      .map((j) => j.jd_url as string)
      .slice(0, 30);
    if (need.length === 0) return;
    need.forEach((u) => enrichRequested.current.add(u));
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/enrich", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ jd_urls: need }),
        });
        const data = await resp.json();
        if (!cancelled && data?.ok && data.filled && Object.keys(data.filled).length) {
          setSummaryOverlay((prev) => ({ ...prev, ...data.filled }));
        }
      } catch {
        // 静默降级：补不到就保持薄卡，后台 drain 兜
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleJobs]);

  // 一键放宽城市 + 岗位类型（保留关键词），让本次发现的岗位可见。
  function relaxLocationAndType() {
    setFilters((f) => ({ ...f, city: "", jobType: "" }));
    setOnlyNew(true);
  }

  function handleExistingJobsSearch() {
    track("search", { keyword: filters.keyword || "" });
    setOfficialJobs([]);
    setOnlyNew(false);
    setSearchInfo(
      `仅搜索本地岗位库，不触发外部请求。当前命中 ${existingFilteredCount} 个岗位。`,
    );
  }

  function handleActionChange(jobId: string, action: PrimaryAction | null) {
    setOfficialJobs((jobs) =>
      jobs.map((job) =>
        job.id === jobId
          ? {
              ...job,
              user_action: action,
              hidden_reason:
                action === "ignored"
                  ? "ignored"
                  : action === "applied"
                    ? "applied_by_default"
                    : null,
            }
          : job,
      ),
    );
    router.refresh();
  }

  return (
    <div className="space-y-5">
      <JobFilters filters={filters} onChange={setFilters} companies={companies} />
      <div className="surface p-4 text-[#1a1714] sm:p-5">
        <div className="mb-3.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold text-[#3f3a33]">
          <MagnifyingGlass size={16} weight="bold" aria-hidden="true" />
          获取岗位的三种方式
          <span className="text-xs font-normal text-[#9a9184]">（刷新公司库 = 刷你关注的公司，免填关键词；联网爬新公司 需先填「关键词」）</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <ActionTile
            icon={Database}
            label="搜索岗位库现有岗位"
            hint="只查本地库 · 不联网 · 秒出"
            tooltip="在已抓取入库的岗位里，按上方筛选条件即时检索，不发起任何联网请求，瞬时返回。"
            accent="bg-[#ece7dd] text-[#3f3a33]"
            onClick={handleExistingJobsSearch}
          />
          <ActionTile
            icon={ArrowsClockwise}
            label={refreshing ? "刷新中…" : "刷新公司库新岗位"}
            hint="刷你关注的全部公司 · 约 1–5 分钟"
            tooltip="后台用真爬虫刷新你筛选/偏好命中的全部公司源（含飞书 / 北森 / Moka 等浏览器源，按相关性取前若干家），新岗位实时流式并入列表。未填筛选时按你保存的求职偏好（目标公司等）刷。约 1–5 分钟。"
            accent="bg-[#dbe9fa] text-[#2f6299]"
            onClick={startRefresh}
            disabled={refreshing || discoveryActive}
            busy={refreshing}
          />
          <ActionTile
            icon={Compass}
            label={discoveryActive ? "联网爬取中…" : "联网爬新公司新岗位"}
            hint="真浏览器抓官网 · 补全描述 · 约 1–5 分钟"
            tooltip="用真实浏览器联网抓取尚未收录的公司官方招聘站，逐岗补全职位描述，保证返回有 summary 的可靠卡片，约 1–5 分钟。"
            accent="bg-[#e7def4] text-[#6a4fa0]"
            onClick={startDiscovery}
            disabled={refreshing || discoveryActive || !filters.keyword}
            busy={discoveryActive}
            hero
          />
        </div>
        {searchInfo && (
          <p className="mt-3 rounded-2xl border border-black/[0.06] bg-[#f6f3ec] px-3.5 py-2.5 text-pretty text-sm leading-6 text-[#5f594e]">
            {searchInfo}
          </p>
        )}
      </div>
      {discoveryActive && <BrowserDiscoveryProgress discovery={discovery} />}

      {officialJobs.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-[#cfe6b0] bg-[#eef6e0] px-3.5 py-2.5 text-sm">
          <Sparkle size={16} weight="fill" className="text-[#6f9a3a]" aria-hidden="true" />
          <span className="font-medium text-[#4f6f2a]">
            本次新发现 {officialJobs.length} 个岗位
            {(filters.city || filters.jobType || filters.keyword) &&
            newMatching.length !== officialJobs.length
              ? `（符合当前筛选 ${newMatching.length} 个）`
              : "（绿色标记）"}
          </span>
          <div className="ml-auto flex gap-1.5">
            <button
              type="button"
              onClick={() => setOnlyNew(true)}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium transition",
                newViewActive
                  ? "bg-[#cde8a0] text-[#3f5a1c]"
                  : "text-[#8a8275] hover:bg-black/[0.05] hover:text-[#1a1714]",
              )}
            >
              只看新发现
            </button>
            <button
              type="button"
              onClick={() => setOnlyNew(false)}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium transition",
                !newViewActive
                  ? "bg-[#1a1714] text-[#f7f1e6]"
                  : "text-[#8a8275] hover:bg-black/[0.05] hover:text-[#1a1714]",
              )}
            >
              查看全部
            </button>
          </div>
        </div>
      )}

      <p className="inline-flex items-center gap-2 rounded-full border border-black/[0.06] bg-white/55 px-3 py-2 text-sm leading-6 text-[#5f594e]">
        <MagnifyingGlass size={16} weight="bold" aria-hidden="true" />
        {newViewActive ? "只看本次新发现：" : "匹配 "}
        {filtered.length} 个岗位{filters.keyword ? `（精确 ${exactCount} + 相关 ${filtered.length - exactCount}）` : ""}，已展示 {Math.min(visibleCount, filtered.length)} 个（本地岗位库 {localJobs.length}{libLoading ? ` / 共 ${initialTotal}，载入中…` : ""} + 本次官网刷新/发现 {officialJobs.length}）。本地搜索、已知源刷新、动态官方源发现三层分开执行。
      </p>
      <div className="space-y-3">
        {visibleJobs.map((job, i) => {
          const tier = (job as any).__tier as "exact" | "related";
          const prevTier = i > 0 ? ((visibleJobs[i - 1] as any).__tier as string) : null;
          const showDivider =
            Boolean(filters.keyword) && tier === "related" && prevTier !== "related";
          return (
            <Fragment key={job.id}>
              {showDivider && (
                <div className="flex items-center gap-3 pt-4 pb-1" role="separator">
                  <span className="h-px flex-1 bg-black/[0.08]" />
                  <span className="whitespace-nowrap text-xs font-medium text-[#8a8275]">
                    相关岗位 · 同职能（标题未直接含「{filters.keyword}」）
                  </span>
                  <span className="h-px flex-1 bg-black/[0.08]" />
                </div>
              )}
              <JobCard
                job={
                  job.jd_url && summaryOverlay[job.jd_url]
                    ? { ...job, summary: summaryOverlay[job.jd_url] }
                    : job
                }
                sessionNew={sessionNewKeys.has(job.jd_url || job.id)}
                onActionChange={handleActionChange}
              />
            </Fragment>
          );
        })}
        {filtered.length === 0 &&
          (officialJobs.length > 0 && (filters.city || filters.jobType) ? (
            <div className="rounded-[1.5rem] border border-dashed border-[#e7c98a] bg-[#fbf2d8] px-6 py-10 text-center">
              <h2 className="text-lg font-semibold text-[#1a1714]">
                本次发现 {officialJobs.length} 个岗位，但 0 个符合当前筛选
              </h2>
              <p className="mx-auto mt-2 max-w-md text-pretty text-sm leading-6 text-[#6b655a]">
                发现的岗位未同时满足
                {filters.city ? ` 城市『${filters.city}』` : ""}
                {filters.jobType ? ` 类型『${filters.jobType}』` : ""}
                ——它们可能属于其它城市，或为社招 / 校招。放宽这两项即可查看本次发现的全部岗位。
              </p>
              <button
                type="button"
                onClick={relaxLocationAndType}
                className="mt-4 inline-flex items-center gap-2 rounded-full bg-[#1a1714] px-5 py-2 text-sm font-semibold text-[#f7f1e6] transition duration-200 hover:bg-[#2b2520] active:scale-[0.98]"
              >
                放宽城市 / 类型，查看全部 {officialJobs.length} 个发现
              </button>
            </div>
          ) : (
            <div className="rounded-[1.5rem] border border-dashed border-black/[0.12] bg-white/45 px-6 py-14 text-center">
              <h2 className="text-lg font-semibold text-[#1a1714]">没有匹配的岗位</h2>
              <p className="mx-auto mt-2 max-w-md text-pretty text-sm leading-6 text-[#6b655a]">
                可以放宽筛选条件，或输入关键词后刷新已知官网源 / 发现新的官方招聘入口。
              </p>
            </div>
          ))}
      </div>
      {filtered.length > visibleCount && (
        <div className="flex justify-center pt-1">
          <button
            type="button"
            onClick={() => setVisibleCount((n) => n + JOBS_PAGE_SIZE)}
            className="inline-flex items-center gap-2 rounded-full border border-black/[0.08] bg-white/70 px-5 py-2.5 text-sm font-medium text-[#3f3a33] transition duration-200 hover:bg-white active:scale-[0.98]"
          >
            加载更多
            <span className="tabular-nums text-[#9a9184]">
              （还有 {filtered.length - visibleCount} 个）
            </span>
          </button>
        </div>
      )}
    </div>
  );
}

function formatElapsed(sec: number) {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

// 获取岗位的动作磁贴：大图标 + 标题 + 一句说明，鼠标悬浮显示完整功能解释（核心功能，放大更醒目）
function ActionTile({
  icon: Icon,
  label,
  hint,
  tooltip,
  accent,
  onClick,
  disabled,
  busy,
  hero,
}: {
  icon: typeof Database;
  label: string;
  hint: string;
  tooltip: string;
  accent: string;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
  hero?: boolean;
}) {
  return (
    <div className="group relative">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={`${label}：${tooltip}`}
        className={cn(
          "flex w-full flex-col items-start gap-3 rounded-2xl border p-5 text-left transition duration-200 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-45",
          hero
            ? "border-[#cfc0e6] bg-[#efe9f8] hover:border-[#bba9dd] hover:bg-[#e7def4]"
            : "border-black/[0.07] bg-white/60 hover:border-black/[0.12] hover:bg-white",
        )}
      >
        <span className={cn("grid size-12 shrink-0 place-items-center rounded-2xl", accent)}>
          {busy ? (
            <CircleNotch size={24} weight="bold" className="animate-spin" aria-hidden="true" />
          ) : (
            <Icon size={24} weight="fill" aria-hidden="true" />
          )}
        </span>
        <span className="min-w-0">
          <span className="block text-base font-semibold text-[#1a1714]">{label}</span>
          <span className="mt-1 block text-[13px] leading-5 text-[#8a8275]">{hint}</span>
        </span>
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute left-1/2 top-full z-30 mt-2 w-64 max-w-[80vw] -translate-x-1/2 rounded-xl border border-white/10 bg-[#1a1714] px-3.5 py-2.5 text-xs leading-5 text-[#f0e9dc] opacity-0 shadow-[0_10px_30px_-8px_rgba(40,34,28,0.5)] transition-opacity duration-200 group-hover:opacity-100"
      >
        {tooltip}
      </span>
    </div>
  );
}

function BrowserDiscoveryProgress({ discovery }: { discovery: BrowserDiscoveryState }) {
  const isRefresh = discovery.kind === "refresh";
  const prog = discovery.progress;
  const hasProg = !!prog && prog.total > 0;
  const pct = hasProg
    ? Math.max(4, Math.min(100, Math.round((prog!.done / prog!.total) * 100)))
    : discovery.phase === "queued"
      ? 8
      : 30;
  const stages = isRefresh
    ? ["排队 · 触发后台抓取", "逐家公司刷新 · 新岗位实时入库"]
    : ["触发后台浏览器抓取", "加载官网 · 拦截官方接口 · 质量门入库"];
  const activeIndex = discovery.phase === "queued" ? 0 : 1;

  return (
    <div className="surface p-4 text-[#1a1714]">
      <div className="flex items-center gap-2.5">
        <CircleNotch size={18} weight="bold" className="animate-spin text-[#3f7cc0]" aria-hidden="true" />
        <span className="text-sm font-semibold">{isRefresh ? "正在刷新你的公司库…" : "正在发现官方招聘源…"}</span>
        <span className="ml-auto text-xs tabular-nums text-[#8a8275]">
          {hasProg ? `已刷 ${prog!.done}/${prog!.total} 家 · ` : ""}已用时 {formatElapsed(discovery.elapsedSec)}
        </span>
      </div>
      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-black/[0.08]">
        <div
          className="h-full rounded-full bg-[#3f7cc0] transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
      <ol className="mt-3 space-y-1.5">
        {stages.map((label, i) => {
          const state = i < activeIndex ? "done" : i === activeIndex ? "active" : "pending";
          return (
            <li key={label} className="flex items-center gap-2 text-sm">
              {state === "done" ? (
                <CheckCircle size={16} weight="fill" className="shrink-0 text-[#3f7cc0]" aria-hidden="true" />
              ) : state === "active" ? (
                <CircleNotch size={16} weight="bold" className="shrink-0 animate-spin text-[#3f7cc0]" aria-hidden="true" />
              ) : (
                <Circle size={16} className="shrink-0 text-[#c4bdb0]" aria-hidden="true" />
              )}
              <span
                className={
                  state === "pending"
                    ? "text-[#9a9184]"
                    : state === "active"
                      ? "text-[#1a1714]"
                      : "text-[#5f594e]"
                }
              >
                {`${i + 1}. ${label}`}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-pretty text-xs leading-5 text-[#8a8275]">
        可离开本页，{isRefresh ? "刷新" : "发现"}完成后结果会自动进岗位库；回到本页或刷新即可看到新增岗位。
      </p>
    </div>
  );
}

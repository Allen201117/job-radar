"use client";

import { useState, useEffect, useRef, Fragment } from "react";
import { useRouter } from "next/navigation";
import JobCard from "@/components/JobCard";
import JobFilters from "@/components/JobFilters";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import type { ScoredJob } from "@/lib/types";
import { useJobFilters } from "@/hooks/useJobFilters";
import {
  useDiscoveryPoll,
  type BrowserDiscoveryState,
  type RetrievalResult,
} from "@/hooks/useDiscoveryPoll";
import {
  ArrowsClockwise,
  ArrowUpRight,
  CheckCircle,
  Circle,
  CircleNotch,
  Compass,
  Database,
  MagnifyingGlass,
  Sparkle,
  X,
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
  // 本次搜索/发现完成后默认只看新岗位；用户可切回「查看全部」
  const [onlyNew, setOnlyNew] = useState(false);
  const [searchInfo, setSearchInfo] = useState("");
  // 公司下拉项：服务端筛选后不能再从「已加载岗位」派生（会只剩几家），改从专用接口取全量 ~500+ 家。
  const [companies, setCompanies] = useState<string[]>([]);
  // 「查已有岗位」点击加载态：即使秒出也显式可见（最短展示一段时间），与另两个检索一致。
  const [existingBusy, setExistingBusy] = useState(false);
  const existingBusyUntil = useRef(0);
  // 三个检索的「显式完成提示」：完成后弹一条带本轮结果概要的横幅（可手动关闭）。
  const [result, setResult] = useState<RetrievalResult | null>(null);
  // 标记本次 loading 结束源于用户点「查已有岗位」（而非筛选防抖自动搜），只为它弹完成提示。
  const pendingLocalResult = useRef(false);
  // 当前激活的检索方式：用于三个搜索入口的绿色「选中态」。
  const [activeSearch, setActiveSearch] = useState<"local" | "known" | "discover" | null>(null);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/jobs/companies");
        const data = await resp.json();
        if (!cancelled && data?.ok && Array.isArray(data.companies)) {
          setCompanies(data.companies);
        }
      } catch {
        // 取不到就保持空 datalist——公司框仍可自由输入子串
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 筛选 + 分页改由服务端 /api/jobs/search 跑（库已 10万+，前端不再全量加载）；匹配逻辑复用 lib/job-filter。
  const {
    filters,
    setFilters,
    sessionNewKeys,
    newViewActive,
    displayJobs,
    total,
    exactCount,
    capped,
    loading,
    loadingMore,
    error,
    hasMore,
    loadMore,
    refresh,
    newMatching,
  } = useJobFilters({ officialJobs, onlyNew, initialFilters, initialJobs, initialTotal });

  // 「更新关注公司 / 扩大官方搜索范围」状态机 + 轮询 + 持久化 + 超时（整体在 hook 内）。
  const { discovery, refreshing, discoveryActive, startDiscovery, startRefresh } =
    useDiscoveryPoll({ filters, setOfficialJobs, setSearchInfo, setResult });

  // 收起「查已有岗位」加载态：底层搜索结束且最短可见时间已到才停 spinner。
  useEffect(() => {
    if (!existingBusy || loading) return;
    const remain = Math.max(0, existingBusyUntil.current - Date.now());
    const t = setTimeout(() => setExistingBusy(false), remain);
    return () => clearTimeout(t);
  }, [existingBusy, loading]);

  // 「查已有岗位」完成提示：仅当本次 loading 结束源于用户点击（pendingLocalResult）时弹，
  // 不打扰筛选防抖触发的后台自动搜。读结束时的 total/exactCount 概要本轮结果。
  useEffect(() => {
    if (!pendingLocalResult.current || loading) return;
    pendingLocalResult.current = false;
    const related = Math.max(0, total - exactCount);
    setResult(
      total > 0
        ? {
            kind: "local",
            tone: "success",
            title: "查已有岗位 · 完成",
            detail: `在已收录岗位里匹配到 ${total} 个${
              filters.keyword ? `（精确 ${exactCount} · 相关 ${related}）` : ""
            }，已展示 ${displayJobs.length} 个。`,
          }
        : {
            kind: "local",
            tone: "empty",
            title: "查已有岗位 · 完成",
            detail:
              "当前筛选没有命中已收录岗位；可放宽条件，或用下方「发掘新公司」联网去官网找。",
          },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  // P3 on-demand 富化：给用户当下看到的薄卡（无 summary）即时补 JD 正文。
  // 只发 jd_url，服务端只补简单 httpx 源（workday/hotjob）；其余/浏览器源留给后台 drain。
  // overlay 覆盖式打补丁（不改各 job 列表），requested ref 防重复请求/死循环。
  const [summaryOverlay, setSummaryOverlay] = useState<Record<string, string>>({});
  const enrichRequested = useRef<Set<string>>(new Set());
  useEffect(() => {
    const need = displayJobs
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
  }, [displayJobs]);

  // 展示时校验（②层）：给当下看到的岗位异步探活，死的当场从看板隐藏（不等用户点）。
  // 只探可探的源(wt/hotjob/workday)，服务端跳过 24h 内刚探过的；requested ref 防重复请求。
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
        // 静默：探不动就不动，点击门 + 后台扫兜底
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayJobs]);

  // 一键放宽城市 + 岗位类型（保留关键词），让本次发现的岗位可见。
  function relaxLocationAndType() {
    setFilters((f) => ({ ...f, city: "", jobType: "" }));
    setOnlyNew(true);
  }

  function handleExistingJobsSearch() {
    track("search", { keyword: filters.keyword || "" });
    setOfficialJobs([]);
    setOnlyNew(false);
    setSearchInfo("");
    setResult(null); // 清掉上一轮完成提示
    pendingLocalResult.current = true; // 本次搜索结束后弹「查已有岗位 · 完成」
    existingBusyUntil.current = Date.now() + 600; // 最短可见 600ms：秒出也有显式加载态
    setExistingBusy(true);
    refresh();
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
      <div className="surface p-4 text-[#1a1714] dark:text-[#f3ecdf] sm:p-5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold text-[#3f3a33] dark:text-[#d9d0c2]">
          <MagnifyingGlass size={16} weight="bold" aria-hidden="true" />
          找岗位
        </div>
        <p className="mt-1.5 text-xs leading-5 text-[#9a9184] dark:text-[#837c70]">
          已用你保存的求职偏好作为默认搜索范围；改上方筛选条件即可调整。
        </p>
        {/* 三个搜索入口平行排列；当前激活的那个亮绿色「选中态」。
            查已有=秒出不联网（默认）；另两个=联网约 1–5 分钟。 */}
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <ActionTile
            icon={Database}
            label={existingBusy ? "查找中…" : "查已有岗位"}
            hint="已收录岗位里即时检索 · 不联网 · 秒出"
            tooltip="在已经收录入库的岗位里，按上方筛选条件即时检索，不发起任何联网请求，瞬时返回。"
            accent="bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
            onClick={() => {
              setActiveSearch("local");
              handleExistingJobsSearch();
            }}
            busy={existingBusy}
            selected={activeSearch === "local"}
          />
          <ActionTile
            icon={ArrowsClockwise}
            label={refreshing ? "刷新中…" : "刷新对口公司"}
            hint="去和你对口的公司官网重抓新岗位 · 约 1–5 分钟"
            tooltip="后台重新抓取「和你偏好/筛选对口的公司」官方招聘页（含需要浏览器的源），有新岗位会自动进列表。没填筛选时按你保存的求职偏好来。约 1–5 分钟。"
            accent="bg-[#dbe9fa] text-[#2f6299] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]"
            onClick={() => {
              setActiveSearch("known");
              startRefresh();
            }}
            disabled={refreshing || discoveryActive}
            busy={refreshing}
            selected={activeSearch === "known"}
          />
          <ActionTile
            icon={Compass}
            label={discoveryActive ? "发掘中…" : "发掘新公司"}
            hint="去库里还没有的公司官网找岗位（需关键词）· 约 1–5 分钟"
            tooltip="用浏览器去抓「库里还没收录的新公司」官方招聘站，并补全职位描述。需要先在上方填「关键词」。约 1–5 分钟。"
            accent="bg-[#e7def4] text-[#6a4fa0] dark:bg-[#b9a3e0]/[0.15] dark:text-[#b9a3e0]"
            onClick={() => {
              setActiveSearch("discover");
              startDiscovery();
            }}
            disabled={refreshing || discoveryActive || !filters.keyword}
            busy={discoveryActive}
            selected={activeSearch === "discover"}
          />
        </div>
        {!filters.keyword && (
          <p className="mt-2 px-1 text-xs leading-5 text-[#9a9184] dark:text-[#837c70]">
            「发掘新公司」需先在上方填「关键词」。
          </p>
        )}
        {searchInfo && (
          <p className="mt-3 rounded-2xl border border-black/[0.06] dark:border-white/[0.1] bg-[#f6f3ec] dark:bg-[#1c1813] px-3.5 py-2.5 text-pretty text-sm leading-6 text-[#5f594e] dark:text-[#b6ad9d]">
            {searchInfo}
          </p>
        )}
      </div>
      {result && (
        <RetrievalDoneBanner result={result} onDismiss={() => setResult(null)} />
      )}
      {discoveryActive && <BrowserDiscoveryProgress discovery={discovery} />}

      {officialJobs.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-[#cfe6b0] dark:border-[#a3d06a]/[0.30] bg-[#eef6e0] dark:bg-[#a3d06a]/[0.15] px-3.5 py-2.5 text-sm">
          <Sparkle size={16} weight="fill" className="text-[#6f9a3a] dark:text-[#a3d06a]" aria-hidden="true" />
          <span className="font-medium text-[#4f6f2a] dark:text-[#a3d06a]">
            本次带回 {officialJobs.length} 个岗位
            {(filters.city || filters.jobType || filters.keyword) &&
            newMatching.length !== officialJobs.length
              ? `，其中 ${newMatching.length} 个合你当前筛选`
              : "（绿色标记）"}
          </span>
          <div className="ml-auto flex gap-1.5">
            <button
              type="button"
              onClick={() => setOnlyNew(true)}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium transition",
                newViewActive
                  ? "bg-[#cde8a0] text-[#3f5a1c] dark:bg-[#a3d06a]/[0.25] dark:text-[#a3d06a]"
                  : "text-[#8a8275] dark:text-[#9a9184] hover:bg-black/[0.05] dark:hover:bg-white/[0.05] hover:text-[#1a1714] dark:hover:text-[#f3ecdf]",
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
                  ? "bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                  : "text-[#8a8275] dark:text-[#9a9184] hover:bg-black/[0.05] dark:hover:bg-white/[0.05] hover:text-[#1a1714] dark:hover:text-[#f3ecdf]",
              )}
            >
              查看全部
            </button>
          </div>
        </div>
      )}

      {/* 信息行：移动端长句会折成多行 → 用 flex items-start + rounded-2xl（而非 inline-flex rounded-full，
          否则多行文字会被撑成丑陋的胶囊形），图标顶对齐随首行。 */}
      <p className="flex items-start gap-2 rounded-2xl border border-black/[0.06] dark:border-white/[0.1] bg-white/55 dark:bg-white/[0.05] px-3.5 py-2.5 text-sm leading-6 text-[#5f594e] dark:text-[#b6ad9d]">
        <MagnifyingGlass size={16} weight="bold" className="mt-0.5 shrink-0" aria-hidden="true" />
        <span>
          {loading ? (
            "正在搜索岗位库…"
          ) : (
            <>
              {newViewActive ? "只看本次带回：" : "库里匹配你筛选的 "}
              {newViewActive ? newMatching.length : total} 个岗位
              {!newViewActive && filters.keyword
                ? `（精确 ${exactCount} + 相关 ${Math.max(0, total - exactCount)}）`
                : ""}
              {!newViewActive && capped ? "，可加载更多" : ""}
              ，已展示 {displayJobs.length} 个。
            </>
          )}
        </span>
      </p>
      {error && (
        <p className="rounded-2xl border border-[#e7b4a0] dark:border-[#7a392e]/[0.60] bg-[#fbe9e2] dark:bg-[#3a201a] px-3.5 py-2.5 text-sm text-[#9a4a32] dark:text-[#e6a99f]">
          {error}
        </p>
      )}
      <div className="space-y-3">
        {displayJobs.filter((job) => !deadIds.has(job.id)).map((job, i, arr) => {
          const tier = (job as any).__tier as "exact" | "related";
          const prevTier = i > 0 ? ((arr[i - 1] as any).__tier as string) : null;
          const showDivider =
            Boolean(filters.keyword) && tier === "related" && prevTier !== "related";
          return (
            <Fragment key={job.id}>
              {showDivider && (
                <div className="flex items-center gap-3 pt-4 pb-1" role="separator">
                  <span className="h-px flex-1 bg-black/[0.08] dark:bg-white/[0.1]" />
                  <span className="whitespace-nowrap text-xs font-medium text-[#8a8275] dark:text-[#9a9184]">
                    相关岗位 · 同职能（标题未直接含「{filters.keyword}」）
                  </span>
                  <span className="h-px flex-1 bg-black/[0.08] dark:bg-white/[0.1]" />
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
        {loading && displayJobs.length === 0 && (
          <div className="rounded-[1.5rem] border border-dashed border-black/[0.12] dark:border-white/[0.1] bg-white/45 dark:bg-white/[0.05] px-6 py-14 text-center">
            <CircleNotch size={22} weight="bold" className="mx-auto animate-spin text-[#8a8275] dark:text-[#9a9184]" aria-hidden="true" />
            <p className="mt-3 text-sm text-[#6b655a] dark:text-[#b6ad9d]">正在搜索岗位库…</p>
          </div>
        )}
        {!loading && displayJobs.length === 0 &&
          (officialJobs.length > 0 && (filters.city || filters.jobType) ? (
            <div className="rounded-[1.5rem] border border-dashed border-[#e7c98a] dark:border-[#e0b15a]/[0.30] bg-[#fbf2d8] dark:bg-[#e0b15a]/[0.15] px-6 py-10 text-center">
              <h2 className="text-lg font-semibold text-[#1a1714] dark:text-[#f3ecdf]">
                本次发现 {officialJobs.length} 个岗位，但 0 个符合当前筛选
              </h2>
              <p className="mx-auto mt-2 max-w-md text-pretty text-sm leading-6 text-[#6b655a] dark:text-[#b6ad9d]">
                发现的岗位未同时满足
                {filters.city ? ` 城市『${filters.city}』` : ""}
                {filters.jobType ? ` 类型『${filters.jobType}』` : ""}
                ——它们可能属于其它城市，或为社招 / 校招。放宽这两项即可查看本次发现的全部岗位。
              </p>
              <button
                type="button"
                onClick={relaxLocationAndType}
                className="mt-4 inline-flex items-center gap-2 rounded-full bg-[#1a1714] dark:bg-[#f3ecdf] px-5 py-2 text-sm font-semibold text-[#f7f1e6] dark:text-[#16130f] transition duration-200 hover:bg-[#2b2520] dark:hover:bg-[#e8ddca] active:scale-[0.98]"
              >
                放宽城市 / 类型，查看全部 {officialJobs.length} 个发现
              </button>
            </div>
          ) : (
            <div className="rounded-[1.5rem] border border-dashed border-black/[0.12] dark:border-white/[0.1] bg-white/45 dark:bg-white/[0.05] px-6 py-14 text-center">
              <h2 className="text-lg font-semibold text-[#1a1714] dark:text-[#f3ecdf]">没有匹配的岗位</h2>
              <p className="mx-auto mt-2 max-w-md text-pretty text-sm leading-6 text-[#6b655a] dark:text-[#b6ad9d]">
                可以放宽筛选条件，或填关键词后用「刷新对口公司 / 发掘新公司」联网去找。
              </p>
            </div>
          ))}
      </div>
      {hasMore && (
        <div className="flex justify-center pt-1">
          <button
            type="button"
            onClick={loadMore}
            disabled={loadingMore}
            className="inline-flex items-center gap-2 rounded-full border border-black/[0.08] dark:border-white/[0.1] bg-white/70 dark:bg-white/[0.05] px-5 py-2.5 text-sm font-medium text-[#3f3a33] dark:text-[#d9d0c2] transition duration-200 hover:bg-white dark:hover:bg-[#1e1a15] active:scale-[0.98] disabled:opacity-50"
          >
            {loadingMore ? (
              <>
                <CircleNotch size={16} weight="bold" className="animate-spin" aria-hidden="true" />
                加载中…
              </>
            ) : (
              <>
                加载更多
                <span className="tabular-nums text-[#9a9184] dark:text-[#837c70]">（还有 {total - displayJobs.length} 个）</span>
              </>
            )}
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
  selected,
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
  selected?: boolean;
}) {
  return (
    <div className="group relative">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={`${label}：${tooltip}`}
        className={cn(
          "bento-glow group/tile relative flex w-full flex-col items-start gap-3 rounded-2xl border p-5 text-left transition-all duration-300 ease-out hover:-translate-y-1 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:translate-y-0 disabled:hover:shadow-none",
          selected && "bento-selected",
          hero
            ? "border-[#cfc0e6] dark:border-[#b9a3e0]/[0.30] bg-[#efe9f8] dark:bg-[#b9a3e0]/[0.10] hover:border-[#bba9dd] dark:hover:border-[#b9a3e0]/[0.45] hover:bg-[#e7def4] dark:hover:bg-[#b9a3e0]/[0.20] hover:shadow-[0_18px_40px_-22px_rgba(106,79,160,0.5)]"
            : "border-black/[0.07] dark:border-white/[0.1] bg-white/60 dark:bg-white/[0.05] hover:border-black/[0.12] dark:hover:border-white/20 hover:bg-white dark:hover:bg-[#1e1a15] hover:shadow-[0_18px_40px_-24px_rgba(40,34,28,0.45)]",
        )}
      >
        <span
          className={cn(
            "grid size-12 shrink-0 place-items-center rounded-2xl transition-transform duration-300 ease-out group-hover/tile:scale-[1.08] group-hover/tile:-rotate-3",
            accent,
          )}
        >
          {busy ? (
            <CircleNotch size={24} weight="bold" className="animate-spin" aria-hidden="true" />
          ) : (
            <Icon size={24} weight="fill" aria-hidden="true" />
          )}
        </span>
        <span className="min-w-0">
          <span className="block text-base font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{label}</span>
          <span className="mt-1 block text-[13px] leading-5 text-[#8a8275] dark:text-[#9a9184]">{hint}</span>
        </span>
        {/* 悬浮时右上角箭头滑入，提示「可点击的动作」（动态特效，与全站卡片悬浮一致）。 */}
        <ArrowUpRight
          size={18}
          weight="bold"
          aria-hidden="true"
          className="pointer-events-none absolute right-4 top-4 -translate-x-1 translate-y-1 text-[#8a8275] opacity-0 transition-all duration-300 ease-out group-hover/tile:translate-x-0 group-hover/tile:translate-y-0 group-hover/tile:opacity-100 dark:text-[#9a9184]"
        />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute left-1/2 top-full z-30 mt-2 w-64 max-w-[80vw] -translate-x-1/2 rounded-xl border border-white/10 bg-[#1a1714] dark:bg-[#211b14] px-3.5 py-2.5 text-xs leading-5 text-[#f0e9dc] opacity-0 shadow-[0_10px_30px_-8px_rgba(40,34,28,0.5)] transition-opacity duration-200 group-hover:opacity-100"
      >
        {tooltip}
      </span>
    </div>
  );
}

// 三个检索完成后的显式提示横幅：成功=暖绿，空结果=中性纸色；与全站 warm-editorial 风格一致。
function RetrievalDoneBanner({
  result,
  onDismiss,
}: {
  result: RetrievalResult;
  onDismiss: () => void;
}) {
  const success = result.tone === "success";
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex items-start gap-3 rounded-2xl border px-4 py-3.5",
        success ? "border-[#cfe6b0] dark:border-[#a3d06a]/[0.30] bg-[#eef6e0] dark:bg-[#a3d06a]/[0.15]" : "border-black/[0.07] dark:border-white/[0.1] bg-[#f6f3ec] dark:bg-[#1c1813]",
      )}
    >
      <span
        className={cn(
          "mt-0.5 grid size-7 shrink-0 place-items-center rounded-full",
          success ? "bg-[#dcecbf] dark:bg-[#a3d06a]/[0.20] text-[#5b7d2c] dark:text-[#a3d06a]" : "bg-black/[0.06] dark:bg-white/[0.05] text-[#8a8275] dark:text-[#9a9184]",
        )}
      >
        {success ? (
          <CheckCircle size={18} weight="fill" aria-hidden="true" />
        ) : (
          <MagnifyingGlass size={16} weight="bold" aria-hidden="true" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p
          className={cn(
            "text-sm font-semibold",
            success ? "text-[#3f5a1c] dark:text-[#a3d06a]" : "text-[#3f3a33] dark:text-[#d9d0c2]",
          )}
        >
          {result.title}
        </p>
        <p
          className={cn(
            "mt-0.5 text-pretty text-sm leading-6",
            success ? "text-[#557029] dark:text-[#a3d06a]" : "text-[#6b655a] dark:text-[#b6ad9d]",
          )}
        >
          {result.detail}
        </p>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="关闭完成提示"
        className="-mr-1 -mt-1 shrink-0 rounded-full p-1.5 text-[#8a8275] dark:text-[#9a9184] transition hover:bg-black/[0.06] dark:hover:bg-white/[0.05] hover:text-[#1a1714] dark:hover:text-[#f3ecdf]"
      >
        <X size={15} weight="bold" aria-hidden="true" />
      </button>
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
    ? ["排队中", "逐家公司更新 · 新岗位实时出现"]
    : ["排队中", "在官网逐站搜索 · 补全职位描述"];
  const activeIndex = discovery.phase === "queued" ? 0 : 1;

  return (
    <div className="surface p-4 text-[#1a1714] dark:text-[#f3ecdf]">
      <div className="flex items-center gap-2.5">
        <CircleNotch size={18} weight="bold" className="animate-spin text-[#3f7cc0] dark:text-[#7fb2e8]" aria-hidden="true" />
        <span className="text-sm font-semibold">{isRefresh ? "正在刷新对口公司…" : "正在发掘新公司…"}</span>
        <span className="ml-auto text-xs tabular-nums text-[#8a8275] dark:text-[#9a9184]">
          {hasProg ? `已更新 ${prog!.done}/${prog!.total} 家 · ` : ""}已用时 {formatElapsed(discovery.elapsedSec)}
        </span>
      </div>
      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-black/[0.08] dark:bg-white/[0.1]">
        <div
          className="h-full rounded-full bg-[#3f7cc0] dark:bg-[#7fb2e8] transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
      <ol className="mt-3 space-y-1.5">
        {stages.map((label, i) => {
          const state = i < activeIndex ? "done" : i === activeIndex ? "active" : "pending";
          return (
            <li key={label} className="flex items-center gap-2 text-sm">
              {state === "done" ? (
                <CheckCircle size={16} weight="fill" className="shrink-0 text-[#3f7cc0] dark:text-[#7fb2e8]" aria-hidden="true" />
              ) : state === "active" ? (
                <CircleNotch size={16} weight="bold" className="shrink-0 animate-spin text-[#3f7cc0] dark:text-[#7fb2e8]" aria-hidden="true" />
              ) : (
                <Circle size={16} className="shrink-0 text-[#c4bdb0] dark:text-[#6f685e]" aria-hidden="true" />
              )}
              <span
                className={
                  state === "pending"
                    ? "text-[#9a9184] dark:text-[#837c70]"
                    : state === "active"
                      ? "text-[#1a1714] dark:text-[#f3ecdf]"
                      : "text-[#5f594e] dark:text-[#b6ad9d]"
                }
              >
                {`${i + 1}. ${label}`}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-pretty text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
        可离开本页，{isRefresh ? "刷新" : "发现"}完成后结果会自动进岗位库；回到本页或刷新即可看到新增岗位。
      </p>
    </div>
  );
}

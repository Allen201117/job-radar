"use client";

import { useState, useEffect, useRef, Fragment } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import JobCard from "@/components/JobCard";
import JobFilters from "@/components/JobFilters";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import { MANUAL_CRAWL_UI_ENABLED } from "@/lib/product-flags";
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
  initialTotal: number;
  initialFilters?: { city?: string; jobType?: string; keyword?: string };
  jobScope?: string | null;
}

export default function JobsClient({ initialJobs, initialTotal, initialFilters, jobScope = "domestic" }: Props) {
  // officialJobs = 高级工具「刷新/发掘」带回的新岗位（默认 UI 隐藏时恒为空）；仍参与 useJobFilters 合并。
  const [officialJobs, setOfficialJobs] = useState<ScoredJob[]>([]);
  const [onlyNew, setOnlyNew] = useState(false);
  const [companies, setCompanies] = useState<string[]>([]);
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

  // 筛选 + 分页由服务端 /api/jobs/search 跑；匹配逻辑复用 lib/job-filter。
  const {
    filters,
    setFilters,
    sessionNewKeys,
    newViewActive,
    displayJobs,
    total,
    exactCount,
    relatedSameFunction,
    relatedMissingInfo,
    capped,
    loading,
    loadingMore,
    error,
    hasMore,
    loadMore,
    refresh,
    newMatching,
  } = useJobFilters({ officialJobs, onlyNew, initialFilters, initialJobs, initialTotal });

  useEffect(() => {
    if (jobScope !== "domestic") return;
    setFilters((f) => (f.region ? { ...f, region: "" } : f));
  }, [jobScope, setFilters]);

  // P3 on-demand 富化：给当下看到的薄卡即时补 JD 正文。
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

  // 展示时校验（②层）：给当下看到的岗位异步探活，死的当场隐藏。
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
        // 静默：探不动就不动，后台扫兜底
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayJobs]);

  // 一键放宽城市 + 岗位类型（保留关键词）
  function relaxLocationAndType() {
    setFilters((f) => ({ ...f, city: "", jobType: "" }));
    setOnlyNew(true);
  }

  function broadenFilters() {
    setFilters((f) => ({ ...f, city: "", jobType: "", keyword: "" }));
    setOnlyNew(false);
  }

  function handleActionChange(jobId: string, action: PrimaryAction | null) {
    setOfficialJobs((jobs) =>
      jobs.map((job) =>
        job.id === jobId
          ? {
              ...job,
              user_action: action,
              hidden_reason:
                action === "ignored" ? "ignored" : action === "applied" ? "applied_by_default" : null,
            }
          : job,
      ),
    );
    router.refresh();
  }

  const visibleJobs = displayJobs.filter((job) => !deadIds.has(job.id));
  const matchCountParts = filters.keyword
    ? [
        exactCount > 0 ? `精确 ${exactCount}` : "",
        relatedSameFunction > 0 ? `同职能相关 ${relatedSameFunction}` : "",
        relatedMissingInfo > 0 ? `信息不全 ${relatedMissingInfo}` : "",
      ].filter(Boolean)
    : [];
  const searchMetaParts = [
    ...matchCountParts,
    capped ? "还有更多，可继续加载" : "",
  ].filter(Boolean);

  return (
    <div className="space-y-5">
      <JobFilters filters={filters} onChange={setFilters} companies={companies} jobScope={jobScope} />

      {/* 搜索说明 + 手动搜索按钮（取代旧三磁贴；筛选变化已自动搜，这里手动重试）。 */}
      <div className="flex flex-col gap-3 surface p-4 text-[#1a1714] dark:text-[#f3ecdf] sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <p className="text-xs leading-5 text-[#9a9184] dark:text-[#837c70]">
          已用你保存的求职偏好作为默认搜索范围；改上方筛选条件即可调整。
        </p>
        <button
          type="button"
          onClick={() => {
            track("search", { keyword: filters.keyword || "" });
            refresh();
          }}
          disabled={loading}
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded-full border border-black/[0.1] bg-white/70 px-4 py-2 text-sm font-medium text-[#3f3a33] transition duration-200 hover:bg-white active:scale-[0.98] disabled:opacity-50 dark:border-white/[0.12] dark:bg-white/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.08]"
        >
          {loading ? (
            <CircleNotch size={16} weight="bold" className="animate-spin" aria-hidden="true" />
          ) : (
            <ArrowsClockwise size={16} weight="bold" aria-hidden="true" />
          )}
          重新搜索
        </button>
      </div>

      {/* 故障回滚专用：高级手动抓取工具（默认隐藏，NEXT_PUBLIC_MANUAL_CRAWL_UI=true 才渲染）。 */}
      {MANUAL_CRAWL_UI_ENABLED && (
        <AdvancedCrawlTools filters={filters} setOfficialJobs={setOfficialJobs} />
      )}

      {/* 高级工具带回的新增岗位提示（默认 UI 下 officialJobs 恒空，不渲染）。 */}
      {officialJobs.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-[#cfe6b0] dark:border-[#a3d06a]/[0.30] bg-[#eef6e0] dark:bg-[#a3d06a]/[0.15] px-3.5 py-2.5 text-sm">
          <Sparkle size={16} weight="fill" className="text-[#6f9a3a] dark:text-[#a3d06a]" aria-hidden="true" />
          <span className="font-medium text-[#4f6f2a] dark:text-[#a3d06a]">
            本次新增 {officialJobs.length} 个新岗位
            {(filters.city || filters.jobType || filters.keyword) && newMatching.length !== officialJobs.length
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

      <div className="rounded-2xl border border-black/[0.06] bg-white/55 px-3.5 py-2.5 text-sm leading-6 text-[#5f594e] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d]">
        <div className="flex items-start gap-2">
        {loading ? (
          <CircleNotch size={16} weight="bold" className="mt-0.5 shrink-0 animate-spin text-[#00b84c] dark:text-[#00e676]" aria-hidden="true" />
        ) : (
          <MagnifyingGlass size={16} weight="bold" className="mt-0.5 shrink-0" aria-hidden="true" />
        )}
        <div className="min-w-0">
          {loading ? (
            <p className="font-medium text-[#3f3a33] dark:text-[#d9d0c2]">正在搜索岗位库…</p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-medium text-[#3f3a33] dark:text-[#d9d0c2]">
                  {newViewActive
                    ? `${newMatching.length} 个本次新增 · 已展示 ${visibleJobs.length}`
                    : `${total} 个匹配岗位 · 已展示 ${visibleJobs.length}`}
                </p>
                {deadIds.size > 0 && (
                  <span className="rounded-full border border-black/[0.08] bg-white/55 px-2 py-0.5 text-xs text-[#8a8275] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#9a9184]">
                    实时复核拦下 {deadIds.size} 个
                  </span>
                )}
              </div>
              {!newViewActive && searchMetaParts.length > 0 && (
                <p className="mt-0.5 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
                  {searchMetaParts.join(" · ")}
                </p>
              )}
            </>
          )}
        </div>
        </div>
        {loading && <div className="jr-scan mt-2.5 h-1 w-full rounded-full" aria-hidden="true" />}
      </div>
      {error && (
        <p className="rounded-2xl border border-[#e7b4a0] dark:border-[#7a392e]/[0.60] bg-[#fbe9e2] dark:bg-[#3a201a] px-3.5 py-2.5 text-sm text-[#9a4a32] dark:text-[#e6a99f]">
          {error}
        </p>
      )}
      <div
        className={cn(
          "space-y-3 transition-opacity duration-200 ease-out",
          loading && visibleJobs.length > 0 && "pointer-events-none opacity-50",
        )}
      >
        {visibleJobs.map((job, i, arr) => {
          const tier = (job as any).__tier as "exact" | "related";
          const prevTier = i > 0 ? ((arr[i - 1] as any).__tier as string) : null;
          const showDivider = Boolean(filters.keyword) && tier === "related" && prevTier !== "related";
          return (
            <Fragment key={job.id}>
              {showDivider && (
                <div className="flex items-center gap-3 pt-4 pb-1" role="separator">
                  <span className="h-px flex-1 bg-black/[0.08] dark:bg-white/[0.1]" />
                  <span className="min-w-0 text-center text-xs font-medium text-[#8a8275] dark:text-[#9a9184]">
                    相关岗位 · 同职能相关或信息不全（见每条标注）
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
                matchReason={(job as any).__match}
                onActionChange={handleActionChange}
              />
            </Fragment>
          );
        })}
        {loading && displayJobs.length === 0 && (
          <div className="rounded-[1.5rem] border border-dashed border-black/[0.12] dark:border-white/[0.1] bg-white/45 dark:bg-white/[0.05] px-6 py-14 text-center">
            <CircleNotch size={22} weight="bold" className="mx-auto animate-spin text-[#00b84c] dark:text-[#00e676]" aria-hidden="true" />
            <p className="mt-3 text-sm text-[#6b655a] dark:text-[#b6ad9d]">正在搜索岗位库…</p>
            <div className="jr-scan mx-auto mt-4 h-1 w-40 rounded-full" aria-hidden="true" />
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
                可以放宽筛选条件，或把目标公司加入关注，让系统持续替你监控它的官方招聘页。
              </p>
              <div className="mt-5 flex flex-col items-center justify-center gap-3 sm:flex-row">
                <button
                  type="button"
                  onClick={broadenFilters}
                  className="rounded-full border border-black/[0.1] bg-white/70 px-4 py-2 text-sm font-medium text-[#3f3a33] transition hover:bg-white dark:border-white/[0.12] dark:bg-white/[0.05] dark:text-[#d9d0c2]"
                >
                  放宽筛选条件
                </button>
                <Link
                  href="/preferences"
                  className="rounded-full border border-black/[0.1] bg-white/70 px-4 py-2 text-sm font-medium text-[#3f3a33] transition hover:bg-white dark:border-white/[0.12] dark:bg-white/[0.05] dark:text-[#d9d0c2]"
                >
                  添加关注公司
                </Link>
              </div>
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

// 高级手动抓取工具（§9.3 feature flag）：只在 NEXT_PUBLIC_MANUAL_CRAWL_UI=true 时渲染。
// useDiscoveryPoll 只在此组件内调用 —— 普通 JobsClient 不触发任何联网抓取。
function AdvancedCrawlTools({
  filters,
  setOfficialJobs,
}: {
  filters: ReturnType<typeof useJobFilters>["filters"];
  setOfficialJobs: React.Dispatch<React.SetStateAction<ScoredJob[]>>;
}) {
  const [searchInfo, setSearchInfo] = useState("");
  const [result, setResult] = useState<RetrievalResult | null>(null);
  const { discovery, refreshing, discoveryActive, refreshActive, discoverActive, startDiscovery, startRefresh } =
    useDiscoveryPoll({ filters, setOfficialJobs, setSearchInfo, setResult });

  return (
    <details className="surface p-4 text-[#1a1714] dark:text-[#f3ecdf] sm:p-5">
      <summary className="cursor-pointer text-sm font-semibold text-[#3f3a33] dark:text-[#d9d0c2]">
        高级工具 · 手动抓取（联网，约 1–5 分钟）
      </summary>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <ActionTile
          icon={ArrowsClockwise}
          label={refreshing || refreshActive ? "刷新中…" : "刷新对口公司"}
          hint="去和你对口的公司官网重抓新岗位"
          tooltip="后台重新抓取「和你偏好/筛选对口的公司」官方招聘页（含需要浏览器的源），有新岗位会自动进列表。"
          accent="bg-[#dbe9fa] text-[#2f6299] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]"
          onClick={() => startRefresh()}
          disabled={refreshing || discoveryActive}
          busy={refreshing || refreshActive}
        />
        <ActionTile
          icon={Compass}
          label={discoverActive ? "发掘中…" : "发掘新公司"}
          hint="去库里还没有的公司官网找岗位（需关键词）"
          tooltip="用浏览器去抓「库里还没收录的新公司」官方招聘站，并补全职位描述。需要先在上方填「关键词」。"
          accent="bg-[#e7def4] text-[#6a4fa0] dark:bg-[#b9a3e0]/[0.15] dark:text-[#b9a3e0]"
          onClick={() => startDiscovery()}
          disabled={refreshing || discoveryActive || !filters.keyword}
          busy={discoverActive}
        />
      </div>
      {searchInfo && (
        <p className="mt-3 rounded-2xl border border-black/[0.06] dark:border-white/[0.1] bg-[#f6f3ec] dark:bg-[#1c1813] px-3.5 py-2.5 text-pretty text-sm leading-6 text-[#5f594e] dark:text-[#b6ad9d]">
          {searchInfo}
        </p>
      )}
      {result && <RetrievalDoneBanner result={result} onDismiss={() => setResult(null)} />}
      {discoveryActive && (
        <div className="mt-3">
          <BrowserDiscoveryProgress discovery={discovery} />
        </div>
      )}
    </details>
  );
}

function formatElapsed(sec: number) {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function ActionTile({
  icon: Icon,
  label,
  hint,
  tooltip,
  accent,
  onClick,
  disabled,
  busy,
}: {
  icon: typeof Database;
  label: string;
  hint: string;
  tooltip: string;
  accent: string;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
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
          "border-black/[0.07] dark:border-white/[0.1] bg-white/60 dark:bg-white/[0.05] hover:border-black/[0.12] dark:hover:border-white/20 hover:bg-white dark:hover:bg-[#1e1a15] hover:shadow-[0_18px_40px_-24px_rgba(40,34,28,0.45)]",
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
        "mt-3 flex items-start gap-3 rounded-2xl border px-4 py-3.5",
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
        <p className={cn("text-sm font-semibold", success ? "text-[#3f5a1c] dark:text-[#a3d06a]" : "text-[#3f3a33] dark:text-[#d9d0c2]")}>
          {result.title}
        </p>
        <p className={cn("mt-0.5 text-pretty text-sm leading-6", success ? "text-[#557029] dark:text-[#a3d06a]" : "text-[#6b655a] dark:text-[#b6ad9d]")}>
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
        <div className="h-full rounded-full bg-[#3f7cc0] dark:bg-[#7fb2e8] transition-all duration-700" style={{ width: `${pct}%` }} />
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

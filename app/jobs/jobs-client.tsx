"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import JobCard from "@/components/JobCard";
import JobFilters from "@/components/JobFilters";
import { mapApiSearchJobsToScoredJobs } from "@/lib/client-job-mapping";
import {
  jobMatchesChinaKeyword,
  normalizeChinaCity,
  recruitmentCategory,
} from "@/lib/china-keyword-expansion";
import { classifyCompanyOrigin } from "@/lib/company-origin";
import { cn } from "@/lib/utils";
import type { ScoredJob } from "@/lib/types";
import {
  ArrowsClockwise,
  CheckCircle,
  Circle,
  CircleNotch,
  Compass,
  Database,
  Lightning,
  MagnifyingGlass,
  Sparkle,
} from "@phosphor-icons/react";

type PrimaryAction = "saved" | "ignored" | "applied";

type DiscoveryPhase = "idle" | "queued" | "running" | "done" | "failed";
type BrowserDiscoveryState = {
  phase: DiscoveryPhase;
  runId: string | null;
  startedAt: number | null;
  elapsedSec: number;
  note: string;
};

const DISCOVERY_POLL_MS = 6000;
const DISCOVERY_TIMEOUT_MS = 8 * 60 * 1000;
// 每次渲染/「加载更多」的批量大小（前端分批渲染，避免一次性渲染上千张卡片卡顿）
const JOBS_PAGE_SIZE = 60;
// 后台「浏览器发现」任务跨页面持久化的 localStorage 键（切到别的页面再回来不丢任务）
const DISCOVERY_STORAGE_KEY = "jobradar:browser-discovery";

function saveDiscoveryTask(runId: string, startedAt: number, query: string) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(
      DISCOVERY_STORAGE_KEY,
      JSON.stringify({ runId, startedAt, query }),
    );
  } catch {
    // localStorage 不可用（隐私模式等）时静默降级，不影响当前会话内轮询
  }
}

function clearDiscoveryTask() {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(DISCOVERY_STORAGE_KEY);
  } catch {
    // 同上
  }
}

type Filters = {
  company: string;
  city: string;
  jobType: string;
  keyword: string;
  showIgnored: boolean;
  showApplied: boolean;
  showNewOnly: boolean;
  sortBy: "match" | "newest";
  capitalOrigin: string;
  salaryOnly: boolean;
};

interface Props {
  initialJobs: ScoredJob[];
  // 活跃岗位总数（SSR 查得）；前端据此后台分块拉完剩余岗位（解除展示硬上限）。
  initialTotal: number;
  // 从用户已保存偏好预填的筛选初值（城市/类型/关键词）；用户手动改即覆盖。
  initialFilters?: { city?: string; jobType?: string; keyword?: string };
}

export default function JobsClient({ initialJobs, initialTotal, initialFilters }: Props) {
  const [filters, setFilters] = useState<Filters>({
    company: "",
    city: initialFilters?.city || "",
    jobType: initialFilters?.jobType || "",
    keyword: initialFilters?.keyword || "",
    showIgnored: false,
    showApplied: false,
    showNewOnly: false,
    sortBy: "match",
    capitalOrigin: "",
    salaryOnly: false,
  });
  const [officialJobs, setOfficialJobs] = useState<ScoredJob[]>([]);
  // 后台分块把岗位库剩余岗位拉完（解除展示硬上限）：SSR 只给第一页，这里补齐到 initialTotal。
  const [extraJobs, setExtraJobs] = useState<ScoredJob[]>([]);
  const [libLoading, setLibLoading] = useState(false);
  const fillRef = useRef(false);
  // 本次搜索/发现完成后默认只看新岗位；用户可切回「查看全部」
  const [onlyNew, setOnlyNew] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [searchInfo, setSearchInfo] = useState("");
  const [discoveryRound, setDiscoveryRound] = useState(0);
  const [discovery, setDiscovery] = useState<BrowserDiscoveryState>({
    phase: "idle",
    runId: null,
    startedAt: null,
    elapsedSec: 0,
    note: "",
  });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const router = useRouter();

  const discoveryActive = discovery.phase === "queued" || discovery.phase === "running";

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

  // 本次会话内由「刷新已知源 / 发现官方源」新拿到的岗位（用于高亮 + 「只看新发现」）
  const sessionNewKeys = useMemo(
    () => new Set(officialJobs.map((j) => j.jd_url || j.id)),
    [officialJobs],
  );

  // 合并本地岗位库 + 本次已知源刷新/官方源发现返回的岗位
  const allJobs = useMemo(() => {
    const seen = new Set(officialJobs.map((j) => j.jd_url || j.id));
    const cachedNotInLive = localJobs.filter((j) => !seen.has(j.jd_url || j.id));
    return [...officialJobs, ...cachedNotInLive];
  }, [localJobs, officialJobs]);

  // 「只看新发现」仅在确有本次新岗位时生效，避免误把列表清空
  const newViewActive = onlyNew && officialJobs.length > 0;

  const filtered = useMemo(() => {
    let arr = allJobs.filter((job) => jobMatchesFilters(job, filters));
    if (newViewActive) {
      arr = arr.filter((job) => sessionNewKeys.has(job.jd_url || job.id));
    }
    arr.sort((a, b) =>
      filters.sortBy === "newest"
        ? new Date(b.posted_at || b.first_seen_at || 0).getTime() -
          new Date(a.posted_at || a.first_seen_at || 0).getTime()
        : (b.match_score || 0) - (a.match_score || 0),
    );
    return arr;
  }, [allJobs, filters, newViewActive, sessionNewKeys]);

  // 分批渲染：默认只渲染前 JOBS_PAGE_SIZE 张，「加载更多」逐批增加；筛选 / 切换新发现视图时回到第一批。
  const [visibleCount, setVisibleCount] = useState(JOBS_PAGE_SIZE);
  useEffect(() => {
    setVisibleCount(JOBS_PAGE_SIZE);
  }, [filters, newViewActive]);
  const visibleJobs = useMemo(
    () => filtered.slice(0, visibleCount),
    [filtered, visibleCount],
  );

  const existingFilteredCount = useMemo(() => {
    return localJobs.filter((job) => jobMatchesFilters(job, filters)).length;
  }, [localJobs, filters]);

  // 本次发现的岗位中，严格符合当前筛选（城市/类型/关键词）的数量——诚实显示「发现 N，符合 M」，
  // 避免「发现 47 却 0 展示」的误导。
  const newMatching = useMemo(
    () => officialJobs.filter((job) => jobMatchesFilters(job, filters)),
    [officialJobs, filters],
  );

  // 一键放宽城市 + 岗位类型（保留关键词），让本次发现的岗位可见。
  function relaxLocationAndType() {
    setFilters((f) => ({ ...f, city: "", jobType: "" }));
    setOnlyNew(true);
  }

  function handleExistingJobsSearch() {
    setOfficialJobs([]);
    setOnlyNew(false);
    setDiscoveryRound(0);
    setSearchInfo(
      `仅搜索本地 jobs 表，不触发外部请求。当前命中 ${existingFilteredCount} 个岗位。`,
    );
  }

  async function handleOfficialDiscovery({
    forceRefresh = false,
    queryOffset = 0,
  }: { forceRefresh?: boolean; queryOffset?: number } = {}) {
    const query = filters.keyword;
    if (!query) {
      setSearchInfo("请先在「关键词」里输入要发现的方向（如 算法 / 产品 / 数据分析）。");
      return;
    }

    setDiscovering(true);
    setSearchInfo(
      forceRefresh
        ? "正在强制刷新中国官方招聘源..."
        : `正在发现中国官方招聘源（第 ${queryOffset + 1} 次检索）...`,
    );
    try {
      const params = new URLSearchParams({
        query,
        limit: "30",
        jobType: filters.jobType || "",
        city: filters.city || "",
        queryOffset: String(queryOffset),
      });
      if (forceRefresh) params.set("forceRefresh", "1");
      const resp = await fetch(`/api/discovery?${params}`);
      const data = await resp.json();

      if (data.ok) {
        const scored = mapApiSearchJobsToScoredJobs(data.jobs || [], query) as ScoredJob[];
        // 累积：每次发现的岗位合并进来（按 jd_url 去重）；后端每次都已写库
        setOfficialJobs((prev) => {
          const seen = new Set(prev.map((j) => j.jd_url || j.id));
          return [...prev, ...scored.filter((j) => !seen.has(j.jd_url || j.id))];
        });
        if (scored.length) setOnlyNew(true); // 有新岗位则默认切到「只看新发现」
        setSearchInfo(formatDiscoveryResult(data, scored.length));
        setDiscoveryRound(queryOffset + 1); // 下次点击换下一组检索词
      } else {
        setSearchInfo(formatDiscoveryError(data));
      }
    } catch (err) {
      setSearchInfo("中国官方源发现失败，仍显示本地岗位");
    } finally {
      setDiscovering(false);
    }
  }

  // 按需「浏览器发现」：触发后台 Playwright 抓取官方 SPA 招聘站，前端轮询状态。
  async function handleBrowserDiscovery() {
    const query = filters.keyword;
    if (!query) {
      setSearchInfo("请先在「关键词」里输入要发现的方向（如 算法 / 产品 / 数据分析）。");
      return;
    }
    setSearchInfo("");
    const startedAt = Date.now();
    setDiscovery({
      phase: "queued",
      runId: null,
      startedAt,
      elapsedSec: 0,
      note: "正在触发后台浏览器抓取…",
    });
    try {
      const resp = await fetch("/api/discovery/dispatch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          city: filters.city || "",
          jobType: filters.jobType || "",
          limit: 30,
        }),
      });
      const data = await resp.json();
      if (!data.ok || !data.run_id) {
        setDiscovery({ phase: "idle", runId: null, startedAt: null, elapsedSec: 0, note: "" });
        clearDiscoveryTask();
        setSearchInfo(formatDispatchError(data));
        return;
      }
      // 持久化任务：切到别的页面再回到岗位库时能恢复轮询、不丢任务
      saveDiscoveryTask(data.run_id, startedAt, query);
      setDiscovery((prev) => ({
        ...prev,
        phase: "queued",
        runId: data.run_id,
        note: "已进入后台队列，等待浏览器抓取…",
      }));
    } catch {
      setDiscovery({ phase: "idle", runId: null, startedAt: null, elapsedSec: 0, note: "" });
      clearDiscoveryTask();
      setSearchInfo("按需发现触发失败，请稍后再试。");
    }
  }

  function finishBrowserDiscovery(data: any) {
    const scored = mapApiSearchJobsToScoredJobs(
      data.jobs || [],
      data.query || filters.keyword,
    ) as ScoredJob[];
    if (scored.length) {
      setOfficialJobs((prev) => {
        const seen = new Set(prev.map((j) => j.jd_url || j.id));
        return [...scored.filter((j) => !seen.has(j.jd_url || j.id)), ...prev];
      });
      setOnlyNew(true); // 发现完成有新岗位 → 默认只看本次新发现
    }
    setSearchInfo(formatBrowserDiscoveryResult(data));
    setDiscovery({ phase: "idle", runId: null, startedAt: null, elapsedSec: 0, note: "" });
    clearDiscoveryTask();
  }

  // 跨页面恢复（修「点了发现后切到别的页面、任务就看不到了」的 bug）：
  // 回到岗位库时若 localStorage 里有未超时的发现任务，恢复 runId → 下方轮询 effect 自动续上。
  useEffect(() => {
    if (typeof window === "undefined") return;
    let saved: { runId?: string; startedAt?: number; query?: string } | null = null;
    try {
      const raw = localStorage.getItem(DISCOVERY_STORAGE_KEY);
      saved = raw ? JSON.parse(raw) : null;
    } catch {
      saved = null;
    }
    if (!saved?.runId || !saved.startedAt) return;
    const elapsed = Date.now() - saved.startedAt;
    if (elapsed >= DISCOVERY_TIMEOUT_MS) {
      clearDiscoveryTask();
      return;
    }
    setDiscovery({
      phase: "running",
      runId: saved.runId,
      startedAt: saved.startedAt,
      elapsedSec: Math.floor(elapsed / 1000),
      note: "已恢复后台发现任务，继续等待结果…",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 轮询 + 计时：runId 一旦确定就开始，终态/卸载时清理。
  useEffect(() => {
    if (!discovery.runId) return;
    const runId = discovery.runId;
    let stopped = false;

    tickRef.current = setInterval(() => {
      setDiscovery((prev) =>
        prev.startedAt
          ? { ...prev, elapsedSec: Math.floor((Date.now() - prev.startedAt) / 1000) }
          : prev,
      );
    }, 1000);

    async function poll() {
      try {
        const resp = await fetch(`/api/discovery/status?runId=${runId}`);
        const data = await resp.json();
        if (stopped) return;
        if (!data.ok) return; // 暂时性错误，下次轮询再试
        if (data.is_terminal) {
          finishBrowserDiscovery(data);
          return;
        }
        if (data.phase === "running") {
          setDiscovery((prev) => (prev.phase === "running" ? prev : { ...prev, phase: "running" }));
        }
      } catch {
        // 网络抖动忽略，等下次轮询
      }
    }

    pollRef.current = setInterval(poll, DISCOVERY_POLL_MS);
    poll();

    const timeout = setTimeout(() => {
      if (stopped) return;
      setDiscovery({ phase: "idle", runId: null, startedAt: null, elapsedSec: 0, note: "" });
      clearDiscoveryTask();
      setSearchInfo("后台浏览器发现仍在运行，可稍后刷新页面查看新增岗位。");
    }, DISCOVERY_TIMEOUT_MS);

    return () => {
      stopped = true;
      if (pollRef.current) clearInterval(pollRef.current);
      if (tickRef.current) clearInterval(tickRef.current);
      clearTimeout(timeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [discovery.runId]);

  async function handleKnownChinaRefresh() {
    const query = filters.keyword;
    if (!query) {
      setOfficialJobs([]);
      setSearchInfo("");
      return;
    }

    setRefreshing(true);
    setSearchInfo("正在刷新已知中国官网源...");
    try {
      const params = new URLSearchParams({
        query,
        limit: "30",
        function: filters.jobType !== "" ? filters.jobType : "all",
        city: filters.city !== "" ? filters.city : "",
      });
      const resp = await fetch(`/api/search?${params}`);
      const data = await resp.json();

      if (data.ok) {
        const scored = mapApiSearchJobsToScoredJobs(
          data.jobs || [],
          query,
        ) as ScoredJob[];

        setOfficialJobs(scored);
        setOnlyNew(scored.length > 0); // 刷到新岗位则默认只看本次新发现
        setSearchInfo(formatKnownRefreshResult(data, scored.length));
      } else {
        setSearchInfo(data?.error || "已知中国官网源刷新失败，仍显示本地岗位。");
      }
    } catch (err) {
      setSearchInfo("已知中国官网源刷新失败，仍显示本地岗位。");
    } finally {
      setRefreshing(false);
    }
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
        <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold text-[#3f3a33]">
          <MagnifyingGlass size={16} weight="bold" aria-hidden="true" />
          获取岗位的三种方式
          <span className="text-xs font-normal text-[#9a9184]">（刷新 / 发现需先在上方填「关键词」）</span>
        </div>
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          <ActionTile
            icon={Database}
            label="搜索已有岗位"
            hint="只查本地库，不联网"
            accent="bg-[#ece7dd] text-[#3f3a33]"
            onClick={handleExistingJobsSearch}
          />
          <ActionTile
            icon={ArrowsClockwise}
            label={refreshing ? "刷新中…" : "刷新已知官网源"}
            hint="已验证的百度 / 京东官方源"
            accent="bg-[#dbe9fa] text-[#2f6299]"
            onClick={handleKnownChinaRefresh}
            disabled={refreshing || discovering || discoveryActive || !filters.keyword}
            busy={refreshing}
          />
          <ActionTile
            icon={Compass}
            label={discoveryActive ? "发现中…" : "发现官方招聘源"}
            hint="真实浏览器抓 SPA，约 1–5 分钟"
            accent="bg-[#e7def4] text-[#6a4fa0]"
            onClick={handleBrowserDiscovery}
            disabled={refreshing || discovering || discoveryActive || !filters.keyword}
            busy={discoveryActive}
            hero
          />
          <ActionTile
            icon={Lightning}
            label="强制刷新"
            hint="忽略缓存，重新发现"
            accent="bg-[#fbeecb] text-[#8a6312]"
            onClick={() => handleOfficialDiscovery({ forceRefresh: true })}
            disabled={refreshing || discovering || discoveryActive || !filters.keyword}
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
        {filtered.length} 个岗位，已展示 {Math.min(visibleCount, filtered.length)} 个（本地岗位库 {localJobs.length}{libLoading ? ` / 共 ${initialTotal}，载入中…` : ""} + 本次官网刷新/发现 {officialJobs.length}）。本地搜索、已知源刷新、动态官方源发现三层分开执行。
      </p>
      <div className="space-y-3">
        {visibleJobs.map((job) => (
          <JobCard
            key={job.id}
            job={job}
            sessionNew={sessionNewKeys.has(job.jd_url || job.id)}
            onActionChange={handleActionChange}
          />
        ))}
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

function jobMatchesFilters(job: ScoredJob, filters: Filters) {
  if (filters.company && job.company !== filters.company) return false;
  if (filters.city) {
    const normalizedCity = normalizeChinaCity(filters.city);
    const location = job.location || "";
    if (!location.includes(filters.city) && !location.includes(normalizedCity)) {
      return false;
    }
  }
  if (filters.jobType) {
    // 用穷尽的三桶分类（社招 / 校招 / 实习）精确匹配，避免细粒度类型（管培生 / 研究岗 / 全职等）漏桶。
    if (recruitmentCategory(job) !== filters.jobType) return false;
  }
  if (filters.keyword) {
    if (!jobMatchesChinaKeyword(job, filters.keyword)) return false;
  }
  if (filters.showNewOnly) {
    if (!job.first_seen_at) return false;
    const days = job.first_seen_at
      ? (Date.now() - new Date(job.first_seen_at).getTime()) / 86400000
      : 999;
    if (days > 3) return false;
  }
  if (!filters.showIgnored && job.hidden_reason === "ignored") return false;
  if (!filters.showApplied && job.hidden_reason === "applied_by_default") return false;
  if (filters.capitalOrigin) {
    const origin = classifyCompanyOrigin(job.company);
    if (filters.capitalOrigin === "外企") {
      if (origin === "中国") return false;
    } else if (origin !== filters.capitalOrigin) return false;
  }
  if (filters.salaryOnly && !job.salary_text) return false;
  return true;
}

function formatKnownRefreshResult(data: any, returnedJobs: number) {
  return [
    `已刷新已知中国官网源，返回 ${returnedJobs} 个岗位。`,
    `中国官网源命中 ${data.chinaKnownSources ?? 0}，入库 ${data.jobs_created ?? 0} / 更新 ${data.jobs_updated ?? 0}。`,
    data.priority || "",
    `耗时 ${data.latencyMs || 0}ms。`,
  ]
    .filter(Boolean)
    .join(" ");
}

function formatDiscoveryResult(data: any, returnedJobs: number) {
  const reason = data.failure_reason || data.diagnostics?.failure_reason || "";
  const FRIENDLY_REASON: Record<string, string> = {
    all_results_rejected:
      "本次未发现新的官方源——搜索结果均为第三方平台 / 转载 / SEO 聚合页，已按规则过滤（这是预期的过滤行为，不是错误）。",
    provider_no_results: "本次搜索没有返回结果，可换个关键词或稍后再试。",
    candidates_pending: "发现了官方源候选，已记入待解析（暂无对应 parser）。",
    parser_missing: "发现了官方源，但暂无对应解析器，已记入候选待接入。",
    quality_gate_failed: "找到疑似岗位但未通过质量门（链接/标题校验），未入库。",
    provider_rate_limited: "百度千帆当日额度已用尽，已停止调用——明天恢复或稍后再试。",
  };
  const statusText =
    !data.status || data.status === "success"
      ? ""
      : FRIENDLY_REASON[reason]
        ? FRIENDLY_REASON[reason] + " "
        : `发现未成功（${data.status}）：${data.error_message || reason || "未写入岗位"}。`;
  const cacheText = data.cache_hit ? `cache_hit=true，来源 ${data.cache_source || "cache"}。` : "";
  const rateLimitText = data.rate_limited ? "百度千帆 rate_limited=true，已停止继续调用千帆。" : "";
  const providers = formatProviderDiagnostics(data.diagnostics?.providers || []);
  const runId = data.discovery_run_id ? `run ${data.discovery_run_id.slice(0, 8)}。` : "";
  const queryText = `本次调用 generated query #${(data.query_offset ?? 0) + 1}，调用数 ${data.generated_queries_called_count ?? data.diagnostics?.generated_queries_called_count ?? 0}。`;

  return [
    statusText,
    cacheText,
    rateLimitText,
    queryText,
    `生成 query ${data.generated_queries?.length ?? data.searchedQueries?.length ?? 0}，raw ${data.raw_results_count ?? data.diagnostics?.raw_results_count ?? 0}，官方候选 ${data.official_candidates_count ?? data.candidates_found ?? data.candidatesFound ?? 0}，第三方/转载 rejected ${data.rejected_third_party_count ?? data.diagnostics?.rejected_third_party_count ?? 0}。`,
    `source_candidates 新增/更新 ${data.source_candidates_created ?? data.diagnostics?.candidates?.created ?? 0}，pending ${data.pending_candidates ?? data.candidatesPending ?? 0}，解析岗位 ${data.parsed_jobs ?? returnedJobs}，入库 ${data.jobs_created ?? data.jobsCreated ?? 0} / 更新 ${data.jobs_updated ?? data.jobsUpdated ?? 0}。`,
    data.failure_reason || data.diagnostics?.failure_reason
      ? `failure_reason: ${data.failure_reason || data.diagnostics?.failure_reason}。`
      : "",
    providers,
    runId,
    `耗时 ${data.latencyMs || 0}ms。`,
  ]
    .filter(Boolean)
    .join(" ");
}

function formatDiscoveryError(data: any) {
  const providers = formatProviderDiagnostics(data?.diagnostics?.providers || []);
  return [
    data?.error || data?.error_message || "中国官方源发现失败，仍显示本地岗位。",
    providers,
  ]
    .filter(Boolean)
    .join(" ");
}

function formatProviderDiagnostics(providers: any[]) {
  if (!Array.isArray(providers) || providers.length === 0) return "";

  return providers
    .map((provider) => {
      const httpStatus = provider.http_status ? ` HTTP ${provider.http_status}` : "";
      const raw = provider.raw_results_count ?? provider.rawResultsCount ?? 0;
      const extracted = provider.extracted_urls_count ?? provider.extracted_urls ?? 0;
      return `${provider.provider_name || provider.name}:${provider.status}${httpStatus}, raw ${raw}, URLs ${extracted}`;
    })
    .join("；");
}

function formatElapsed(sec: number) {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function formatDispatchError(data: any) {
  const MAP: Record<string, string> = {
    dispatch_not_configured:
      "按需「浏览器发现」未启用：服务端缺少 GITHUB_DISPATCH_TOKEN / GITHUB_DISPATCH_REPO 配置。",
    run_insert_failed: "发现任务创建失败：请确认已应用数据库迁移 009（discovery_runs 异步列）。",
    dispatch_failed: `触发后台抓取失败：${data?.detail || ""}`,
    invalid_input: "入参不合法，请检查关键词后重试。",
    Unauthorized: "未登录或会话已过期，请重新登录后再试。",
  };
  return MAP[data?.error] || data?.error_message || data?.error || "按需发现触发失败，请稍后再试。";
}

function formatBrowserDiscoveryResult(data: any) {
  const isDone =
    data?.phase === "done" || data?.status === "success" || data?.status === "partial_success";
  if (isDone) {
    const created = data?.jobs_created ?? 0;
    const updated = data?.jobs_updated ?? 0;
    const shown = data?.total ?? 0;
    if (created > 0 || updated > 0 || shown > 0) {
      return `浏览器发现完成：新增 ${created} / 更新 ${updated} 个官方岗位，本次展示 ${shown} 个（已入共享库）。`;
    }
    return "浏览器发现完成，但本次没有命中该关键词的官方岗位——换个关键词或去掉城市再试。";
  }
  const MAP: Record<string, string> = {
    no_recipe_matched: "暂无匹配的平台配方（当前覆盖字节 / 飞书系：蔚来·小鹏·地平线·小米）。",
    no_spa_sources_in_db: "未找到可抓取的官方源——请先应用迁移 010（seed SPA 源）。",
    no_jobs_passed_quality: "抓到岗位但未通过质量门 / 未命中关键词，未入库。",
    dispatch_failed: "后台抓取触发失败。",
    discovery_exception: `后台抓取异常：${data?.error_message || ""}`,
  };
  const reason = data?.failure_reason || "";
  return (
    MAP[reason] ||
    `本次发现未成功（${data?.status || "failed"}）：${data?.error_message || reason || "未写入岗位"}。`
  );
}

// 获取岗位的动作磁贴：图标 + 标题 + 一句说明，比原来的小药丸按钮更醒目（核心功能）
function ActionTile({
  icon: Icon,
  label,
  hint,
  accent,
  onClick,
  disabled,
  busy,
  hero,
}: {
  icon: typeof Database;
  label: string;
  hint: string;
  accent: string;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
  hero?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={hint}
      className={cn(
        "group flex items-center gap-3 rounded-2xl border px-4 py-3 text-left transition duration-200 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45",
        hero
          ? "border-[#cfc0e6] bg-[#efe9f8] hover:border-[#bba9dd] hover:bg-[#e7def4]"
          : "border-black/[0.07] bg-white/60 hover:border-black/[0.12] hover:bg-white",
      )}
    >
      <span className={cn("grid size-9 shrink-0 place-items-center rounded-xl", accent)}>
        {busy ? (
          <CircleNotch size={18} weight="bold" className="animate-spin" aria-hidden="true" />
        ) : (
          <Icon size={18} weight="fill" aria-hidden="true" />
        )}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-[#1a1714]">{label}</span>
        <span className="block truncate text-xs text-[#8a8275]">{hint}</span>
      </span>
    </button>
  );
}

function BrowserDiscoveryProgress({ discovery }: { discovery: BrowserDiscoveryState }) {
  const stages = [
    "触发后台浏览器抓取",
    "加载官网 · 拦截官方接口 · 质量门入库",
  ];
  const activeIndex = discovery.phase === "queued" ? 0 : 1;
  const pct = discovery.phase === "queued" ? 18 : 64;

  return (
    <div className="surface p-4 text-[#1a1714]">
      <div className="flex items-center gap-2.5">
        <CircleNotch size={18} weight="bold" className="animate-spin text-[#3f7cc0]" aria-hidden="true" />
        <span className="text-sm font-semibold">正在发现官方招聘源…</span>
        <span className="ml-auto text-xs tabular-nums text-[#8a8275]">
          已用时 {formatElapsed(discovery.elapsedSec)} · 预计 1–5 分钟
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
        可离开本页，发现完成后结果会自动进岗位库；回到本页或刷新即可看到新增岗位。
      </p>
    </div>
  );
}

"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import JobCard from "@/components/JobCard";
import JobFilters from "@/components/JobFilters";
import { mapApiSearchJobsToScoredJobs } from "@/lib/client-job-mapping";
import {
  jobMatchesChinaKeyword,
  normalizeChinaCity,
  normalizeChinaJobType,
} from "@/lib/china-keyword-expansion";
import { classifyCompanyOrigin } from "@/lib/company-origin";
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
  companies: string[];
}

export default function JobsClient({ initialJobs, companies }: Props) {
  const [filters, setFilters] = useState<Filters>({
    company: "",
    city: "",
    jobType: "",
    keyword: "",
    showIgnored: false,
    showApplied: false,
    showNewOnly: false,
    sortBy: "match",
    capitalOrigin: "",
    salaryOnly: false,
  });
  const [officialJobs, setOfficialJobs] = useState<ScoredJob[]>([]);
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

  // 合并本地岗位库 + 本次已知源刷新/官方源发现返回的岗位
  const allJobs = useMemo(() => {
    const seen = new Set(officialJobs.map((j) => j.jd_url || j.id));
    const cachedNotInLive = initialJobs.filter((j) => !seen.has(j.jd_url || j.id));
    return [...officialJobs, ...cachedNotInLive];
  }, [initialJobs, officialJobs]);

  const filtered = useMemo(() => {
    const arr = allJobs.filter((job) => jobMatchesFilters(job, filters));
    arr.sort((a, b) =>
      filters.sortBy === "newest"
        ? new Date(b.posted_at || b.first_seen_at || 0).getTime() -
          new Date(a.posted_at || a.first_seen_at || 0).getTime()
        : (b.match_score || 0) - (a.match_score || 0),
    );
    return arr;
  }, [allJobs, filters]);

  // 分批渲染：默认只渲染前 JOBS_PAGE_SIZE 张，「加载更多」逐批增加；筛选变化时回到第一批。
  const [visibleCount, setVisibleCount] = useState(JOBS_PAGE_SIZE);
  useEffect(() => {
    setVisibleCount(JOBS_PAGE_SIZE);
  }, [filters]);
  const visibleJobs = useMemo(
    () => filtered.slice(0, visibleCount),
    [filtered, visibleCount],
  );

  const existingFilteredCount = useMemo(() => {
    return initialJobs.filter((job) => jobMatchesFilters(job, filters)).length;
  }, [initialJobs, filters]);

  function handleExistingJobsSearch() {
    setOfficialJobs([]);
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
    setDiscovery({
      phase: "queued",
      runId: null,
      startedAt: Date.now(),
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
        setSearchInfo(formatDispatchError(data));
        return;
      }
      setDiscovery((prev) => ({
        ...prev,
        phase: "queued",
        runId: data.run_id,
        note: "已进入后台队列，等待浏览器抓取…",
      }));
    } catch {
      setDiscovery({ phase: "idle", runId: null, startedAt: null, elapsedSec: 0, note: "" });
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
    }
    setSearchInfo(formatBrowserDiscoveryResult(data));
    setDiscovery({ phase: "idle", runId: null, startedAt: null, elapsedSec: 0, note: "" });
  }

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
      <div className="rounded-[1.35rem] border border-white/10 bg-white/[0.055] p-4 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
        <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={handleExistingJobsSearch}
          className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm font-medium text-white/78 transition duration-200 hover:bg-white/16 hover:text-white active:scale-[0.98]"
        >
          <Database size={16} weight="fill" aria-hidden="true" />
          搜索已有岗位
        </button>
        <button
          onClick={handleKnownChinaRefresh}
          disabled={refreshing || discovering || discoveryActive || !filters.keyword}
          className="inline-flex items-center gap-2 rounded-full bg-sky-300 px-4 py-2 text-sm font-semibold text-sky-950 transition duration-200 hover:bg-sky-200 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <ArrowsClockwise size={16} weight="bold" aria-hidden="true" />
          {refreshing ? "刷新中..." : "刷新已知中国官网源"}
        </button>
        <button
          onClick={handleBrowserDiscovery}
          disabled={refreshing || discovering || discoveryActive || !filters.keyword}
          title="触发后台真实浏览器抓取官方 SPA 招聘站（字节 / 飞书系：蔚来·小鹏·地平线·小米），约 1–5 分钟，结果自动入库"
          className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm font-medium text-white/78 transition duration-200 hover:bg-white/16 hover:text-white active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Compass size={16} weight="fill" aria-hidden="true" />
          {discoveryActive ? "发现中…" : "发现中国官方招聘源"}
        </button>
        <button
          onClick={() => handleOfficialDiscovery({ forceRefresh: true })}
          disabled={refreshing || discovering || discoveryActive || !filters.keyword}
          className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm font-medium text-white/78 transition duration-200 hover:bg-white/16 hover:text-white active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Lightning size={16} weight="fill" aria-hidden="true" />
          强制刷新
        </button>
        {searchInfo && (
          <span className="min-w-0 flex-1 rounded-2xl border border-white/10 bg-black/20 px-3 py-2 text-pretty text-sm leading-6 text-white/58">{searchInfo}</span>
        )}
        </div>
      </div>
      {discoveryActive && <BrowserDiscoveryProgress discovery={discovery} />}
      <p className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.045] px-3 py-2 text-sm leading-6 text-white/58">
        <MagnifyingGlass size={16} weight="bold" aria-hidden="true" />
        匹配 {filtered.length} 个岗位，已展示 {Math.min(visibleCount, filtered.length)} 个（本地岗位库 {initialJobs.length} + 本次官网刷新/发现 {officialJobs.length}）。本地搜索、已知源刷新、动态官方源发现三层分开执行。
      </p>
      <div className="space-y-3">
        {visibleJobs.map((job) => (
          <JobCard
            key={job.id}
            job={job}
            onActionChange={handleActionChange}
          />
        ))}
        {filtered.length === 0 && (
          <div className="rounded-[1.5rem] border border-dashed border-white/14 bg-white/[0.05] px-6 py-14 text-center">
            <h2 className="text-lg font-semibold text-white">没有匹配的岗位</h2>
            <p className="mx-auto mt-2 max-w-md text-pretty text-sm leading-6 text-white/56">
              可以放宽筛选条件，或输入关键词后刷新已知官网源 / 发现新的官方招聘入口。
            </p>
          </div>
        )}
      </div>
      {filtered.length > visibleCount && (
        <div className="flex justify-center pt-1">
          <button
            type="button"
            onClick={() => setVisibleCount((n) => n + JOBS_PAGE_SIZE)}
            className="inline-flex items-center gap-2 rounded-full border border-white/12 bg-white/[0.06] px-5 py-2.5 text-sm font-medium text-white/80 transition duration-200 hover:bg-white/12 hover:text-white active:scale-[0.98]"
          >
            加载更多
            <span className="tabular-nums text-white/50">
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
    const recruitType =
      normalizeChinaJobType({
        title: job.title,
        sourceType: job.job_type,
        summary: job.summary,
      }) ||
      job.job_type ||
      "";
    if (!recruitType.includes(filters.jobType)) return false;
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

function BrowserDiscoveryProgress({ discovery }: { discovery: BrowserDiscoveryState }) {
  const stages = [
    "触发后台浏览器抓取",
    "加载官网 · 拦截官方接口 · 质量门入库",
  ];
  const activeIndex = discovery.phase === "queued" ? 0 : 1;
  const pct = discovery.phase === "queued" ? 18 : 64;

  return (
    <div className="rounded-[1.35rem] border border-white/12 bg-white/[0.06] p-4 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
      <div className="flex items-center gap-2.5">
        <CircleNotch size={18} weight="bold" className="animate-spin text-sky-300" aria-hidden="true" />
        <span className="text-sm font-semibold">正在发现官方招聘源…</span>
        <span className="ml-auto text-xs tabular-nums text-white/55">
          已用时 {formatElapsed(discovery.elapsedSec)} · 预计 1–5 分钟
        </span>
      </div>
      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-black/25">
        <div
          className="h-full rounded-full bg-sky-300 transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
      <ol className="mt-3 space-y-1.5">
        {stages.map((label, i) => {
          const state = i < activeIndex ? "done" : i === activeIndex ? "active" : "pending";
          return (
            <li key={label} className="flex items-center gap-2 text-sm">
              {state === "done" ? (
                <CheckCircle size={16} weight="fill" className="shrink-0 text-sky-300" aria-hidden="true" />
              ) : state === "active" ? (
                <CircleNotch size={16} weight="bold" className="shrink-0 animate-spin text-sky-300" aria-hidden="true" />
              ) : (
                <Circle size={16} className="shrink-0 text-white/30" aria-hidden="true" />
              )}
              <span
                className={
                  state === "pending"
                    ? "text-white/40"
                    : state === "active"
                      ? "text-white"
                      : "text-white/65"
                }
              >
                {`${i + 1}. ${label}`}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-pretty text-xs leading-5 text-white/50">
        可离开本页，发现完成后结果会自动进岗位库；回到本页或刷新即可看到新增岗位。
      </p>
    </div>
  );
}

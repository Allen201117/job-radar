"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import JobCard from "@/components/JobCard";
import JobFilters from "@/components/JobFilters";
import { mapApiSearchJobsToScoredJobs } from "@/lib/client-job-mapping";
import {
  jobMatchesChinaKeyword,
  normalizeChinaCity,
} from "@/lib/china-keyword-expansion";
import type { ScoredJob } from "@/lib/types";

type PrimaryAction = "saved" | "ignored" | "applied";

type Filters = {
  company: string;
  city: string;
  jobType: string;
  keyword: string;
  showIgnored: boolean;
  showApplied: boolean;
  showNewOnly: boolean;
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
  });
  const [officialJobs, setOfficialJobs] = useState<ScoredJob[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [searchInfo, setSearchInfo] = useState("");
  const [canContinueDiscovery, setCanContinueDiscovery] = useState(false);
  const router = useRouter();

  // 合并本地岗位库 + 本次已知源刷新/官方源发现返回的岗位
  const allJobs = useMemo(() => {
    const seen = new Set(officialJobs.map((j) => j.jd_url || j.id));
    const cachedNotInLive = initialJobs.filter((j) => !seen.has(j.jd_url || j.id));
    return [...officialJobs, ...cachedNotInLive];
  }, [initialJobs, officialJobs]);

  const filtered = useMemo(() => {
    return allJobs.filter((job) => jobMatchesFilters(job, filters));
  }, [allJobs, filters]);

  const existingFilteredCount = useMemo(() => {
    return initialJobs.filter((job) => jobMatchesFilters(job, filters)).length;
  }, [initialJobs, filters]);

  function handleExistingJobsSearch() {
    setOfficialJobs([]);
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
      setOfficialJobs([]);
      setSearchInfo("");
      setCanContinueDiscovery(false);
      return;
    }

    setDiscovering(true);
    setSearchInfo(forceRefresh ? "正在强制刷新中国官方招聘源..." : "正在发现中国官方招聘源...");
    try {
      const params = new URLSearchParams({
        query,
        limit: "30",
        jobType: filters.jobType !== "" ? filters.jobType : "",
        city: filters.city !== "" ? filters.city : "",
        queryOffset: String(queryOffset),
      });
      if (forceRefresh) params.set("forceRefresh", "1");
      const resp = await fetch(`/api/discovery?${params}`);
      const data = await resp.json();

      if (data.ok) {
        const scored = mapApiSearchJobsToScoredJobs(
          data.jobs || [],
          query,
        ) as ScoredJob[];

        setOfficialJobs(scored);
        setSearchInfo(formatDiscoveryResult(data, scored.length));
        setCanContinueDiscovery(Boolean(data.can_continue_discovery));
      } else {
        setSearchInfo(formatDiscoveryError(data));
        setCanContinueDiscovery(false);
      }
    } catch (err) {
      setSearchInfo("中国官方源发现失败，仍显示本地岗位");
      setCanContinueDiscovery(false);
    } finally {
      setDiscovering(false);
    }
  }

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
    <div className="space-y-4">
      <JobFilters filters={filters} onChange={setFilters} companies={companies} />
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={handleExistingJobsSearch}
          className="rounded-md border border-border px-4 py-1.5 text-sm font-medium hover:bg-muted"
        >
          搜索已有岗位
        </button>
        <button
          onClick={handleKnownChinaRefresh}
          disabled={refreshing || discovering || !filters.keyword}
          className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          {refreshing ? "刷新中..." : "刷新已知中国官网源"}
        </button>
        <button
          onClick={() => handleOfficialDiscovery()}
          disabled={refreshing || discovering || !filters.keyword}
          className="rounded-md border border-border px-4 py-1.5 text-sm font-medium hover:bg-muted disabled:opacity-50"
        >
          {discovering ? "发现中..." : "发现中国官方招聘源"}
        </button>
        <button
          onClick={() => handleOfficialDiscovery({ queryOffset: 1 })}
          disabled={refreshing || discovering || !filters.keyword || !canContinueDiscovery}
          className="rounded-md border border-border px-4 py-1.5 text-sm font-medium hover:bg-muted disabled:opacity-50"
        >
          继续发现更多
        </button>
        <button
          onClick={() => handleOfficialDiscovery({ forceRefresh: true })}
          disabled={refreshing || discovering || !filters.keyword}
          className="rounded-md border border-border px-4 py-1.5 text-sm font-medium hover:bg-muted disabled:opacity-50"
        >
          强制刷新
        </button>
        {searchInfo && (
          <span className="text-sm text-muted-foreground">{searchInfo}</span>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        显示 {filtered.length} 个岗位（本地岗位库 {initialJobs.length} + 本次官网刷新/发现 {officialJobs.length}）。本地搜索、已知源刷新、动态官方源发现三层分开执行。
      </p>
      <div className="space-y-3">
        {filtered.map((job) => (
          <JobCard
            key={job.id}
            job={job}
            onActionChange={handleActionChange}
          />
        ))}
        {filtered.length === 0 && (
          <p className="py-12 text-center text-muted-foreground">没有匹配的岗位。</p>
        )}
      </div>
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
  if (filters.jobType && !(job.job_type || "").includes(filters.jobType)) return false;
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

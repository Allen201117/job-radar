"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  filterAndRankJobs,
  DEFAULT_FILTERS,
  type Filters,
} from "@/lib/job-filter";
import type { ScoredJob } from "@/lib/types";

// 每页（首屏 / 「加载更多」）的服务端分页大小。
export const JOBS_PAGE_SIZE = 60;
export type { Filters };

type RankedJob = ScoredJob & { __tier: "exact" | "related" };

// 把筛选条件序列化成 /api/jobs/search 的查询串。
function filtersToParams(f: Filters, offset: number, limit: number): string {
  const p = new URLSearchParams();
  if (f.company.trim()) p.set("company", f.company.trim());
  if (f.city.trim()) p.set("city", f.city.trim());
  if (f.jobType) p.set("jobType", f.jobType);
  if (f.keyword.trim()) p.set("keyword", f.keyword.trim());
  if (f.capitalOrigin) p.set("capitalOrigin", f.capitalOrigin);
  if (f.salaryOnly) p.set("salaryOnly", "1");
  if (f.showIgnored) p.set("showIgnored", "1");
  if (f.showApplied) p.set("showApplied", "1");
  if (f.showNewOnly) p.set("showNewOnly", "1");
  p.set("sortBy", f.sortBy);
  p.set("offset", String(offset));
  p.set("limit", String(limit));
  return p.toString();
}

type ServerState = {
  jobs: RankedJob[];
  total: number;
  exactCount: number;
  capped: boolean;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
};

type UseJobFiltersArgs = {
  // 本次会话内由「刷新已知源 / 发现官方源」新拿到的岗位（前端置顶展示）
  officialJobs: ScoredJob[];
  // 「只看新发现」开关
  onlyNew: boolean;
  // 从用户已保存偏好预填的筛选初值（城市/类型/关键词）；用户手动改即覆盖。
  initialFilters?: { city?: string; jobType?: string; keyword?: string };
  // SSR 首页岗位（无初始筛选时做即时首屏）+ 活跃总数（无筛选浏览时的诚实计数）
  initialJobs: ScoredJob[];
  initialTotal: number;
};

// 服务端筛选版：筛选/分页改由 /api/jobs/search 在服务端跑（库已 10万+，前端不再全量加载）。
// 匹配/排序逻辑复用 lib/job-filter（与服务端同一份）→ 结果一致。会话新发现仍在前端置顶合并。
export function useJobFilters({
  officialJobs,
  onlyNew,
  initialFilters,
  initialJobs,
  initialTotal,
}: UseJobFiltersArgs) {
  const [filters, setFilters] = useState<Filters>({
    ...DEFAULT_FILTERS,
    city: initialFilters?.city || "",
    jobType: initialFilters?.jobType || "",
    keyword: initialFilters?.keyword || "",
  });

  const hasInitialFilter = Boolean(
    initialFilters?.city || initialFilters?.jobType || initialFilters?.keyword,
  );

  // 无初始筛选 → 用 SSR 首页(取前一页)做即时首屏；有初始筛选 → 首搜返回前先空(免闪未筛选的错误内容)。
  const seed: RankedJob[] = hasInitialFilter
    ? []
    : (initialJobs.slice(0, JOBS_PAGE_SIZE).map((j) => ({
        ...j,
        __tier: "exact" as const,
      })) as RankedJob[]);

  const [server, setServer] = useState<ServerState>({
    jobs: seed,
    total: hasInitialFilter ? 0 : initialTotal,
    exactCount: hasInitialFilter ? 0 : seed.length,
    capped: false,
    loading: true,
    loadingMore: false,
    error: null,
  });

  // 单调请求号：晚到的旧请求结果一律丢弃，避免竞态把新搜索覆盖回旧结果。
  const reqRef = useRef(0);

  const runSearch = useCallback(async (f: Filters, offset: number) => {
    const myReq = ++reqRef.current;
    const more = offset > 0;
    setServer((s) => ({ ...s, loading: !more, loadingMore: more, error: null }));
    try {
      const resp = await fetch(
        `/api/jobs/search?${filtersToParams(f, offset, JOBS_PAGE_SIZE)}`,
      );
      const data = await resp.json();
      if (myReq !== reqRef.current) return; // 已被更新的搜索取代
      if (!data?.ok) {
        setServer((s) => ({
          ...s,
          loading: false,
          loadingMore: false,
          error: data?.error || "搜索失败",
        }));
        return;
      }
      const batch: RankedJob[] = Array.isArray(data.jobs) ? data.jobs : [];
      setServer((s) => ({
        jobs: more ? [...s.jobs, ...batch] : batch,
        total: data.total ?? 0,
        exactCount: data.exactCount ?? 0,
        capped: Boolean(data.capped),
        loading: false,
        loadingMore: false,
        error: null,
      }));
    } catch {
      if (myReq !== reqRef.current) return;
      setServer((s) => ({
        ...s,
        loading: false,
        loadingMore: false,
        error: "搜索失败，请重试",
      }));
    }
  }, []);

  // 筛选变化 → 防抖 300ms 后重搜（offset 0）。挂载时也会跑一次（应用初始筛选）。
  useEffect(() => {
    const t = setTimeout(() => {
      runSearch(filters, 0);
    }, 300);
    return () => clearTimeout(t);
  }, [filters, runSearch]);

  const loadMore = useCallback(() => {
    if (server.loading || server.loadingMore) return;
    runSearch(filters, server.jobs.length);
  }, [filters, server.jobs.length, server.loading, server.loadingMore, runSearch]);

  const refresh = useCallback(() => {
    runSearch(filters, 0);
  }, [filters, runSearch]);

  // 会话新发现（刷新/发现）：客户端用同一份 jobFilterTier 精筛 + 排序，置顶展示。
  const sessionNewKeys = useMemo(
    () => new Set(officialJobs.map((j) => j.jd_url || j.id)),
    [officialJobs],
  );
  const newMatching = useMemo(
    () => filterAndRankJobs(officialJobs as ScoredJob[], filters, sessionNewKeys),
    [officialJobs, filters, sessionNewKeys],
  );
  const newViewActive = onlyNew && officialJobs.length > 0;

  // 展示列表：只看新发现 → 仅 newMatching；否则 newMatching 置顶 + 服务端库结果（去重）。
  const displayJobs = useMemo<RankedJob[]>(() => {
    if (newViewActive) return newMatching;
    if (newMatching.length === 0) return server.jobs;
    const newKeys = new Set(newMatching.map((j) => j.jd_url || j.id));
    return [...newMatching, ...server.jobs.filter((j) => !newKeys.has(j.jd_url || j.id))];
  }, [newViewActive, newMatching, server.jobs]);

  const hasMore = !newViewActive && server.jobs.length < server.total;

  return {
    filters,
    setFilters,
    sessionNewKeys,
    newViewActive,
    displayJobs,
    total: server.total,
    exactCount: server.exactCount,
    capped: server.capped,
    loading: server.loading,
    loadingMore: server.loadingMore,
    error: server.error,
    hasMore,
    loadMore,
    refresh,
    newMatching,
  };
}

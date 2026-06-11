"use client";

import { useEffect, useMemo, useState } from "react";
import {
  keywordMatchTier,
  normalizeChinaCity,
  recruitmentCategory,
} from "@/lib/china-keyword-expansion";
import { classifyCompanyOrigin } from "@/lib/company-origin";
import type { ScoredJob } from "@/lib/types";

// 每次渲染/「加载更多」的批量大小（前端分批渲染，避免一次性渲染上千张卡片卡顿）
export const JOBS_PAGE_SIZE = 60;

export type Filters = {
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

type UseJobFiltersArgs = {
  // 内存岗位库（SSR 第一页 + 后台补齐，已去重），过滤的基础数据源
  localJobs: ScoredJob[];
  // 本次会话内由「刷新已知源 / 发现官方源」新拿到的岗位
  officialJobs: ScoredJob[];
  // 「只看新发现」开关（由调用方持有，影响过滤视图）
  onlyNew: boolean;
  // 从用户已保存偏好预填的筛选初值（城市/类型/关键词）；用户手动改即覆盖。
  initialFilters?: { city?: string; jobType?: string; keyword?: string };
};

// Filters state + 派生过滤逻辑（useMemo 链）。从 jobs-client 抽出，行为保持不变。
export function useJobFilters({
  localJobs,
  officialJobs,
  onlyNew,
  initialFilters,
}: UseJobFiltersArgs) {
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
    // 两层匹配：每个岗位算出档位（exact/related）；精确层在上、相关层在下，本次新发现置顶。
    const tierRank = (t: string) => (t === "exact" ? 0 : 1);
    const sortVal = (j: ScoredJob) =>
      filters.sortBy === "newest"
        ? new Date(j.posted_at || j.first_seen_at || 0).getTime()
        : j.match_score || 0;
    let arr = allJobs
      .map((job) => ({ job, tier: jobFilterTier(job, filters) }))
      .filter(
        (x): x is { job: ScoredJob; tier: "exact" | "related" } => x.tier !== null,
      );
    if (newViewActive) {
      arr = arr.filter((x) => sessionNewKeys.has(x.job.jd_url || x.job.id));
    }
    arr.sort((a, b) => {
      if (tierRank(a.tier) !== tierRank(b.tier)) return tierRank(a.tier) - tierRank(b.tier);
      const an = sessionNewKeys.has(a.job.jd_url || a.job.id) ? 0 : 1;
      const bn = sessionNewKeys.has(b.job.jd_url || b.job.id) ? 0 : 1;
      if (an !== bn) return an - bn; // 本次新发现置顶（同档内）
      return sortVal(b.job) - sortVal(a.job);
    });
    return arr.map((x) => ({ ...x.job, __tier: x.tier }));
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

  // 精确层数量（用于诚实展示「精确 E + 相关 R」），相关层 = filtered.length - exactCount。
  const exactCount = useMemo(
    () => filtered.reduce((n, j) => n + ((j as any).__tier === "exact" ? 1 : 0), 0),
    [filtered],
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

  return {
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
  };
}

// 返回岗位通过当前筛选的匹配档："exact"（精确）/ "related"（同职能相关）/ null（不匹配）。
// 非关键词项（城市/类型/公司/资本/薪资/新发现/隐藏）仍硬 AND；关键词改两层匹配，治 88% 空摘要的召回崩。
function jobFilterTier(job: ScoredJob, filters: Filters): "exact" | "related" | null {
  if (filters.company) {
    // 大小写不敏感子串匹配：可输入"字节"命中"字节跳动"、"bytedance"命中"ByteDance"。
    const want = filters.company.trim().toLowerCase();
    if (want && !(job.company || "").toLowerCase().includes(want)) return null;
  }
  if (filters.city) {
    const normalizedCity = normalizeChinaCity(filters.city);
    const location = job.location || "";
    if (!location.includes(filters.city) && !location.includes(normalizedCity)) {
      return null;
    }
  }
  if (filters.jobType) {
    // 用穷尽的三桶分类（社招 / 校招 / 实习）精确匹配，避免细粒度类型（管培生 / 研究岗 / 全职等）漏桶。
    if (recruitmentCategory(job) !== filters.jobType) return null;
  }
  if (filters.showNewOnly) {
    if (!job.first_seen_at) return null;
    const days = (Date.now() - new Date(job.first_seen_at).getTime()) / 86400000;
    if (days > 3) return null;
  }
  if (!filters.showIgnored && job.hidden_reason === "ignored") return null;
  if (!filters.showApplied && job.hidden_reason === "applied_by_default") return null;
  if (filters.capitalOrigin) {
    const origin = classifyCompanyOrigin(job.company);
    if (filters.capitalOrigin === "外企") {
      if (origin === "中国") return null;
    } else if (origin !== filters.capitalOrigin) return null;
  }
  if (filters.salaryOnly && !job.salary_text) return null;
  // 关键词两层：无关键词 → 全放行(exact)；否则 精确 / 相关 / 不匹配(null)。
  if (!filters.keyword) return "exact";
  return keywordMatchTier(job, filters.keyword);
}

function jobMatchesFilters(job: ScoredJob, filters: Filters) {
  return jobFilterTier(job, filters) !== null;
}

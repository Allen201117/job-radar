// 岗位筛选 + 两层排序的纯逻辑（从 hooks/useJobFilters.ts 抽出，零行为变化）。
// 抽到 lib 层后，浏览器端筛选钩子(useJobFilters) 与 服务端搜索(lib/job-search → /api/jobs/search)
// 复用同一份匹配逻辑 → 服务端筛选结果与原前端筛选「逐字段一致」，全部既有测试照常通过。
import {
  keywordMatchTier,
  normalizeChinaCity,
  recruitmentCategory,
} from "@/lib/china-keyword-expansion";
import { classifyCompanyOrigin } from "@/lib/company-origin";
import type { ScoredJob } from "@/lib/types";

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

export const DEFAULT_FILTERS: Filters = {
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
};

// 返回岗位通过当前筛选的匹配档："exact"（精确）/ "related"（同职能相关）/ null（不匹配）。
// 非关键词项（城市/类型/公司/资本/薪资/新发现/隐藏）仍硬 AND；关键词改两层匹配，治 88% 空摘要的召回崩。
export function jobFilterTier(
  job: ScoredJob,
  filters: Filters,
): "exact" | "related" | null {
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

export function jobMatchesFilters(job: ScoredJob, filters: Filters): boolean {
  return jobFilterTier(job, filters) !== null;
}

const tierRank = (t: string) => (t === "exact" ? 0 : 1);

// 两层匹配 + 排序：每个岗位算出档位（exact/related），精确层在上、相关层在下；
// 同档内「本次新发现(sessionNewKeys)」置顶，再按 match_score / 发布时间。
// 返回带 __tier 标记的有序数组（与原 useJobFilters 的 filtered useMemo 完全一致）。
// sessionNewKeys 省略时（服务端无会话新发现）该置顶规则自然为空操作。
export function filterAndRankJobs(
  jobs: ScoredJob[],
  filters: Filters,
  sessionNewKeys: Set<string> = new Set(),
): Array<ScoredJob & { __tier: "exact" | "related" }> {
  const sortVal = (j: ScoredJob) =>
    filters.sortBy === "newest"
      ? new Date(j.posted_at || j.first_seen_at || 0).getTime()
      : j.match_score || 0;

  const arr = jobs
    .map((job) => ({ job, tier: jobFilterTier(job, filters) }))
    .filter(
      (x): x is { job: ScoredJob; tier: "exact" | "related" } => x.tier !== null,
    );

  arr.sort((a, b) => {
    if (tierRank(a.tier) !== tierRank(b.tier)) return tierRank(a.tier) - tierRank(b.tier);
    const an = sessionNewKeys.has(a.job.jd_url || a.job.id) ? 0 : 1;
    const bn = sessionNewKeys.has(b.job.jd_url || b.job.id) ? 0 : 1;
    if (an !== bn) return an - bn; // 本次新发现置顶（同档内）
    return sortVal(b.job) - sortVal(a.job);
  });

  return arr.map((x) => ({ ...x.job, __tier: x.tier }));
}

// 精确层数量（用于诚实展示「精确 E + 相关 R」）。
export function countExact(
  ranked: Array<{ __tier: "exact" | "related" }>,
): number {
  return ranked.reduce((n, j) => n + (j.__tier === "exact" ? 1 : 0), 0);
}

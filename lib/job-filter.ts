// 岗位筛选 + 两层排序的纯逻辑（从 hooks/useJobFilters.ts 抽出，零行为变化）。
// 抽到 lib 层后，浏览器端筛选钩子(useJobFilters) 与 服务端搜索(lib/job-search → /api/jobs/search)
// 复用同一份匹配逻辑 → 服务端筛选结果与原前端筛选「逐字段一致」，全部既有测试照常通过。
import {
  hasExplicitRecruitmentType,
  keywordMatchTier,
  normalizeChinaCity,
  recruitmentCategory,
} from "@/lib/china-keyword-expansion";
import { classifyCompanyOriginWithSource } from "@/lib/company-origin";
import { educationMatch } from "@/lib/education-rank";
import { jobMatchesRegion } from "@/lib/job-scope";
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
  region: string;
  salaryOnly: boolean;
  sponsorshipOnly: boolean;
  education: string; // 用户所选学历（博士/硕士/本科/大专）；""=学历不限（不筛）
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
  region: "",
  salaryOnly: false,
  sponsorshipOnly: false,
  education: "",
};

// 返回岗位通过当前筛选的匹配档："exact"（精确）/ "related"（同职能相关）/ null（不匹配）。
// 城市/类型按「信息缺失不淘汰」处理：字段为空(信息未知)→ 放行但降级为 related（排序沉到精确匹配之后），
// 仅当字段【有值且明确不符】才淘汰 → 治「爬来的岗位 location/job_type 大面积为空、被硬 AND 一刀切成 0 个」。
// 公司/资本/薪资/新发现/隐藏是用户主动施加的硬条件，保持硬 AND；关键词走两层匹配，治 88% 空摘要的召回崩。
export function jobFilterTier(
  job: ScoredJob,
  filters: Filters,
): "exact" | "related" | null {
  // 因「字段缺失」而放行（非精确匹配）→ 整体降级为 related，靠排序沉到精确匹配之后。
  let degraded = false;

  if (filters.company) {
    // 大小写不敏感子串匹配：可输入"字节"命中"字节跳动"、"bytedance"命中"ByteDance"。
    const want = filters.company.trim().toLowerCase();
    if (want && !(job.company || "").toLowerCase().includes(want)) return null;
  }
  if (filters.city) {
    const location = job.location || "";
    if (!location) {
      degraded = true; // 城市未知（信息缺失 ≠ 不符合）→ 不淘汰，降级排后。
    } else {
      const normalizedCity = normalizeChinaCity(filters.city);
      if (!location.includes(filters.city) && !location.includes(normalizedCity)) {
        return null; // 明确写了别的城市 → 淘汰。
      }
    }
  }
  if (filters.jobType) {
    // 三桶分类（社招 / 校招 / 实习）精确匹配。但无类型信号的岗位会被 recruitmentCategory
    // 兜底成「社招」，据此硬筛会误杀「类型未知」岗 → 有明确信号才参与过滤，否则放行降级。
    if (hasExplicitRecruitmentType(job)) {
      if (recruitmentCategory(job) !== filters.jobType) return null; // 明确类型不符 → 淘汰。
    } else {
      degraded = true; // 类型未知 → 不淘汰，降级排后。
    }
  }
  if (filters.education) {
    // 学历门槛/资格语义（用户拍板）+「信息缺失不淘汰」，全部封装在 educationMatch（纯函数·有单测）：
    // reject=要求高于用户学历，够不着 → 淘汰；degrade=要求缺失/解析不出 → 不一刀切，降级排后。
    const verdict = educationMatch(job.education, filters.education);
    if (verdict === "reject") return null;
    if (verdict === "degrade") degraded = true;
  }
  if (filters.showNewOnly) {
    if (!job.first_seen_at) return null;
    const days = (Date.now() - new Date(job.first_seen_at).getTime()) / 86400000;
    if (days > 3) return null;
  }
  if (!filters.showIgnored && job.hidden_reason === "ignored") return null;
  if (!filters.showApplied && job.hidden_reason === "applied_by_default") return null;
  if (filters.capitalOrigin) {
    // 资本来源用「公司名名单 + 来源 adapter 兜底」综合判定：名单外的本土公司靠来源认出，
    // "外企" 才能正确踢掉它们（job.source_adapter 由服务端搜索标注；前端无则退化为纯名单）。
    const origin = classifyCompanyOriginWithSource(job.company, job.source_adapter);
    if (filters.capitalOrigin === "外企") {
      if (origin === "中国") return null;
    } else if (origin !== filters.capitalOrigin) return null;
  }
  if (filters.region && !jobMatchesRegion(job, filters.region)) return null;
  if (filters.salaryOnly && !job.salary_text) return null;
  // 「排除明确不提供 Sponsorship 的岗」：只滤掉 sponsorship_signal='none'（JD 明说不 sponsor），
  // 保留 available + unknown。因为绝大多数 JD 不会主动写「我们提供 sponsorship」(available 天然极少)，
  // 若只留 available 会把「可能给」的岗(unknown)全滤掉 → 结果恒为 0（踩过这个坑）。
  if (filters.sponsorshipOnly && job.sponsorship_signal === "none") return null;
  // 关键词两层：无关键词 → 放行；否则 精确 / 相关 / 不匹配(null)。
  // 任一字段靠「缺失放行」→ 整体压到 related，排序沉底（精确匹配优先展示）。
  if (!filters.keyword) return degraded ? "related" : "exact";
  const tier = keywordMatchTier(job, filters.keyword);
  if (tier === null) return null;
  return degraded ? "related" : tier;
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

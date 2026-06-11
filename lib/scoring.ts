import type { Job, UserPreferences, JobAction } from "./types";
import { keywordMatchTier } from "./china-keyword-expansion";

interface ScoreResult {
  score: number;
  matched_keywords: string[];
  hidden_reason: string | null;
  user_action: string | null;
}

export type MatchTierLevel = "high" | "related" | "none";

export interface MatchTier {
  level: MatchTierLevel;
  label: string | null;
}

// 把无量纲匹配分映射成可解释的三档徽标（纯展示层消费，不参与计分）。
// >= 40 → 高匹配；>= 15 → 相关；其余 → 不展示徽标（level=none）。
export function matchTier(score: number): MatchTier {
  if (score >= 40) return { level: "high", label: "高匹配" };
  if (score >= 15) return { level: "related", label: "相关" };
  return { level: "none", label: null };
}

export function scoreJob(
  job: Job,
  preferences: UserPreferences | null,
  actions: JobAction[],
): ScoreResult {
  let score = 0;
  const matched_keywords: string[] = [];
  let hidden_reason: string | null = null;
  let user_action: string | null = null;

  const title = (job.title || "").toLowerCase();
  const summary = (job.summary || "").toLowerCase();
  const location = (job.location || "").toLowerCase();
  const company = (job.company || "").toLowerCase();
  const text = `${title} ${summary}`;

  if (!preferences) {
    return { score: 0, matched_keywords: [], hidden_reason: null, user_action: null };
  }

  // target_roles 命中：用 keywordMatchTier 跨语言召回（与 Jobs 页 jobs-client 同口径），
  // 替换裸 includes——偏好填「产品经理」也能命中英文 "Product Manager" 标题，且带职能门防跨职能误召。
  for (const role of preferences.target_roles || []) {
    if (keywordMatchTier(job, role)) {
      score += 30;
      matched_keywords.push(role);
      break; // 只加一次
    }
  }

  // location 命中 target_locations
  for (const loc of preferences.target_locations || []) {
    if (location.includes(loc.toLowerCase())) {
      score += 20;
      matched_keywords.push(loc);
      break;
    }
  }

  // company 命中 target_companies
  for (const c of preferences.target_companies || []) {
    if (company.includes(c.toLowerCase())) {
      score += 15;
      matched_keywords.push(c);
      break;
    }
  }

  // target_keywords 命中：同走 keywordMatchTier 跨语言召回（与 Jobs 页同口径），替换裸 includes。
  for (const kw of preferences.target_keywords || []) {
    if (keywordMatchTier(job, kw)) {
      score += 5;
      matched_keywords.push(kw);
    }
  }

  // 7 天内新增
  if (job.first_seen_at) {
    const daysSinceFirstSeen =
      (Date.now() - new Date(job.first_seen_at).getTime()) / 86400000;
    if (daysSinceFirstSeen <= 7) {
      score += 10;
    }
  }

  // 用户操作状态只应用到当前岗位，避免一个 ignored/applied 影响整页排序。
  const primaryAction = actions
    .filter((a) => a.job_id === job.id && a.action !== "viewed")
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0];

  if (primaryAction?.action === "ignored") {
    hidden_reason = "ignored";
    user_action = "ignored";
  }

  if (primaryAction?.action === "applied") {
    hidden_reason = "applied_by_default";
    user_action = "applied";
  }

  if (primaryAction?.action === "saved") {
    user_action = "saved";
  }

  // exclude_keywords 命中 = 硬过滤（PRD 硬规则「一律不入选」），优先级最高：
  // 覆盖任何用户操作状态，由 sortAndFilterJobs 默认剔除、不受 showIgnored/showApplied 开关影响。
  for (const ek of preferences.exclude_keywords || []) {
    if (text.includes(ek.toLowerCase())) {
      hidden_reason = "excluded";
      break;
    }
  }

  return { score, matched_keywords, hidden_reason, user_action };
}

export function sortAndFilterJobs(
  jobs: Job[],
  preferences: UserPreferences | null,
  actions: JobAction[],
  options: {
    showIgnored?: boolean;
    showApplied?: boolean;
    limit?: number;
  } = {},
) {
  const scored = jobs.map((job) => {
    const result = scoreJob(job, preferences, actions);
    return {
      ...job,
      match_score: result.score,
      matched_keywords: result.matched_keywords,
      hidden_reason: result.hidden_reason,
      user_action: result.user_action,
    };
  });

  const filtered = scored.filter((job) => {
    // exclude_keywords 命中 = 硬过滤，永远剔除，不受 showIgnored/showApplied 开关影响（PRD 硬规则）。
    if (job.hidden_reason === "excluded") return false;
    if (!options.showIgnored && job.hidden_reason === "ignored") return false;
    if (!options.showApplied && job.hidden_reason === "applied_by_default")
      return false;
    return true;
  });

  filtered.sort((a, b) => b.match_score - a.match_score);

  if (options.limit) {
    return filtered.slice(0, options.limit);
  }

  return filtered;
}

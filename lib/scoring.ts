import type { Job, UserPreferences, JobAction } from "./types";
import { keywordMatchTier } from "./china-keyword-expansion";

interface ScoreResult {
  score: number;
  matched_keywords: string[];
  hidden_reason: string | null;
  user_action: string | null;
  // 相关性门信号（Today 看板硬过滤用，不参与计分/展示）：
  // content_matched = 命中任一 target_role/target_keyword/target_company（「做什么 / 哪家」）；
  // location_matched = 命中任一 target_location（「在哪座城市」）。
  content_matched: boolean;
  location_matched: boolean;
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
  let content_matched = false;
  let location_matched = false;

  const title = (job.title || "").toLowerCase();
  const summary = (job.summary || "").toLowerCase();
  const location = (job.location || "").toLowerCase();
  const company = (job.company || "").toLowerCase();
  const text = `${title} ${summary}`;

  if (!preferences) {
    return {
      score: 0,
      matched_keywords: [],
      hidden_reason: null,
      user_action: null,
      content_matched: false,
      location_matched: false,
    };
  }

  // target_roles 命中：用 keywordMatchTier 跨语言召回（与 Jobs 页 jobs-client 同口径），
  // 替换裸 includes——偏好填「产品经理」也能命中英文 "Product Manager" 标题，且带职能门防跨职能误召。
  for (const role of preferences.target_roles || []) {
    if (keywordMatchTier(job, role)) {
      score += 30;
      matched_keywords.push(role);
      content_matched = true;
      break; // 只加一次
    }
  }

  // location 命中 target_locations
  for (const loc of preferences.target_locations || []) {
    if (location.includes(loc.toLowerCase())) {
      score += 20;
      matched_keywords.push(loc);
      location_matched = true;
      break;
    }
  }

  // company 命中 target_companies
  for (const c of preferences.target_companies || []) {
    if (company.includes(c.toLowerCase())) {
      score += 15;
      matched_keywords.push(c);
      content_matched = true;
      break;
    }
  }

  // target_keywords 命中：同走 keywordMatchTier 跨语言召回（与 Jobs 页同口径），替换裸 includes。
  for (const kw of preferences.target_keywords || []) {
    if (keywordMatchTier(job, kw)) {
      score += 5;
      matched_keywords.push(kw);
      content_matched = true;
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

  return {
    score,
    matched_keywords,
    hidden_reason,
    user_action,
    content_matched,
    location_matched,
  };
}

export function sortAndFilterJobs(
  jobs: Job[],
  preferences: UserPreferences | null,
  actions: JobAction[],
  options: {
    showIgnored?: boolean;
    showApplied?: boolean;
    limit?: number;
    // 相关性硬门（Today 看板用）：用户填了职位/关键词/公司 → 必须命中其一；填了城市 → 必须命中城市。
    // 杜绝「偏好预筛不足时盲取最新岗位兜底、却只排序不过滤」导致看板被无关岗位刷屏（PRD 核心：精准 > 规模）。
    requireRelevance?: boolean;
  } = {},
) {
  const hasContentSignal =
    !!preferences &&
    (preferences.target_roles || []).length +
      (preferences.target_keywords || []).length +
      (preferences.target_companies || []).length >
      0;
  const hasLocSignal =
    !!preferences && (preferences.target_locations || []).length > 0;

  const scored = jobs.map((job) => {
    const result = scoreJob(job, preferences, actions);
    return {
      job: {
        ...job,
        match_score: result.score,
        matched_keywords: result.matched_keywords,
        hidden_reason: result.hidden_reason,
        user_action: result.user_action,
      },
      content_matched: result.content_matched,
      location_matched: result.location_matched,
    };
  });

  const filtered = scored.filter(({ job, content_matched, location_matched }) => {
    // exclude_keywords 命中 = 硬过滤，永远剔除，不受 showIgnored/showApplied 开关影响（PRD 硬规则）。
    if (job.hidden_reason === "excluded") return false;
    if (!options.showIgnored && job.hidden_reason === "ignored") return false;
    if (!options.showApplied && job.hidden_reason === "applied_by_default")
      return false;
    // 相关性门：仅当显式开启且用户有相应偏好信号时生效（城市 + 职能/关键词/公司双向治污）。
    if (options.requireRelevance) {
      if (hasContentSignal && !content_matched) return false;
      if (hasLocSignal && !location_matched) return false;
    }
    return true;
  });

  filtered.sort((a, b) => b.job.match_score - a.job.match_score);

  const out = filtered.map((x) => x.job);
  if (options.limit) {
    return out.slice(0, options.limit);
  }
  return out;
}

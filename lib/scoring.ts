import type { Job, UserPreferences, JobAction } from "./types";

interface ScoreResult {
  score: number;
  matched_keywords: string[];
  hidden_reason: string | null;
  user_action: string | null;
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

  // title 命中 target_roles
  for (const role of preferences.target_roles || []) {
    if (title.includes(role.toLowerCase())) {
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

  // keyword 命中 (title 或 summary)
  for (const kw of preferences.target_keywords || []) {
    if (text.includes(kw.toLowerCase())) {
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

  // exclude_keywords 命中
  for (const ek of preferences.exclude_keywords || []) {
    if (text.includes(ek.toLowerCase())) {
      score -= 50;
      break;
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

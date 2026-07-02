import type {
  Job,
  UserPreferences,
  JobAction,
  MatchReason,
} from "./types";
import {
  keywordMatchTier,
  classifyJobFunction,
  normalizeChinaCity,
} from "./china-keyword-expansion";
import { jobIndustryAllowed } from "./company-industry";

interface ScoreResult {
  score: number;
  matched_keywords: string[];
  match_reasons: MatchReason[];
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
  const match_reasons: MatchReason[] = [];
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
      match_reasons: [],
      hidden_reason: null,
      user_action: null,
      content_matched: false,
      location_matched: false,
    };
  }

  // 跨行业门（硬门）：用户填了目标行业、且本岗行业（公司→行业，lib/company-industry）判得出、
  // 两者不符 → 视为「职位/关键词不命中」（不给 role/keyword 命中与分），治「同职能跨行业误命中」
  // （互联网产品经理 ✗ 生物医药/消费产品经理）。行业判不出或用户没填 → 放行（不误杀）。
  // 注：公司命中（target_companies）不受此门约束——用户亲手指名的公司，行业无关紧要。
  const industryAllowed = jobIndustryAllowed(job.company, preferences.target_industries || []);
  const overseasProfile = shouldUseOverseasProfile(job, preferences);
  const keywordOptions = overseasProfile ? { includeOverseasLexicon: true } : undefined;
  const targetRoles = scoringTargetRoles(preferences, overseasProfile);
  const targetKeywords = scoringTargetKeywords(preferences, overseasProfile);

  // 岗位职能门（硬门）：用户目标职能 = 从 target_roles 里判得出的干净职能（"AI 数据产品经理"→产品；
  // 纯领域词如 "AI Agent"→其他 不计）。岗位职能判得出且不属于用户职能 → 不算命中，治「产品经理被推
  // 数据科学家 / 算法工程师」——岗位「岗位」层不符（行业-公司-岗位 三层认知的「岗位」维度）。
  // 保守放行：用户无可判职能 / 岗位职能判不出（其他）→ 不设门（不误杀）。公司命中同样豁免（见下）。
  const userFunctions = new Set<string>();
  for (const role of targetRoles) {
    const fn = classifyJobFunction({ title: role });
    if (fn && fn !== "其他") userFunctions.add(fn);
  }
  const jobFunction = classifyJobFunction(job);
  const functionAllowed =
    userFunctions.size === 0 || jobFunction === "其他" || userFunctions.has(jobFunction);

  // target_roles 命中：用 keywordMatchTier 跨语言召回（与 Jobs 页 jobs-client 同口径），
  // 替换裸 includes——偏好填「产品经理」也能命中英文 "Product Manager" 标题，且带职能门防跨职能误召。
  for (const role of targetRoles) {
    if (industryAllowed && functionAllowed && keywordMatchTier(job, role, keywordOptions)) {
      score += 30;
      matched_keywords.push(role);
      match_reasons.push({ type: "role", value: role });
      content_matched = true;
      break; // 只加一次
    }
  }

  // location 命中 target_locations
  for (const loc of preferences.target_locations || []) {
    if (locationMatchesTarget(job.location, loc)) {
      score += 20;
      matched_keywords.push(loc);
      match_reasons.push({ type: "location", value: loc });
      location_matched = true;
      break;
    }
  }

  // company 命中 target_companies
  for (const c of preferences.target_companies || []) {
    if (company.includes(c.toLowerCase())) {
      score += 15;
      matched_keywords.push(c);
      match_reasons.push({ type: "company", value: c });
      content_matched = true;
      break;
    }
  }

  // target_keywords 命中：同走 keywordMatchTier 跨语言召回（与 Jobs 页同口径），替换裸 includes。
  // 同样过跨行业门 + 职能门（与 role 一致）：跨行业 / 跨职能岗的技能命中不算数
  // （否则 PM 的 SQL/Python 会命中一切数据/研发岗，把工程师岗刷成高匹配）。
  for (const kw of targetKeywords) {
    if (industryAllowed && functionAllowed && keywordMatchTier(job, kw, keywordOptions)) {
      score += 5;
      matched_keywords.push(kw);
      match_reasons.push({ type: "keyword", value: kw });
      content_matched = true;
    }
  }

  // 7 天内新增
  if (job.first_seen_at) {
    const daysSinceFirstSeen =
      (Date.now() - new Date(job.first_seen_at).getTime()) / 86400000;
    if (daysSinceFirstSeen <= 7) {
      score += 10;
      match_reasons.push({ type: "freshness", value: "近 7 天新增" });
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
    match_reasons,
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
      (preferences.en_target_roles || []).length +
      (preferences.en_target_keywords || []).length +
      (preferences.en_skills || []).length +
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
        match_reasons: result.match_reasons,
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

function shouldUseOverseasProfile(job: Job, preferences: UserPreferences): boolean {
  const scope = preferences.job_scope || "domestic";
  if (scope === "overseas") return true;
  if (scope === "all") return job.job_scope === "overseas";
  return false;
}

function scoringTargetRoles(preferences: UserPreferences, overseasProfile: boolean): string[] {
  const base = preferences.target_roles || [];
  if (!overseasProfile) return base;
  return uniqueStrings([...(preferences.en_target_roles || []), ...base]);
}

function scoringTargetKeywords(preferences: UserPreferences, overseasProfile: boolean): string[] {
  const base = preferences.target_keywords || [];
  if (!overseasProfile) return base;
  return uniqueStrings([
    ...(preferences.en_target_keywords || []),
    ...(preferences.en_skills || []),
    ...base,
  ]);
}

function locationMatchesTarget(jobLocation: string | null | undefined, target: string): boolean {
  const rawLocation = String(jobLocation || "").trim();
  const rawTarget = String(target || "").trim();
  if (!rawLocation || !rawTarget) return false;
  if (rawLocation.toLowerCase().includes(rawTarget.toLowerCase())) return true;

  const normalizedLocation = normalizeChinaCity(rawLocation).toLowerCase();
  const normalizedTarget = normalizeChinaCity(rawTarget).toLowerCase();
  return Boolean(normalizedLocation && normalizedTarget && normalizedLocation === normalizedTarget);
}

function uniqueStrings(values: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const clean = String(value || "").trim();
    if (!clean) continue;
    const key = clean.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(clean);
  }
  return out;
}

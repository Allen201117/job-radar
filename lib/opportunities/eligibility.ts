// 匹配事实计算（computeMatchFacts）+ 硬门（checkEligibility），§6.5。
// computeMatchFacts 一次性算好所有维度，被 eligibility / scoring / 原因生成共用，杜绝口径漂移。
// 严格复用既有 matcher（keywordMatchTier / recruitmentCategory / hasExplicitRecruitmentType /
// educationMatch / jobIndustryAllowed 同源 classify / normalizeChinaCity / excludeJobs），不另造近似规则。
import type { Job } from "../types";
import type {
  RadarProfile,
  MatchFacts,
  SourceMeta,
  EligibilityResult,
  DegradedDimension,
  RejectReason,
  TriState,
  EducationLabel,
} from "./types";
import { freshnessState } from "./freshness";
import {
  keywordMatchTier,
  recruitmentCategory,
  hasExplicitRecruitmentType,
  normalizeChinaCity,
  classifyJobFunction,
} from "../china-keyword-expansion";
import { classifyCompanyIndustry, userTargetIndustryCategories, jobIndustryAllowed } from "../company-industry";
import { educationMatch } from "../education-rank";
import { excludeJobs } from "../live-search";
import { normalizeCompany } from "../company-normalize";
import { jobMatchesRegion } from "../job-scope";

export interface ActionState {
  primary: "saved" | "ignored" | "applied" | null;
  viewed: boolean;
}

// 用户「方向」职能集（筛选准确性核心）：只从**目标岗位**逐条整体分类，**不含关键词**——
// 关键词里的 "SQL/Python/数据埋点" 会把方向污染成 研发/数据，让后端/算法岗误判为方向匹配。
// 与 lib/scoring.ts 搜索路径同口径（classifyJobFunction({title: role})，跳过判不出的「其他」）。
function userTargetFunctions(profile: RadarProfile): Set<string> {
  const out = new Set<string>();
  for (const role of profile.targetRoles) {
    const fn = classifyJobFunction({ title: role });
    if (fn && fn !== "其他") out.add(fn);
  }
  return out;
}

// role+keyword 跨查询取最优 tier；exact 立即胜出，否则首个 related。
function bestRoleTier(
  job: Job,
  queries: string[],
  options: { includeOverseasLexicon?: boolean } = {},
): { tier: "exact" | "related" | null; label: string | null } {
  let label: string | null = null;
  for (const q of queries) {
    const t = keywordMatchTier(job, q, options);
    if (t === "exact") return { tier: "exact", label: q };
    if (t === "related" && label === null) label = q;
  }
  return { tier: label ? "related" : null, label };
}

function usesOverseasScope(profile: RadarProfile, job: Job): boolean {
  if (profile.jobScope === "overseas") return true;
  return profile.jobScope === "all" && job.job_scope === "overseas";
}

// 位置三态：domestic 保持旧城市 includes 口径；overseas/all 的海外岗走 country_code/targetRegions。
function locationState(job: Job, profile: RadarProfile): { state: TriState; name: string | null } {
  if (usesOverseasScope(profile, job)) {
    const regions = profile.targetRegions || [];
    if (regions.length === 0) return { state: "na", name: null };
    for (const region of regions) {
      if (jobMatchesRegion(job, region)) return { state: "match", name: region };
    }
    return { state: "mismatch", name: null };
  }

  if ((profile.jobScope || "domestic") === "domestic" && job.job_scope === "overseas") {
    return { state: "mismatch", name: null };
  }

  const targets = profile.targetLocations;
  if (targets.length === 0) return { state: "na", name: null };
  const loc = String(job.location || "");
  if (!loc) return { state: "unknown", name: null };
  for (const t of targets) {
    const norm = normalizeChinaCity(t);
    if (loc.includes(t) || (norm && loc.includes(norm))) return { state: "match", name: norm || t };
  }
  return { state: "mismatch", name: null };
}

// 招聘阶段三态：仅在用户设了阶段时参与；岗位无明确类型信号 → unknown（不一刀切）
function stageState(
  job: Job,
  userStage: string
): { state: TriState; label: "实习" | "校招" | "社招" | null } {
  if (!userStage) return { state: "na", label: null };
  if (!hasExplicitRecruitmentType(job)) return { state: "unknown", label: null };
  const cat = recruitmentCategory(job) as "实习" | "校招" | "社招";
  return cat === userStage ? { state: "match", label: cat } : { state: "mismatch", label: cat };
}

// 学历三态：educationMatch pass/degrade/reject → match/unknown/mismatch；用户无学历 → na
function educationState(job: Job, highest: EducationLabel): TriState {
  if (!highest) return "na";
  const v = educationMatch(job.education, highest);
  return v === "pass" ? "match" : v === "degrade" ? "unknown" : "mismatch";
}

// 行业三态：拒绝判定**复用权威 jobIndustryAllowed**（不另造近似拒绝逻辑）。
// jobIndustryAllowed=false 仅当「用户有目标行业 且 公司行业已知 且 不在目标内」→ mismatch（拒绝）。
// allowed 时再用同源 classify 细分 match（已知∈目标，计 +10）vs unknown（判不出，degrade）vs na（用户没填）——
// 这三者 jobIndustryAllowed 都返回 true（都不拒绝），细分只用于打分/degrade，不改变拒绝口径。
function industryState(job: Job, targetIndustries: string[]): { state: TriState; name: string | null } {
  const targets = userTargetIndustryCategories(targetIndustries) as Set<string>;
  if (targets.size === 0) return { state: "na", name: null };
  if (!jobIndustryAllowed(job.company, targetIndustries)) return { state: "mismatch", name: null };
  const cat = classifyCompanyIndustry(job.company) as string | null;
  if (!cat) return { state: "unknown", name: null };
  return { state: "match", name: cat };
}

// 目标公司命中（§10.2 normalizeCompany 后 exact equality；不再用子串把"字节"误当"字节跳动"）。
// 归一会剥「有限公司/集团/中国」等尾缀 → "字节跳动有限公司" 命中 "字节跳动"；"字节" ≠ "字节跳动" 不命中。
function companyHit(job: Job, targetCompanies: string[]): { hit: boolean; name: string | null } {
  const comp = normalizeCompany(job.company);
  if (!comp) return { hit: false, name: null };
  for (const t of targetCompanies) {
    if (normalizeCompany(t) === comp) return { hit: true, name: job.company };
  }
  return { hit: false, name: null };
}

function skillsHit(job: Job, skills: string[]): string[] {
  const hay = `${job.title || ""} ${job.summary || ""}`.toLowerCase();
  const out: string[] = [];
  for (const s of skills) {
    const k = s.trim().toLowerCase();
    if (k && hay.includes(k)) out.push(s);
  }
  return out;
}

export function computeMatchFacts(
  job: Job,
  profile: RadarProfile,
  sourceMeta: SourceMeta | undefined,
  action: ActionState,
  now: Date
): MatchFacts {
  const roleQueries = [...profile.targetRoles, ...profile.targetKeywords];
  const roleConstrained = roleQueries.length > 0;
  // 职能门：岗位职能判得出且不在用户方向集内 → 不认作方向匹配（roleTier=null → checkEligibility 按 role_mismatch 拒掉）。
  // 这样「后端/算法开发(研发)」不会因 JD 里含 AI/产品 被误标 方向匹配/高匹配。判不出(其他)或用户没填方向 → 放行（不误杀）。
  const userFns = userTargetFunctions(profile);
  const jobFn = classifyJobFunction(job);
  const functionAllowed = userFns.size === 0 || jobFn === "其他" || userFns.has(jobFn);
  const keywordOptions = usesOverseasScope(profile, job) ? { includeOverseasLexicon: true } : {};
  const role =
    roleConstrained && functionAllowed ? bestRoleTier(job, roleQueries, keywordOptions) : { tier: null as null, label: null };

  const loc = locationState(job, profile);
  const stage = stageState(job, profile.experienceStage);
  const ind = industryState(job, profile.targetIndustries);
  const company = companyHit(job, profile.targetCompanies);

  let noveltyHours: number | null = null;
  if (job.first_seen_at) {
    const t = new Date(job.first_seen_at).getTime();
    if (!Number.isNaN(t)) noveltyHours = (now.getTime() - t) / 3_600_000;
  }

  return {
    active: job.status === "active",
    summaryOk: String(job.summary || "").trim().length >= 60,
    summaryLong: String(job.summary || "").trim().length >= 200,
    sourceDisabled: sourceMeta != null && sourceMeta.enabled === false,
    excluded: excludeJobs([job], profile.excludeKeywords).length === 0,
    freshness: freshnessState(job.last_seen_at, sourceMeta?.crawl_method ?? null, now),
    roleTier: role.tier,
    roleConstrained,
    roleMatchLabel: role.label,
    companyHit: company.hit,
    companyName: company.name,
    location: loc.state,
    locationName: loc.name,
    stage: stage.state,
    stageLabel: stage.label,
    education: educationState(job, profile.highestEducation),
    industry: ind.state,
    industryName: ind.name,
    skillsHit: skillsHit(job, profile.skills),
    noveltyHours,
    userAction: action.primary,
    viewed: action.viewed,
  };
}

function reject(reason: RejectReason): EligibilityResult {
  return { eligible: false, reason };
}

// 硬门：按 §6.5 顺序返回第一个拒绝原因；unknown 维度累积为 degraded（放行但 scoring 轻罚）。
export function checkEligibility(f: MatchFacts): EligibilityResult {
  if (!f.active) return reject("inactive");
  if (!f.summaryOk) return reject("thin_summary");
  if (f.sourceDisabled) return reject("source_disabled");
  if (f.freshness === "stale" || f.freshness === "unknown") return reject("stale");
  if (f.excluded) return reject("excluded");
  if (f.userAction) return reject("already_actioned");
  if (f.roleConstrained && f.roleTier === null) return reject("role_mismatch");

  const degraded: DegradedDimension[] = [];

  if (f.location === "mismatch") return reject("location_mismatch");
  if (f.location === "unknown") degraded.push("location");

  if (f.stage === "mismatch") return reject("stage_mismatch");
  if (f.stage === "unknown") degraded.push("stage");

  if (f.education === "mismatch") return reject("education_mismatch");
  if (f.education === "unknown") degraded.push("education");

  // 命中目标公司 → 不执行行业拒绝、也不计行业 degrade（用户明确想要这家）
  if (!f.companyHit) {
    if (f.industry === "mismatch") return reject("industry_mismatch");
    if (f.industry === "unknown") degraded.push("industry");
  }

  return { eligible: true, degraded };
}

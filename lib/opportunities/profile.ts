// 合并 user_preferences + candidate_profiles → 统一 RadarProfile（§6.2），并判定画像完整度（§4.2）。
//
// 合并优先级：
//   1. 手工偏好（user_preferences）= 求职意图权威；
//   2. 简历（candidate_profiles）只补 skills / education / seniority / experience_stage 与「偏好为空」的字段；
//   3. 简历不得覆盖用户手填的 目标城市/目标岗位/目标公司/排除词；
//   4. 所有数组大小写不敏感去重；
//   5. dailyLimit clamp 5–30。
// 唯一的「合并」字段是 target_industries（偏好 ∪ 简历），其余是「偏好优先，空则简历兜底」。
import type { UserPreferences, CandidateProfile } from "../types";
import type { RadarProfile, ExperienceStage, EducationLabel } from "./types";
import { educationRank } from "../education-rank";
import { effectiveJobScope, effectiveTargetRegions } from "../job-scope";

// trim、去空、大小写不敏感去重（保留首次出现的原始大小写）
function uniqStrings(list: unknown): string[] {
  if (!Array.isArray(list)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of list) {
    if (typeof raw !== "string") continue;
    const v = raw.trim();
    if (!v) continue;
    const key = v.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(v);
  }
  return out;
}

// 偏好优先，偏好去空后为空则用简历兜底
function preferOrFallback(prefList: unknown, candList: unknown): string[] {
  const pref = uniqStrings(prefList);
  return pref.length > 0 ? pref : uniqStrings(candList);
}

function clampDailyLimit(value: unknown): number {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 20;
  return Math.max(5, Math.min(30, Math.round(n)));
}

function mapStage(value: string | null | undefined): ExperienceStage {
  if (value === "实习" || value === "校招" || value === "社招") return value;
  return "";
}

// 从简历 education[] + education_summary 推导最高学历档（无对应数据库列，按文本档位算）。
// EducationLabel 只到大专；低于大专 / 判不出 → null（学历门不卡）。
function deriveHighestEducation(candidate: CandidateProfile | null): EducationLabel {
  if (!candidate) return null;
  const texts: string[] = [];
  if (Array.isArray(candidate.education)) texts.push(...candidate.education.filter((x) => typeof x === "string"));
  if (candidate.education_summary) texts.push(candidate.education_summary);
  let best = 0;
  for (const t of texts) {
    const r = educationRank(t);
    if (typeof r === "number" && r > best) best = r;
  }
  if (best >= 6) return "博士";
  if (best === 5) return "硕士";
  if (best === 4) return "本科";
  if (best === 3) return "大专";
  return null;
}

export function buildRadarProfile(
  userId: string,
  prefs: UserPreferences | null,
  candidate: CandidateProfile | null
): RadarProfile {
  const jobScope = effectiveJobScope(prefs);
  const useEnglishProfile = (jobScope === "overseas" || jobScope === "all") && candidate?.has_en_resume === true;
  const cnRoles = preferOrFallback(prefs?.target_roles, candidate?.target_roles);
  const cnKeywords = uniqStrings(prefs?.target_keywords);
  const cnSkills = uniqStrings(candidate?.skills);
  const enRoles = preferOrFallback(candidate?.en_target_roles, cnRoles);
  const enKeywords = preferOrFallback(candidate?.en_target_keywords, cnKeywords);
  const enSkills = preferOrFallback(candidate?.en_skills, cnSkills);

  return {
    userId,
    jobScope,
    targetRegions: effectiveTargetRegions(prefs),
    targetRoles: useEnglishProfile ? enRoles : cnRoles,
    targetKeywords: useEnglishProfile ? enKeywords : cnKeywords,
    excludeKeywords: uniqStrings(prefs?.exclude_keywords),
    targetLocations: preferOrFallback(prefs?.target_locations, candidate?.target_locations),
    targetCompanies: uniqStrings(prefs?.target_companies),
    // 唯一合并字段：偏好 ∪ 简历
    targetIndustries: uniqStrings([...(prefs?.target_industries ?? []), ...(candidate?.industries ?? [])]),
    skills: useEnglishProfile ? enSkills : cnSkills,
    experienceStage: mapStage((prefs?.experience_stage ?? candidate?.experience_stage) as any),
    seniority: candidate?.seniority ?? null,
    highestEducation: deriveHighestEducation(candidate),
    dailyLimit: clampDailyLimit(prefs?.daily_limit),
  };
}

// 画像完整度（v3 §4 必改）：ready = content(roles|keywords|companies)。
// ⚠️ 城市**不再是硬门**——服务「只盯几家公司、没指定城市」的观望用户：缺城市照样 ready，
// 只是不按城市过滤、卡片标「城市未限定」。missingLocation 仅供「建议补城市」软提示、不阻断。
// 身份、强度都不参与 readiness（身份只在有岗位时做资格过滤；强度只调推荐量）。
export function profileReadiness(profile: RadarProfile): {
  ready: boolean;
  missingContent: boolean;
  missingLocation: boolean;
} {
  const hasContent =
    profile.targetRoles.length > 0 ||
    profile.targetKeywords.length > 0 ||
    profile.targetCompanies.length > 0;
  const hasLocation = profile.targetLocations.length > 0;
  return {
    ready: hasContent,
    missingContent: !hasContent,
    missingLocation: !hasLocation,
  };
}

export function isProfileReady(profile: RadarProfile): boolean {
  return profileReadiness(profile).ready;
}

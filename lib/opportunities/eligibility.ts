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
// 导出给 stage-1 召回复用（lib/jobs-store/opportunities.ts 的跨职能剪枝）：
// 召回与本文件的职能门必须用**同一套**目标职能集合，否则两端判据漂移、召回又会把
// 用不上的职能拉回来。
export function userTargetFunctions(profile: RadarProfile): Set<string> {
  const out = new Set<string>();
  for (const role of profile.targetRoles) {
    const fn = classifyJobFunction({ title: role });
    if (fn && fn !== "其他") out.add(fn);
  }
  return out;
}

interface RoleTier {
  tier: "exact" | "related" | null;
  label: string | null;
  // 命中落在标题上还是只在正文里（scoring 用它分 40/30 两档）。
  titleHit: boolean;
}

// keywordMatchTier 的匹配域有三块（见 china-keyword-expansion._jobTexts）：标题 / 公司 / 内容
// （内容 = location + job_type + summary + salary）。把不想要的那块置空再判一次，就是「命中落在哪一块」。
// ⚠️ 两个裁剪对象都必须**每个岗位只建一次、跨查询词复用**：那边的文本缓存是按行对象身份的 WeakMap，
// 每个词各克隆一次会让缓存全 miss、把标题重新归一 N 遍。
//
// 两种裁剪法是刻意分开的，别合并成一个：
//   noContentJob  → 给 roleTitleHit（40/30 分档）用，口径与 2026-09-17 上线时逐字一致，本次不动。
//   titleOnlyJob  → 给下面的职能门豁免用。豁免必须严到**只认标题**：真库实测（44 画像）宽到带公司名时，
//                   新放行的 1,700 个岗里 572 个（34%）其实是公司名里带了用户的方向词
//                   （「机械」画像 → XX机械有限公司名下全部岗位），那不是「标题写着他要的岗」。
function noContentJob(job: Job): Job {
  return { ...job, summary: null, job_type: null, salary_text: null, location: null } as Job;
}
function titleOnlyJob(job: Job): Job {
  // company 是 `string`（非空类型），置空串即可 —— _jobTexts 归一后同样得到空公司域。
  return { ...job, summary: null, job_type: null, salary_text: null, location: null, company: "" } as Job;
}

// role+keyword 跨查询取最优 tier；exact 立即胜出，否则首个 related。
function bestRoleTier(
  job: Job,
  titleJob: Job,
  queries: string[],
  options: { includeOverseasLexicon?: boolean } = {},
): RoleTier {
  let label: string | null = null;
  for (const q of queries) {
    const t = keywordMatchTier(job, q, options);
    if (t === "exact") {
      return { tier: "exact", label: q, titleHit: keywordMatchTier(titleJob, q, options) === "exact" };
    }
    if (t === "related" && label === null) label = q;
  }
  return { tier: label ? "related" : null, label, titleHit: false };
}

// 职能门拒收的岗位走这条：**只认标题字面精确命中**，一条都不看正文。
// 与 bestRoleTier 的差别是刻意的——正文里的泛词正是职能门要挡的东西，标题字面写着用户要的岗位名不是。
function titleExactRoleTier(
  titleJob: Job,
  queries: string[],
  options: { includeOverseasLexicon?: boolean } = {},
): RoleTier {
  for (const q of queries) {
    if (keywordMatchTier(titleJob, q, options) === "exact") return { tier: "exact", label: q, titleHit: true };
  }
  return { tier: null, label: null, titleHit: false };
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

// 招聘阶段三态：实习/校招用户只接受明确匹配；社招保持默认宽松。
function stageState(
  job: Job,
  userStage: string
): { state: TriState; label: "实习" | "校招" | "社招" | null } {
  if (!userStage) return { state: "na", label: null };
  const cat = recruitmentCategory(job) as "实习" | "校招" | "社招";
  // 实习/校招会自报家门：这两类求职者只接受明确匹配的岗，无明确信号(默认社招)一律排除
  if (userStage === "实习" || userStage === "校招") {
    return cat === userStage ? { state: "match", label: cat } : { state: "mismatch", label: cat };
  }
  // 社招是默认态：无明确信号的岗 unknown(放行轻罚)，避免误杀 94% 无 job_type 的岗
  if (!hasExplicitRecruitmentType(job)) return { state: "unknown", label: null };
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
  // 方向（occupation）与技能（skill）分离：方向只认**目标岗位**，技能词一律不参与方向判定。
  // 简历解析把「技能」原样灌进 target_keywords（Python / SQL / Excel / Figma），旧实现把它们
  // 与目标岗位一起当方向查询 → 真实画像实测：方向「数据分析师」的用户被推「结算专员」「管理培训生」，
  // 卡片上写着「方向匹配：Excel」。技能是求职者会什么，不是他想做什么，判不了方向。
  // 用户没填目标岗位时才回退用关键词——否则这类用户一个岗位都召不回。
  const directionQueries = profile.targetRoles.length > 0 ? profile.targetRoles : profile.targetKeywords;
  const roleConstrained = directionQueries.length > 0;
  // 关键词降级为「加分技能」（≤15 分封顶），只有在它没被当作方向查询时才并入，避免同一个词双重计分。
  const skillTerms =
    profile.targetRoles.length > 0 ? [...profile.skills, ...profile.targetKeywords] : profile.skills;
  // 职能门：岗位职能判得出且不在用户方向集内 → 正文/泛词带来的方向命中不算数
  // （roleTier=null → checkEligibility 按 role_mismatch 拒掉）。
  // 这样「后端/算法开发(研发)」不会因 JD 里含 AI/产品 被误标 方向匹配/高匹配。判不出(其他)或用户没填方向 → 放行（不误杀）。
  //
  // ⚠️ **职能门两边的口径必须对称，否则标题字面写着用户目标岗位的岗会被拒（2026-09-18 立）**：
  // 用户方向集来自 `classifyJobFunction({ title: role })` —— **只看标题**；
  // 而岗位这边 `classifyJobFunction(job)` 优先认物化列 `jobs.job_function`，那是按**标题 + 正文**算的。
  // 同一个词两把尺子，于是「仓库文员 / 办公室文员」画像（userFns={职能}）下，
  // 「客房部文员」(物化列=供应链)、「客服文员」(客服服务) 这类标题自判就是「职能」的岗全被 role_mismatch 拒掉。
  // 修法 = 物化列口径不放行时，再用**和用户侧同一个表达式**（只看标题）复判一次；两边都判不出交集才拒。
  //
  // 🚫 **不能改成「标题字面 exact 命中一律豁免职能门」**——真库 44 画像 + LLM 独立裁判实测过，代价是精度塌方：
  // 那一版比本版多放行 1,040 个岗，随机 150 条送判官 → **严格（同一具体角色）只有 48.0%、宽松 64.7%**；
  // 本版新放行的 93 条同口径是 **严格 84.4% / 宽松 95.2%**。多出来的那批集中在两个坏形态：
  // 「产品经理」→ `Product Engineering Architect` / `Product Design Engineer` / `Senior Product Engineer`，
  // 「工程」→ `销售管理工程师` / `物流工程师`（按命中词计 产品经理 241 + 工程 263，占 45%）。
  // 它们的标题命中落在**泛锚点**上（product / 工程），而标题真正的角色词（Engineer / 销售）属于
  // `GENERIC_ANCHOR_GROUP_INDEXES` 那几组、无权认领标题 ⇒ 角色簇门 `_titleRoleClusterConflict` 够不着，
  // 职能门是**唯一**拦得住它们的东西。按标题复判则两个形态都照旧拒掉（Product Engineering Architect
  // 标题自判 = 研发、销售管理工程师 = 销售，都不在各自用户的方向集里）。
  // 角色簇门本身在 keywordMatchTier 内部，两条路径都过它，没有被绕过。
  const userFns = userTargetFunctions(profile);
  const jobFn = classifyJobFunction(job);
  const functionAllowed = userFns.size === 0 || jobFn === "其他" || userFns.has(jobFn);
  // 只在物化列口径已经拒了的时候才复判（省一次分类；userFns 为空时 functionAllowed 恒真，不会走到这）。
  const titleFn = functionAllowed ? null : classifyJobFunction({ title: job.title });
  const titleFunctionAllowed = titleFn === null || titleFn === "其他" || userFns.has(titleFn);
  const keywordOptions = usesOverseasScope(profile, job) ? { includeOverseasLexicon: true } : {};
  const role: RoleTier = !roleConstrained
    ? { tier: null, label: null, titleHit: false }
    : functionAllowed
      ? bestRoleTier(job, noContentJob(job), directionQueries, keywordOptions)
      : titleFunctionAllowed
        ? titleExactRoleTier(titleOnlyJob(job), directionQueries, keywordOptions)
        : { tier: null, label: null, titleHit: false };
  const roleTitleHit = role.titleHit;

  const loc = locationState(job, profile);
  const stage = stageState(job, profile.experienceStage);
  const ind = industryState(job, profile.targetIndustries);
  const company = companyHit(job, profile.targetCompanies);

  let noveltyHours: number | null = null;
  if (job.first_seen_at) {
    const t = new Date(job.first_seen_at).getTime();
    if (!Number.isNaN(t)) noveltyHours = (now.getTime() - t) / 3_600_000;
  }

  // 正文长度优先认召回随行带回的 `summary_len`（= 库里 `char_length(btrim(summary))`，**完整**正文）。
  // 两个原因：① 召回只传 300 字截断正文，用它算「≥200 字」本来就是在算截断值；
  // ② 正文按需传之后（lib/jobs-store/opportunities.candidateSummaryExpr）职能门必拒的行 summary 为 null，
  //    若跟着判成 thin_summary，拒绝原因会从 role_mismatch 漂成 thin_summary —— 结果不变但计分板会骗人。
  // 没有这一列的调用方（Supabase 兜底 / 单测 / 洞察派生）照旧按 job.summary 现算，行为不变。
  const recalledSummaryLen = (job as unknown as { summary_len?: unknown }).summary_len;
  const summaryLen =
    typeof recalledSummaryLen === "number"
      ? recalledSummaryLen
      : String(job.summary || "").trim().length;

  return {
    active: job.status === "active",
    summaryOk: summaryLen >= 60,
    summaryLong: summaryLen >= 200,
    sourceDisabled: sourceMeta != null && sourceMeta.enabled === false,
    excluded: excludeJobs([job], profile.excludeKeywords).length === 0,
    freshness: freshnessState(job.last_seen_at, sourceMeta?.crawl_method ?? null, now),
    roleTier: role.tier,
    roleConstrained,
    roleMatchLabel: role.label,
    roleTitleHit,
    companyHit: company.hit,
    companyName: company.name,
    location: loc.state,
    locationName: loc.name,
    stage: stage.state,
    stageLabel: stage.label,
    education: educationState(job, profile.highestEducation),
    industry: ind.state,
    industryName: ind.name,
    skillsHit: skillsHit(job, skillTerms),
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

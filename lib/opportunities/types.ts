// 个人机会雷达 · 引擎类型契约（单一事实来源）
// 本文件只声明类型，无运行时行为。所有 lib/opportunities/* 模块的跨模块接口都在此固定，
// 改动这里前先想清楚对 eligibility / scoring / grouping / service 的连带影响。
//
// 注意：本目录所有模块只能用「相对 import」（"./types" / "../china-keyword-expansion"），
// 不能用 "@/..." 别名——否则 node --test 的即时转译 shim 解析不到（见 tests/opportunity-*.test.js）。

import type { Job } from "../types";

export type { Job };

// 求职阶段：空串表示用户未设定
export type ExperienceStage = "" | "实习" | "校招" | "社招";

// 最高学历档位；null = 无法判定（不卡门）
export type EducationLabel = "博士" | "硕士" | "本科" | "大专" | null;

// 合并 user_preferences（求职意图权威）+ candidate_profiles（补充字段）后的统一画像。
// 合并规则见 profile.ts：手工偏好优先，简历只补 skills/education/seniority 与缺失字段。
export interface RadarProfile {
  userId: string;
  targetRoles: string[];
  targetKeywords: string[];
  excludeKeywords: string[];
  targetLocations: string[];
  targetCompanies: string[];
  targetIndustries: string[];
  skills: string[];
  experienceStage: ExperienceStage;
  seniority: string | null;
  highestEducation: EducationLabel;
  dailyLimit: number;
}

// 岗位新鲜度状态（由 source SLA + last_seen_at 推出）
export type FreshnessState = "verified" | "aging" | "stale" | "unknown";

// 单源元信息（从 Supabase sources 批量取，freshness/eligibility 用；不访问网络）
export interface SourceMeta {
  id: string;
  company?: string | null;
  adapter_name?: string | null;
  crawl_method: string | null; // 'http' | 'playwright' | 'manual' | null
  last_checked_at?: string | null;
  enabled: boolean;
}

// 单维匹配三态 + na：
//   match    用户设了该约束且岗位命中
//   unknown  用户设了该约束但岗位该属性缺失 → 放行但记为 degraded
//   mismatch 用户设了该约束且岗位明确不符 → 硬门拒绝
//   na       用户未设该约束 → 不参与门与计分
export type TriState = "match" | "unknown" | "mismatch" | "na";

// 可被判为 degraded（信息缺失而放行）的维度
export type DegradedDimension = "location" | "stage" | "education" | "industry";

// 一次性算好的「匹配事实」，被 eligibility / scoring / 原因生成共用，避免三处重复计算导致口径漂移。
export interface MatchFacts {
  active: boolean;
  summaryOk: boolean; // summary 去空白长度 ≥60
  summaryLong: boolean; // summary 去空白长度 ≥200（计分 +5 信号）
  sourceDisabled: boolean; // source 元信息明确存在且 enabled=false
  excluded: boolean; // 命中 excludeKeywords
  freshness: FreshnessState;

  roleTier: "exact" | "related" | null; // 跨 role+keyword 取最优 keywordMatchTier
  roleConstrained: boolean; // 用户是否设了 target role / keyword
  roleMatchLabel: string | null; // 产生最优 tier 的目标词（原因展示用）

  companyHit: boolean; // 命中用户 target company（归一 exact）
  companyName: string | null; // 命中的公司展示名（原因用）

  location: TriState;
  locationName: string | null; // 命中的城市（原因用）

  stage: TriState;
  stageLabel: "实习" | "校招" | "社招" | null; // 岗位的明确阶段（原因/计分用）

  education: TriState;

  industry: TriState;
  industryName: string | null; // 命中的行业类目（原因用）

  skillsHit: string[]; // 命中的技能

  noveltyHours: number | null; // now - first_seen_at 的小时数
  userAction: "saved" | "ignored" | "applied" | null; // 主动作（不含 viewed）
  viewed: boolean;
}

export type RejectReason =
  | "inactive"
  | "thin_summary"
  | "source_disabled"
  | "stale"
  | "excluded"
  | "already_actioned"
  | "role_mismatch"
  | "location_mismatch"
  | "stage_mismatch"
  | "education_mismatch"
  | "industry_mismatch";

export type EligibilityResult =
  | { eligible: true; degraded: DegradedDimension[] }
  | { eligible: false; reason: RejectReason };

// 展示档位（内部 score → 用户档位）
export type OpportunityTier = "high" | "related" | "explore";

// 对用户展示的匹配原因（§6.7）
export type OpportunityReason =
  | { type: "role"; label: string }
  | { type: "location"; label: string }
  | { type: "company"; label: string }
  | { type: "stage"; label: string }
  | { type: "industry"; label: string }
  | { type: "skill"; label: string }
  | { type: "freshness"; label: string };

// 计分 + 原因结果
export interface ScoreResult {
  score: number; // clamp 0–100
  tier: OpportunityTier | null; // >=70 high / >=45 related / 30-44 explore / <30 null(不展示)
  reasons: OpportunityReason[];
}

// 一条进入 Feed 的机会
export interface Opportunity {
  job: Job;
  score: number;
  tier: OpportunityTier;
  reasons: OpportunityReason[];
  freshness: FreshnessState;
  firstSeenAt: string | null;
  lastSeenAt: string | null;
  userAction: "saved" | "ignored" | "applied" | null;
  viewed: boolean;
  isNew: boolean; // first_seen_at > 有效上次访问时间（由 grouping 计算填充）
  exploreEligible: boolean; // 是否够格进「拓展机会」（related 职能 或 命中目标公司），由 service 据 facts 算
}

export type FeedSurface = "today" | "email";

export interface OpportunityFeedOptions {
  now?: Date;
  noveltySinceOverride?: string | null;
  surface: FeedSurface;
}

export interface FeedSections {
  new: Opportunity[];
  priority: Opportunity[];
  explore: Opportunity[];
  aging: Opportunity[];
}

export interface FeedCounts {
  new_since_last_open: number;
  high_match: number;
  verified: number;
  aging: number;
}

// /api/opportunities 响应体（§7.1）
export interface OpportunityFeed {
  generated_at: string;
  profile_ready: boolean;
  candidate_capped: boolean;
  last_opened_at: string | null;
  counts: FeedCounts;
  sections: FeedSections;
}

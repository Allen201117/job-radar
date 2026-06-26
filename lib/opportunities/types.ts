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

// 雷达强度（v3）：手动初值 + 行为自调。只调日常推荐的量/频/门槛，不卡 readiness、不压关键提醒。
export type RadarIntensity = "active" | "passive";

// 分层核验场景（01 spec §2）：逐岗 enrich_checked_at 年龄的 SLA 叠加在 source 抓取新鲜度之上。
export type VerifyTier = "today" | "search" | "admin";

// 信号当「标签」（03/04 spec），不是入选唯一理由。
export type OpportunitySignalType =
  | "STILL_OPEN" // 最近确认仍在招（护城河外显，主力）
  | "DEADLINE_SOON" // 快截止
  | "CLOSED_OR_STALE" // 收藏/关注对象关闭或陈旧（关键提醒）
  | "CAMPUS_WINDOW" // 校招通道开放（校招季强化）
  | "NEWLY_DISCOVERED" // 我们新发现（需官方 posted_at；first_seen 污染下不可用）
  | "COMPANY_MOMENTUM"; // 公司动量（B 端/admin，不上 C 端「猛招」）

export interface OpportunitySignal {
  type: OpportunitySignalType;
  label: string; // 展示文案（受 03 spec 文案约束）
  priority: number;
  isCritical: boolean; // true=关键提醒（不受强度压制）
  evidence: {
    lastCheckedAt?: string | null; // = jobs.enrich_checked_at
    officialPostedAt?: string | null; // = jobs.posted_at（官方发布；可空）
    deadlineAt?: string | null;
    status?: string | null;
    freshness?: FreshnessState;
  };
}

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
  // v3：信号当标签（≥1）、强度、展示用的核验/官方发布/截止时间。由 service 据 signals 派生填充。
  signals: OpportunitySignal[];
  intensity: RadarIntensity;
  lastCheckedAt: string | null; // = jobs.enrich_checked_at
  officialPostedAt: string | null; // = jobs.posted_at（官方发布；可空）
  deadlineAt: string | null; // parseDeadline 出的明确截止日（可空）
}

export type FeedSurface = "today" | "email";

export interface OpportunityFeedOptions {
  now?: Date;
  noveltySinceOverride?: string | null;
  surface: FeedSurface;
  // 由调用方(route)按 resolveIntensity 算好传入；缺省 active。强度只调日常推荐，不压关键提醒。
  intensity?: RadarIntensity;
}

// v3 动态分区（按身份×强度×已触发信号生成；不是固定三模式布局）。
// 渲染顺序固定 critical→main→explore→momentum→waiting，空区不渲染 = 不同身份/强度天然不同布局。
export type SectionKey = "critical" | "main" | "explore" | "momentum" | "waiting";

export interface FeedSections {
  critical: Opportunity[]; // 关键提醒（永远置顶、不受强度压制、不被截断）
  main: Opportunity[]; // 刚核验仍在招的对口机会（STILL_OPEN 主力）
  explore: Opportunity[]; // 拓展看看（仅 active 强度）
  momentum: Opportunity[]; // 招聘动量（仅数据可信；job_events 前恒空，不上 C 端「猛招」）
  waiting: Opportunity[]; // 等待再次确认（超 today 核验时限 / aging）
}

export interface FeedCounts {
  total: number; // 全部展示卡数
  critical: number; // 关键提醒数
  main: number; // 主清单数
  by_signal: Partial<Record<OpportunitySignalType, number>>; // 按 primary signal 计数
}

// /api/opportunities 响应体（§7.1 + v3 §8.2）
export interface OpportunityFeed {
  generated_at: string;
  profile_ready: boolean;
  candidate_capped: boolean;
  last_opened_at: string | null;
  stage: ExperienceStage; // 身份（资格 + 信号侧重）
  intensity: RadarIntensity; // 强度（日常推荐的量/频/门槛）
  counts: FeedCounts;
  sections: FeedSections;
}

export interface Job {
  id: string;
  source_id: string | null;
  company: string;
  title: string;
  location: string | null;
  job_type: string | null;
  summary: string | null;
  jd_url: string;
  apply_url: string | null;
  salary_text: string | null;
  posted_at: string | null;
  experience: string | null;
  education: string | null;
  deadline: string | null;
  first_seen_at: string;
  last_seen_at: string;
  status: string;
  content_hash: string | null;
  created_at: string;
}

export interface Source {
  id: string;
  company: string;
  source_url: string;
  source_type: string | null;
  adapter_name: string | null;
  crawl_method: string;
  enabled: boolean;
  last_checked_at: string | null;
  notes: string | null;
  created_at: string;
}

export interface SourceCandidate {
  id: string;
  query: string;
  company: string | null;
  title: string | null;
  url: string;
  source_type: string | null;
  detected_platform:
    | "official_careers"
    | "greenhouse"
    | "lever"
    | "workday"
    | "ashby"
    | "smartrecruiters"
    | "unknown"
    | null;
  confidence: number | null;
  status: "pending" | "approved" | "rejected" | "parsed" | "failed";
  reason: string | null;
  created_at: string;
}

export interface UserPreferences {
  id: string;
  user_id: string;
  target_locations: string[];
  target_roles: string[];
  target_keywords: string[];
  exclude_keywords: string[];
  target_companies: string[];
  // 目标行业（跨行业门用，从简历 candidate_profiles.industries 同步而来，迁移 160）。
  // 可选：历史行/未同步用户为空，scoring 读取处一律 `|| []` 兜底。
  target_industries?: string[];
  daily_limit: number;
}

export interface ResumeUpload {
  id: string;
  user_id: string;
  file_name: string | null;
  file_type: string | null;
  file_size: number;
  raw_text: string | null;
  parsed_profile: Record<string, unknown>;
  parse_status: "parsed" | "failed";
  parse_error: string | null;
  created_at: string;
}

export interface CandidateProfile {
  user_id: string;
  resume_id: string | null;
  headline: string | null;
  target_roles: string[];
  target_locations: string[];
  skills: string[];
  industries: string[];
  seniority: string | null;
  experience_stage: string | null;
  education: string[];
  experience: string[];
  education_summary: string | null;
  experience_summary: string | null;
  raw_profile: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface JobAction {
  id: string;
  user_id: string;
  job_id: string;
  action: "viewed" | "saved" | "ignored" | "applied";
  note: string | null;
  created_at: string;
}

export interface Profile {
  id: string;
  display_name: string | null;
  role: "admin" | "user";
  created_at: string;
}

export interface CrawlRun {
  id: string;
  source_id: string | null;
  started_at: string;
  finished_at: string | null;
  status: string | null;
  jobs_found: number;
  jobs_created: number;
  jobs_updated: number;
  error_message: string | null;
}

export interface DiscoveryRun {
  id: string;
  query: string;
  city: string | null;
  company: string | null;
  job_type: string | null;
  status: string | null;
  candidates_found: number;
  candidates_parsed: number;
  candidates_pending: number;
  jobs_created: number;
  jobs_updated: number;
  blocked_count: number;
  error_message: string | null;
  created_at: string;
}

export type MatchReasonType =
  | "role"
  | "location"
  | "keyword"
  | "company"
  | "freshness";

export interface MatchReason {
  type: MatchReasonType;
  value: string;
}

export interface ScoredJob extends Job {
  match_score: number;
  matched_keywords: string[];
  match_reasons?: MatchReason[];
  hidden_reason: string | null;
  user_action: string | null;
  // 资本来源筛选用：岗位来源 adapter（搜索时由 source_id→sources.adapter_name 标注；
  // jobs/sources 跨库无法 SQL join，故在应用层注入）。缺省时国籍判定退化为纯公司名名单。
  source_adapter?: string | null;
}

// ============================================================
// 模块 B 职业洞察层（career insights）
// ============================================================

export type InsightDimension =
  | "timing"
  | "hiring"
  | "listing"
  | "compensation_intensity"
  | "path"
  | "culture";

export type InsightGrade = "fact" | "experience" | "rumor";

export type InsightStatus = "active" | "disputed" | "retired";

export type InsightSourceKind =
  | "official_filing"
  | "official_site"
  | "campus_announcement"
  | "public_aggregate"
  | "community_deidentified";

export interface CompanyProfile {
  id: string;
  company: string;
  display_name: string | null;
  aliases: string[];
  summary: string | null;
  last_verified_at: string | null;
  created_at: string;
  updated_at: string;
  // 021 行业 + 135 官方事实（T2 Wikidata 回填，均可选）
  industry?: string | null;
  founded_year?: number | null;
  headcount_band?: string | null;
  funding_stage?: string | null;
  hq_location?: string | null;
}

export interface InsightSource {
  id: string;
  url: string;
  publisher: string | null;
  source_kind: InsightSourceKind | null;
  excerpt: string | null;
  collected_at: string | null;
  deidentified: boolean;
  created_at: string;
}

export interface InsightItem {
  id: string;
  company_id: string;
  dimension: InsightDimension;
  grade: InsightGrade;
  title: string | null;
  content: string;
  sample_size: number | null;
  payload: Record<string, unknown>;
  time_window: string | null;
  valid_from: string | null;
  valid_until: string | null;
  last_verified_at: string;
  deidentified: boolean;
  status: InsightStatus;
  created_at: string;
  updated_at: string;
}

// 带溯源 + 时效标记的展示态条目
export interface InsightItemView extends InsightItem {
  sources: InsightSource[];
  outdated: boolean;
  // T1 派生层标记：true = 由自有 jobs 数据算出的事实聚合（非策展/非社区），前端用不同芯片呈现
  derived?: boolean;
}

// /api/insights 按公司聚合的响应
export interface CompanyInsightBundle {
  company: CompanyProfile;
  // 按 dimension 分组的展示态条目
  dimensions: Record<InsightDimension, InsightItemView[]>;
}

export interface InsightDispute {
  id: string;
  item_id: string;
  reporter_user_id: string | null;
  reason: string | null;
  contact: string | null;
  status: "open" | "upheld" | "rejected";
  created_at: string;
  resolved_at: string | null;
}

// ============================================================
// ③ 个性化职业路径（career path，确定性引擎）
// ============================================================

export type TimingStatusKind = "open" | "rolling" | "closed" | "unknown";

export interface CareerTimingStatus {
  status: TimingStatusKind;
  label: string; // 招聘窗口期 / 全年滚动 / 可能非窗口期 / 未知
  detail: string | null; // 对应 time_window 文本
}

export interface CareerCompanyRec {
  company: string;
  display_name: string | null;
  timing: CareerTimingStatus;
  job_count: number;
  comp_note: string | null; // 性价比一句（来自 comp 洞察）
  caution_note: string | null; // 温馨提示一句（来自 culture 洞察）
  reasons: string[]; // 排在此位的理由
}

export interface CareerNote {
  company: string;
  title: string | null;
  content: string;
}

export interface CareerPathReport {
  has_profile: boolean;
  profile_summary: {
    target_roles: string[];
    seniority: string | null;
    target_locations: string[];
  };
  is_recommended_fallback: boolean; // true=用户未设目标公司，给出的是种子推荐
  recommendations: CareerCompanyRec[];
  path_notes: CareerNote[];
  cautions: CareerNote[];
  failure_reason: "no_profile" | "insight_unverified" | null;
}

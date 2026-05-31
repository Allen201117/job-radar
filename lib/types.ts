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

export interface ScoredJob extends Job {
  match_score: number;
  matched_keywords: string[];
  hidden_reason: string | null;
  user_action: string | null;
}

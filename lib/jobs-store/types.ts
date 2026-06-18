// 自建香港 jobs 库的行类型（Phase 1，jobs-store 边界）。与 jobs-db/schema.sql 的 jobs 表列对齐。
// 复用 lib/types 的 Job 形状（app 其余代码已按它消费）；这里只声明 DB 行 → app Job 的映射点。

// jobs 表一行（pg 返回的原始列）。timestamptz 经 pg 驱动转成 JS Date 或 ISO 字符串（按列用法取用）。
export interface JobRow {
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
  first_seen_at: string | null;
  last_seen_at: string | null;
  status: string;
  content_hash: string | null;
  created_at: string | null;
  experience: string | null;
  education: string | null;
  deadline: string | null;
  enrich_fail_count: number;
  enrich_checked_at: string | null;
  canonical_jd_url: string | null;
}

// jobs 表全部可读列（select 用，避免 select *）。
export const JOB_COLUMNS =
  "id, source_id, company, title, location, job_type, summary, jd_url, apply_url, salary_text, " +
  "posted_at, first_seen_at, last_seen_at, status, content_hash, created_at, experience, " +
  "education, deadline, enrich_fail_count, enrich_checked_at, canonical_jd_url";

-- ============================================================
-- Candidate profile summary fields for resume-driven matching
-- ============================================================

alter table candidate_profiles
  add column if not exists experience_stage text,
  add column if not exists education_summary text,
  add column if not exists experience_summary text;

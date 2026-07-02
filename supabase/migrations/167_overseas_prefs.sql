-- 167_overseas_prefs.sql - overseas jobs: scope, target regions, and English profile fields.
alter table user_preferences add column if not exists job_scope text not null default 'domestic';
alter table user_preferences add column if not exists target_regions text[] not null default '{}';

alter table candidate_profiles add column if not exists target_regions text[] not null default '{}';
alter table candidate_profiles add column if not exists en_target_roles text[] not null default '{}';
alter table candidate_profiles add column if not exists en_skills text[] not null default '{}';
alter table candidate_profiles add column if not exists en_target_keywords text[] not null default '{}';
alter table candidate_profiles add column if not exists has_en_resume boolean not null default false;

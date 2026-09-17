-- 253_user_preferences_en_profile.sql
-- 英文简历画像同步到 user_preferences（修 2026-09-17 审查发现：/jobs 海外排序读不到英文画像）。
--
-- 现象：lib/types.ts 的 UserPreferences 早就声明了 en_target_roles / en_skills / en_target_keywords /
-- has_en_resume，lib/scoring.ts 也按这些字段给海外岗打分；但列只在 candidate_profiles 上（迁移 167），
-- user_preferences 从来没有 → /jobs 页与 /api/jobs/search 只读 user_preferences，海外用户上传英文简历后
-- 「按匹配度」排序与没上传完全一样，而 /today（读 candidate_profiles）已经在用它。两页各说各话。
--
-- 修法：给 user_preferences 补同名列（与迁移 202 给中文侧补 skills 列同一先例），保存英文档案时两处同写；
-- 存量用户从 candidate_profiles 回填一次。en_target_keywords 刻意回填为空：它此前是 en_skills 的副本
-- （lib/resume-en-profile.js），技能词当补充搜索词会让「用户没填英文目标岗位」时技能词被当成方向信号。
alter table user_preferences add column if not exists en_target_roles text[] not null default '{}';
alter table user_preferences add column if not exists en_skills text[] not null default '{}';
alter table user_preferences add column if not exists en_target_keywords text[] not null default '{}';
alter table user_preferences add column if not exists has_en_resume boolean not null default false;

update user_preferences p
set en_target_roles = coalesce(c.en_target_roles, '{}'),
    en_skills = coalesce(c.en_skills, '{}'),
    en_target_keywords = '{}',
    has_en_resume = true
from candidate_profiles c
where c.user_id = p.user_id
  and c.has_en_resume = true;

-- 160 — user_preferences 加 target_industries（目标行业）
-- 跨行业门用：打分时「公司→行业（lib/company-industry）∈ 用户目标行业」才算职位命中，
-- 治「同职能跨行业误命中」（互联网产品经理 ✗ 生物医药/消费产品经理）。
-- 值从简历 candidate_profiles.industries 经 app/api/resume 同步而来；用户未填则为空、门不生效（放行）。
-- Idempotent：add column if not exists，存量行默认空数组（门对其放行，不误杀）。

alter table user_preferences add column if not exists target_industries text[] default '{}';

-- 一次性回填：把已解析用户的 candidate_profiles.industries 灌进 target_industries，
-- 让跨行业门对存量用户立刻生效（否则新列默认空 → 门对所有老用户「睡着」，要等各自重新解析简历才激活）。
-- 仅填「目标行业为空 且 简历有行业」的用户，不覆盖用户后续手动所填；幂等（再跑只补仍为空的）。
update user_preferences up
set target_industries = cp.industries
from candidate_profiles cp
where cp.user_id = up.user_id
  and coalesce(array_length(up.target_industries, 1), 0) = 0
  and coalesce(array_length(cp.industries, 1), 0) > 0;

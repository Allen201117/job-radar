-- 公开讨论说法层新增「薪资水平」主题。
-- 必须完整重建 209 的枚举：CHECK 不是增量约束，遗漏任一旧值都会让既有行无法通过校验。

begin;

alter table insight_items drop constraint if exists insight_items_metric_key_check;
alter table insight_items
  add constraint insight_items_metric_key_check
  check (metric_key is null or metric_key in (
    'headcount_total', 'headcount_tech_ratio', 'edu_bachelor_plus_ratio', 'edu_master_plus_ratio',
    'bu_count', 'bu_job_count',
    'hiring_volume_30d', 'hiring_trend_30d_pct', 'hiring_trend_90d_pct', 'open_age_days_median',
    'city_share', 'function_share', 'bucket_share',
    'exp_years_median', 'edu_requirement_mode',
    'avg_comp_annual', 'salary_range_k', 'bonus_months',
    'overtime_level', 'promotion_pace', 'interview_rounds',
    'intern_experience',
    'work_culture',
    'hiring_freeze_signal', 'layoff_mention',
    'listing_status', 'revenue_yoy',
    'pay_level'
  ));

commit;

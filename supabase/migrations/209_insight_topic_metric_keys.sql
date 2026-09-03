-- 把「说法」层归类：给公开讨论型洞察补上 metric_key
--
-- 背景（2026-09-03 创始人定调）：洞察库不放「数据层」——城市分布、学历要求这类
-- 用户自己在岗位库筛一下就有，不算信息差。用户要的是**别人的经验感受**：
-- 年终奖、加班强度、面试难度、晋升节奏、实习体验、裁员稳定性。
--
-- 但线上实测：这 5,949 条「说法」里 metric_key **非空的是 0 条**——
-- 全是自由文本散文，没法索引、没法筛选、没法跨公司比较。
-- 迁移 204 把指标枚举化了，可惜只有派生层在用；真正值钱的那层一条都没归。
-- 这条迁移是补课：先把**主题**归好（确定性映射，零 LLM 成本），
-- 数值（几个月 / 几轮 / 档位）由后续抽取任务写 metric_value。

begin;

set local statement_timeout = '60s';

-- 1) 枚举补两个：实习体验没有对应 key；另留一个泛化主题给「公开讨论·群体印象」这类无主题条目。
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
    -- 2026-09-03 新增：说法层的主题键
    'intern_experience',   -- 实习体验（1,108 条）
    'work_culture',        -- 无明确主题的公开讨论（251 条），避免它们变成不可筛的黑洞
    'hiring_freeze_signal', 'layoff_mention',
    'listing_status', 'revenue_yoy'
  ));

-- 2) 按 T3 写入时的标题主题做确定性回填。
--    标题形态由 crawler/insight_backlog.py 的 T3_TOPIC_CATALOG 决定（「{主题} · 群体印象」），
--    所以这是一一对应的映射，不需要 LLM，也不会误判。
--    ⚠️ 只回填 origin='public_web' 且 metric_key 为空的行：不碰官方事实与派生条目。
update insight_items set metric_key = case
    when title like '年终奖%'     then 'bonus_months'
    when title like '加班文化%'   then 'overtime_level'
    when title like '面试难度%'   then 'interview_rounds'
    when title like '晋升发展%'   then 'promotion_pace'
    when title like '实习体验%'   then 'intern_experience'
    when title like '裁员稳定性%' then 'layoff_mention'
    when title like '公开讨论%'   then 'work_culture'
  end
where origin = 'public_web'
  and metric_key is null
  and (
    title like '年终奖%' or title like '加班文化%' or title like '面试难度%'
    or title like '晋升发展%' or title like '实习体验%' or title like '裁员稳定性%'
    or title like '公开讨论%'
  );

-- 3) 官方上市/股票事实：同样归一个 key，好让「有上市信息的公司」可筛。
update insight_items set metric_key = 'listing_status'
where metric_key is null
  and dimension = 'listing'
  and origin in ('official', 'official_filing', 'wikidata', 'manual');

commit;

-- 上线后校验：说法层还有多少条没归类（应当只剩人工录入的零星条目）
-- select count(*) from insight_items
-- where origin = 'public_web' and status = 'active' and metric_key is null;

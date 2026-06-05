-- ============================================================
-- 023 — 职业洞察新增第五维度 listing（上市状态 / 股票 / 即将上市）
-- ============================================================
-- 需求：洞察增加「该公司是否上市、近期股价、未上市 / 即将上市是否适合投递」这类参考项。
-- 设计（遵守数据质量优先级，不编造易过时的具体股价）：
--   - listing 维度仍走统一 schema + 校验门（fact 须带来源 / 去标识 / 时效）。
--   - 易变的「近期行情」不落库为具体数字，改为在 payload.quote_url 存一个公开行情页链接，
--     正文只陈述**稳定事实**：上市/未上市/已递表/计划上市 + 交易所 + 代码 + 上市日。
-- payload 约定（jsonb）：
--   { status: 'listed'|'pre_ipo'|'filed'|'private', exchange, ticker, ipo_date, quote_url }
--   status: listed=已上市 / filed=已递交招股书 / pre_ipo=筹备上市 / private=未上市暂无计划

alter table insight_items drop constraint if exists insight_items_dimension_check;

alter table insight_items
  add constraint insight_items_dimension_check
  check (dimension in (
    'timing', 'compensation_intensity', 'path', 'culture', 'listing'
  ));

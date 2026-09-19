-- 让「按设计刹停」（RepetitionBrake 判定批量门店同质岗）与「真漏抓」在 crawl_runs 里能分开算。
--
-- 背景：规则 G（ops_watchdog）只读 reported_total/coverage_complete 判「漏抓缺口」，
-- 而 RepetitionBrake 刹停的源（如物美超市——753 行归一后只剩 84 种角色，89% 重复）
-- fetch_complete 天然为 False（CLAUDE.md §3 立的不变量，list-absence 探活要靠它），
-- 与「我们自己的分页/上限 bug 真漏抓」在 crawl_runs 里长得一模一样，会被规则 G 混进同一堆
-- 「缺口」里，误导人去重新抬上限（抬了也没用，刹车会再次刹停，且违反「精准 > 规模」）。
--
-- coverage_stop_reason 只在 adapter 的刹停原因**可判定**时才写（RepetitionBrake 触发 →
-- 'repetition_brake'）；正常抓全 / 真撞上限 / 撞安全翻页上限等都不写（NULL），
-- 不影响 fetch_complete/reported_total 语义、不改规则 G 的任何阈值常量。
alter table crawl_runs
  add column if not exists coverage_stop_reason text;

comment on column crawl_runs.coverage_stop_reason is
  '抓取在未抓全时为何提前停止（可判定时才写，NULL=未知/未触发已知刹车）。'
  '当前唯一取值 repetition_brake = RepetitionBrake 判定为「同一岗位 × N 家门店」批量发布、'
  '按设计刹停翻页（CLAUDE.md「列表抓取上限」一节），供覆盖率看板与 ops_watchdog 规则 G '
  '把「按设计刹停」从「漏抓缺口」里摘出来单列，不再混进同一个告警。';

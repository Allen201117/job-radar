-- 抓全率可观测（阶段①）：抓取日志记录「官网自报总数」与「是否抓全」，
-- 让全库覆盖率（fetched ÷ reported_total）可持续监控、成时间序列（每源每次抓取一行）。
alter table crawl_runs
  add column if not exists reported_total int,
  add column if not exists coverage_complete boolean;

comment on column crawl_runs.reported_total is
  '官网接口本次自报的岗位总数（覆盖率分母）。每次抓取当场读取，天然跟随官网实时变化；NULL=接口无此字段/纯HTML源/不可测。';
comment on column crawl_runs.coverage_complete is
  '本次抓取是否抓到了 reported_total 的全部（fetched>=total 或按接口翻完）。NULL=不可判定。';

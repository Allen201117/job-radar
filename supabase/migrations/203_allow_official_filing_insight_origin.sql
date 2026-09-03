-- 年报 T2 官方披露事实以 official_filing 标识来源层，和 insight_sources.source_kind 对齐。
alter table insight_items drop constraint if exists insight_items_origin_check;
alter table insight_items
  add constraint insight_items_origin_check
  check (origin in ('derived', 'wikidata', 'official', 'official_filing', 'public_web', 'manual'));

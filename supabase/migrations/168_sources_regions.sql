-- 168_sources_regions.sql - source-level crawl regions, defaulting to greater China.
alter table sources add column if not exists regions text[] not null default '{CN}';

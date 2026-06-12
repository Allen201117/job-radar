-- ============================================================
-- 140 — 中文 bigram 全文检索：让「北京产品经理」等中文关键词搜索走索引、秒出、近全量召回
-- ============================================================
-- 背景：中文岗位词多为 2 字(产品/北京)，ilike '%词%' 上 pg_trgm 几乎无选择性(单页 6s)，
-- 「扫最新窗口」又召回不全(北京产品 110/真实1094)。正解 = 中文双字(bigram)分词的 tsvector + GIN 索引。
-- 设计：把 title/summary/company/location/job_type 拼起来，按「空白切词→每词相邻双字」生成 bigram 串，
--       存 to_tsvector('simple', bigrams) 于 search_bigrams 列(GIN 索引)。查询时把关键词同样 bigram 成 tsquery，
--       @@ 命中 ≈ 子串命中(超集)；最终精筛仍由 lib/job-filter 的 jobFilterTier 在 JS 做(口径零变化)。
-- 上线策略(避免给 10万行表加列时的长锁冻站)：本迁移只加「函数+可空列+GIN+触发器+批量回填RPC」(均轻量)，
--   存量由 scripts/backfill-search-bigrams.js 调 RPC 分批回填(行级锁、不挡读)；新数据由触发器自动维护。
-- 幂等；push 后由 migrate.yml 自动应用。

-- 1) bigram 分词器：小写→按空白切词→每词生成相邻双字(单字词原样保留)。immutable，供生成/触发器/查询同口径。
create or replace function chinese_bigrams(t text) returns text as $$
declare
  tok text;
  res text := '';
  i int;
  n int;
begin
  foreach tok in array regexp_split_to_array(lower(coalesce(t, '')), '\s+')
  loop
    n := char_length(tok);
    if n = 0 then
      continue;
    elsif n = 1 then
      res := res || ' ' || tok;
    else
      for i in 1 .. n - 1 loop
        res := res || ' ' || substr(tok, i, 2);
      end loop;
    end if;
  end loop;
  return btrim(res);
end;
$$ language plpgsql immutable;

-- 2) 可空 tsvector 列 + GIN 索引（空列上建索引是瞬时的；回填时增量维护）。
alter table jobs add column if not exists search_bigrams tsvector;
create index if not exists jobs_search_bigrams_gin on jobs using gin (search_bigrams);

-- 3) 触发器：插入/更新检索相关字段时自动重算 search_bigrams（新数据无需爬虫改动）。
create or replace function jobs_set_search_bigrams() returns trigger as $$
begin
  new.search_bigrams := to_tsvector('simple', chinese_bigrams(
    coalesce(new.title,'') || ' ' || coalesce(new.summary,'') || ' ' ||
    coalesce(new.company,'') || ' ' || coalesce(new.location,'') || ' ' || coalesce(new.job_type,'')
  ));
  return new;
end;
$$ language plpgsql;

drop trigger if exists jobs_search_bigrams_trg on jobs;
create trigger jobs_search_bigrams_trg
  before insert or update of title, summary, company, location, job_type on jobs
  for each row execute function jobs_set_search_bigrams();

-- 4) 批量回填 RPC（service_role 调用；行级锁 + skip locked，不挡读、不一次性长锁）。返回本批回填行数，0 即完成。
create or replace function backfill_search_bigrams(batch int default 2000) returns int as $$
declare
  updated int;
begin
  with cte as (
    select id from jobs where search_bigrams is null limit batch for update skip locked
  )
  update jobs j set search_bigrams = to_tsvector('simple', chinese_bigrams(
    coalesce(j.title,'') || ' ' || coalesce(j.summary,'') || ' ' ||
    coalesce(j.company,'') || ' ' || coalesce(j.location,'') || ' ' || coalesce(j.job_type,'')
  ))
  from cte where j.id = cte.id;
  get diagnostics updated = row_count;
  return updated;
end;
$$ language plpgsql;

grant execute on function backfill_search_bigrams(int) to service_role;

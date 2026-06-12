-- ============================================================
-- 142 — 搜索 v2：title/header 锚定的「双语」检索列 search_doc，修「略过英文标题岗」+「搜索慢」
-- ============================================================
-- 旧 search_bigrams 两个毛病：① 把 title+summary 全文 bigram → 关键词命中摘要里的提及 → 候选≈结果的3.5倍 → 慢；
--   ② 全 bigram → 拉丁 2 字 bigram(pr/od)posting 巨大拖慢4x，只能丢英文词 → 漏英文标题岗。
-- v2 治法（业界多语检索通用法：标题锚定 + 按脚本分词）：
--   · 只索引短字段 title+company+location+job_type（**不含 summary**）→ 候选紧≈结果 → 快。
--   · search_tokens：CJK 出「相邻双字 bigram」(中文子串)，纯拉丁/数字出「整词」(英文标题选择性好、不爆)。
--     → 「产品」查询经同义词扩展含 product/manager 整词 → 命中英文 "Product Manager" 标题。
-- 取舍：丢「正文里才提到角色」的少量召回(泛标题岗)；这类多为噪声(旧职能门本就在过滤)。
-- 用新列 search_doc(从空回填,一遍过,无需先 null 旧列)，并清掉旧 search_bigrams。幂等；push 自动应用。

-- 双语分词器：小写→截断前4000字→按空白切词；纯拉丁/数字词出整词，含 CJK 的词出相邻双字。immutable(查询/触发器/回填同口径)。
create or replace function search_tokens(t text) returns text as $$
declare
  tok text;
  res text := '';
  i int;
  n int;
begin
  foreach tok in array regexp_split_to_array(left(lower(coalesce(t, '')), 4000), '\s+')
  loop
    n := char_length(tok);
    if n = 0 then
      continue;
    elsif tok ~ '^[a-z0-9]+$' then
      res := res || ' ' || tok;          -- 纯拉丁/数字：整词
    elsif n = 1 then
      res := res || ' ' || tok;
    else
      for i in 1 .. n - 1 loop
        res := res || ' ' || substr(tok, i, 2);  -- 含 CJK：相邻双字
      end loop;
    end if;
  end loop;
  return btrim(res);
end;
$$ language plpgsql immutable;

alter table jobs add column if not exists search_doc tsvector;
create index if not exists jobs_search_doc_gin on jobs using gin (search_doc);

create or replace function jobs_set_search_doc() returns trigger as $$
begin
  new.search_doc := to_tsvector('simple', search_tokens(
    coalesce(new.title,'') || ' ' || coalesce(new.company,'') || ' ' ||
    coalesce(new.location,'') || ' ' || coalesce(new.job_type,'')
  ));
  return new;
end;
$$ language plpgsql;

drop trigger if exists jobs_search_doc_trg on jobs;
create trigger jobs_search_doc_trg
  before insert or update of title, company, location, job_type on jobs
  for each row execute function jobs_set_search_doc();

-- 回填 RPC（短字段→batch 可大；函数级 180s 超时防个别长字段批次被砍）。
create or replace function backfill_search_doc(batch int default 3000) returns int
language plpgsql
set statement_timeout = '180s'
as $$
declare
  updated int;
begin
  with cte as (
    select id from jobs where search_doc is null limit batch for update skip locked
  )
  update jobs j set search_doc = to_tsvector('simple', search_tokens(
    coalesce(j.title,'') || ' ' || coalesce(j.company,'') || ' ' ||
    coalesce(j.location,'') || ' ' || coalesce(j.job_type,'')
  ))
  from cte where j.id = cte.id;
  get diagnostics updated = row_count;
  return updated;
end;
$$;
grant execute on function backfill_search_doc(int) to service_role;

-- 清理旧 search_bigrams（不再用；省爬虫 upsert 写开销 + 索引空间）。
drop trigger if exists jobs_search_bigrams_trg on jobs;
drop index if exists jobs_search_bigrams_gin;
alter table jobs drop column if exists search_bigrams;

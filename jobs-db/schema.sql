-- 求职雷达 Phase 1：自建香港 PostgreSQL 17 的 jobs 热表 schema。
-- 从 Supabase 生产库(PG17.6) pg_dump 忠实重建：列 / 约束 / canonical 触发器 / count 函数 / btree 索引
-- 全部与线上一致。crawler 继续从 Supabase 读 sources/写 crawl_runs，只把 **jobs 读写** 切到这里。
--
-- 搜索：忠实复刻生产的**中文 bigram FTS**（search_doc + search_tokens + jobs_set_search_doc 触发器 +
--   jobs_search_doc_gin），与 lib/job-search.ts 同口径，零召回回归；另留 pg_trgm GIN 辅助 ad-hoc ILIKE。
--   search_doc 值已随数据迁移带过来（163k 行已填充），新写入由触发器维护。
--
-- 幂等：全部 IF NOT EXISTS / OR REPLACE，可重复 apply（jobs-db-migrate.yml）。
-- gen_random_uuid() 是 PG13+ 核心函数，无需扩展。

create extension if not exists pg_trgm;

create table if not exists jobs (
  id                uuid primary key default gen_random_uuid(),
  source_id         uuid,
  company           text not null,
  title             text not null,
  location          text,
  job_type          text,
  summary           text,
  jd_url            text not null,
  apply_url         text,
  salary_text       text,
  posted_at         timestamptz,
  first_seen_at     timestamptz default now(),
  last_seen_at      timestamptz default now(),
  status            text default 'active' check (status in ('active','removed','expired','error')),
  content_hash      text,
  created_at        timestamptz default now(),
  experience        text,
  education         text,
  deadline          text,
  enrich_fail_count integer not null default 0,
  enrich_checked_at timestamptz,
  search_doc        tsvector,   -- 保留列；v1 不填（FTS 后置 pass 再启用）
  canonical_jd_url  text,
  constraint jobs_company_title_location_jd_url_key unique (company, title, location, jd_url)
);

-- ── canonical_jd_url 归一（与 lib/canonical-url.js / crawler/normalizer.py / 迁移144 字节级一致；改一处必同改）──
create or replace function canonicalize_jd_url(u text)
returns text language plpgsql immutable as $function$
declare
  s text;
  base text;
  query text;
  qpos int;
  part text;
  k text;
  kept text[] := array[]::text[];
begin
  if u is null then
    return null;
  end if;
  s := btrim(u);
  if s = '' then
    return s;
  end if;
  if position('#' in s) > 0 then       -- SPA hash 路由保守不动
    return s;
  end if;
  qpos := position('?' in s);
  if qpos > 0 then
    base := substr(s, 1, qpos - 1);
    query := substr(s, qpos + 1);
  else
    base := s;
    query := '';
  end if;
  if query <> '' then
    foreach part in array string_to_array(query, '&') loop
      if part = '' then
        continue;
      end if;
      k := lower(split_part(part, '=', 1));
      if left(k, 4) = 'utm_' then
        continue;
      end if;
      if k in ('spm','scm','bd_vid','gclid','fbclid','msclkid','yclid',
               'hmsr','hmpl','hmcu','hmkw','hmci','_ga','gio_link_id') then
        continue;
      end if;
      kept := array_append(kept, part);
    end loop;
    query := array_to_string(kept, '&');
  end if;
  base := regexp_replace(base, '/+$', '');
  if query <> '' then
    return base || '?' || query;
  else
    return base;
  end if;
end;
$function$;

create or replace function jobs_set_canonical_jd_url()
returns trigger language plpgsql as $function$
begin
  -- schema 限定：数据迁移(pg_dump 把 search_path 置空)时 COPY 触发本函数，非限定调用会找不到函数。
  new.canonical_jd_url := public.canonicalize_jd_url(new.jd_url);
  return new;
end;
$function$;

drop trigger if exists jobs_canonical_jd_url_trg on jobs;
create trigger jobs_canonical_jd_url_trg
  before insert or update of jd_url on jobs
  for each row execute function jobs_set_canonical_jd_url();

-- ── 中文 bigram 全文检索（search_doc）：从生产忠实重建，与 lib/job-search.ts 的 queryTokens 同口径。
--   迁移已带过 search_doc 值（163k 行已填充）；这里补 tokenizer + 触发器（新写入维护）+ GIN 索引。
create or replace function search_tokens(t text)
returns text language plpgsql immutable as $function$
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
$function$;

create or replace function jobs_set_search_doc()
returns trigger language plpgsql as $function$
begin
  -- schema 限定 public.search_tokens：COPY/迁移时 search_path 可能为空。
  new.search_doc := to_tsvector('simple', public.search_tokens(
    coalesce(new.title,'') || ' ' || coalesce(new.company,'') || ' ' ||
    coalesce(new.location,'') || ' ' || coalesce(new.job_type,'')
  ));
  return new;
end;
$function$;

drop trigger if exists jobs_search_doc_trg on jobs;
create trigger jobs_search_doc_trg
  before insert or update of title, company, location, job_type on jobs
  for each row execute function jobs_set_search_doc();

-- ── 「有效在招」诚实计数（active + 有 JD 正文 ≥60 字）──
create or replace function count_valid_active_jobs()
returns bigint language sql stable as $function$
  select count(*)::bigint
  from public.jobs
  where status = 'active'
    and summary is not null
    and char_length(btrim(summary)) >= 60;
$function$;

-- ── 搜索/公司面板读用 RPC（从生产忠实重建；app jobs-store 用 select * from fn() 调）──
create or replace function active_companies()
returns table(company text) language sql stable
set search_path to 'public' as $function$
  select j.company
  from public.jobs j
  where j.status = 'active' and j.company is not null and j.company <> ''
  group by j.company
  order by j.company
$function$;

create or replace function active_job_counts_by_company()
returns table(company text, job_count integer) language sql stable
set search_path to 'public' as $function$
  select j.company, count(*)::int as job_count
  from public.jobs j
  where j.status = 'active' and j.company is not null and j.company <> ''
  group by j.company
$function$;

-- ── 索引（btree，从生产忠实重建）──
-- 注：原 idx_jobs_enrich_queue(first_seen 前导) / idx_jobs_first_seen(裸) / jobs_source_id_idx(裸) 已于
-- 2026-06-20 下架——生产实测 0 次 idx_scan，分别被 jobs_enrich_queue_by_source_idx(source_id 前导,
-- 迁移150)/ jobs_status_first_seen_idx(status,first_seen 复合)/ 部分 source 前导索引完全覆盖（裸索引列序更差，
-- planner 不选）。省每次 upsert 的索引维护。若查询形态变化可按需重建。
create index if not exists idx_jobs_company                 on jobs (company);
create index if not exists idx_jobs_status                  on jobs (status);
create index if not exists jobs_active_company_idx          on jobs (company) where status = 'active';
create index if not exists jobs_active_liveness_by_source_idx on jobs (source_id, enrich_checked_at nulls first) where status = 'active';
create index if not exists jobs_canonical_jd_url_idx        on jobs (canonical_jd_url);
create unique index if not exists jobs_canonical_jd_url_active_uniq on jobs (canonical_jd_url) where status = 'active';
create index if not exists jobs_enrich_queue_by_source_idx  on jobs (source_id, first_seen_at desc) where status = 'active' and summary is null and enrich_fail_count < 3;
create index if not exists jobs_status_first_seen_idx       on jobs (status, first_seen_at desc);
create index if not exists jobs_valid_active_idx            on jobs (id) where status = 'active' and summary is not null and char_length(btrim(summary)) >= 60;

-- ── 中文 bigram 全文检索 GIN（search_doc）：app 搜索主路径（lib/jobs-store/search.ts 的 textSearch）──
create index if not exists jobs_search_doc_gin on jobs using gin (search_doc);

-- 注：原 jobs_title_trgm_idx / jobs_company_trgm_idx（pg_trgm GIN，title/company ILIKE 辅助）已于
-- 2026-06-20 下架——生产实测 5 天 0 次 idx_scan（搜索的 ilike 都在 FTS 收窄后的小集合上过滤、用不到它们），
-- 白吃每次 upsert 的 GIN 维护开销 + 36MB 缓存。pg_trgm 扩展保留；若未来有全表 ILIKE 热查询可按需重建。

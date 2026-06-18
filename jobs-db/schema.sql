-- 求职雷达 Phase 1：自建香港 PostgreSQL 17 的 jobs 热表 schema。
-- 从 Supabase 生产库(PG17.6) pg_dump 忠实重建：列 / 约束 / canonical 触发器 / count 函数 / btree 索引
-- 全部与线上一致。crawler 继续从 Supabase 读 sources/写 crawl_runs，只把 **jobs 读写** 切到这里。
--
-- 搜索：v1 用 pg_trgm 的 GIN 索引做 ILIKE 子串检索（自足、够快），**不搬**自定义 bigram FTS
--   (search_doc / search_tokens / jobs_set_search_doc / jobs_search_doc_gin) —— 那套留作后置性能 pass。
--   search_doc 列保留（faithful，v1 不填）。对齐 docs/superpowers/plans/2026-06-14-jobs-database-refactor.md。
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
create index if not exists idx_jobs_company                 on jobs (company);
create index if not exists idx_jobs_enrich_queue            on jobs (first_seen_at desc) where status = 'active' and summary is null and enrich_fail_count < 3;
create index if not exists idx_jobs_first_seen              on jobs (first_seen_at desc);
create index if not exists idx_jobs_status                  on jobs (status);
create index if not exists jobs_active_company_idx          on jobs (company) where status = 'active';
create index if not exists jobs_active_liveness_by_source_idx on jobs (source_id, enrich_checked_at nulls first) where status = 'active';
create index if not exists jobs_canonical_jd_url_idx        on jobs (canonical_jd_url);
create unique index if not exists jobs_canonical_jd_url_active_uniq on jobs (canonical_jd_url) where status = 'active';
create index if not exists jobs_enrich_queue_by_source_idx  on jobs (source_id, first_seen_at desc) where status = 'active' and summary is null and enrich_fail_count < 3;
create index if not exists jobs_source_id_idx               on jobs (source_id);
create index if not exists jobs_status_first_seen_idx       on jobs (status, first_seen_at desc);
create index if not exists jobs_valid_active_idx            on jobs (id) where status = 'active' and summary is not null and char_length(btrim(summary)) >= 60;

-- ── v1 搜索：pg_trgm GIN（title/company 快速 ILIKE 子串检索，替代 bigram FTS）──
create index if not exists jobs_title_trgm_idx   on jobs using gin (title gin_trgm_ops);
create index if not exists jobs_company_trgm_idx on jobs using gin (company gin_trgm_ops);

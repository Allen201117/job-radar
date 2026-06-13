-- ============================================================
-- 144 — jobs 唯一性下沉到 DB：canonical_jd_url + active partial unique index
-- ============================================================
-- 背景：001_init 的 unique(company,title,location,jd_url) 受 nullable location 影响形同虚设
--   （Postgres 里 NULL≠NULL，空 location 的同岗不去重）。去重一直只靠应用层 crawler/db.py
--   先查后写兜底，DB 层无硬保证「同一岗位链接不重复」。本迁移把唯一性下沉到 DB。
--
-- 设计：
--   1) canonicalize_jd_url(text)：把链接变体（utm_*/spm 等 tracking 参数、尾斜杠）归一到同一把键；
--      含 '#'(SPA hash 路由 Moka/北森/飞书/携程) → 整串原样返回，绝不动 fragment（岗位身份在 fragment 里）。
--      ⚠️ 与 lib/canonical-url.js / crawler/normalizer.py 的 canonicalize_jd_url 逐字一致
--      （tests/canonical-url.test.js + crawler/test_canonical.py 两套测试守着）。
--   2) 可空列 canonical_jd_url + 回填 + before-insert/update 触发器（新数据自动维护，所有写入端零改动）。
--   3) 上唯一约束前先 dedup active 重复（每 canonical 保留最新一行，其余降级 removed）——
--      否则存量有重复时 CREATE UNIQUE INDEX 会失败，并永久阻塞此后所有迁移。
--   4) full btree 索引（服务 crawler 跨状态 .eq(canonical_jd_url) 查找）+ active partial unique index（硬约束）。
--
-- 全程单事务（db-migrate.sh 用 -1 应用）：任一步失败整体回滚，不会留半成品。幂等；push 自动应用。

-- 0) 抬高本事务 statement_timeout：全表回填(2b 对每行调函数)+dedup+建唯一索引在 10万级 jobs 上
--    会超过 Supabase 默认 statement_timeout(实测 ~2min 被强杀)。set local 仅本迁移事务内生效，
--    提交即恢复，不影响全局/其他会话。
set local statement_timeout = '1800s';

-- 1) 归一函数（immutable，供回填/触发器/审计同口径）。
create or replace function canonicalize_jd_url(u text) returns text as $$
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
$$ language plpgsql immutable;

-- 2a) 可空列（空列瞬时，不长锁）。
alter table jobs add column if not exists canonical_jd_url text;

-- 2b) 回填存量（此时触发器尚未建，不会重复触发；jd_url NOT NULL → canonical 必非空）。
update jobs set canonical_jd_url = canonicalize_jd_url(jd_url) where canonical_jd_url is null;

-- 2c) 触发器：插入/改 jd_url 时自动维护 canonical_jd_url（爬虫/JS/直写各端零改动）。
create or replace function jobs_set_canonical_jd_url() returns trigger as $$
begin
  new.canonical_jd_url := canonicalize_jd_url(new.jd_url);
  return new;
end;
$$ language plpgsql;

drop trigger if exists jobs_canonical_jd_url_trg on jobs;
create trigger jobs_canonical_jd_url_trg
  before insert or update of jd_url on jobs
  for each row execute function jobs_set_canonical_jd_url();

-- 3) 上唯一约束前 dedup：每 canonical 在 active 里保留最新一行（last_seen_at→first_seen_at→id），其余降级 removed。
--    降级而非删除：保住 job_actions 对历史行的外键（用户的收藏/投递记录不丢）。
with ranked as (
  select id, row_number() over (
    partition by canonical_jd_url
    order by last_seen_at desc nulls last, first_seen_at desc nulls last, id desc
  ) as rn
  from jobs
  where status = 'active'
)
update jobs set status = 'removed'
where id in (select id from ranked where rn > 1);

-- 4a) full btree：服务 crawler 跨状态按 canonical 查既有行（含 removed/expired，用于回填/复活）。
create index if not exists jobs_canonical_jd_url_idx on jobs (canonical_jd_url);

-- 4b) active partial unique index：DB 层硬保证「同一岗位链接在 active 里唯一」（dedup 后必建得成）。
create unique index if not exists jobs_canonical_jd_url_active_uniq
  on jobs (canonical_jd_url)
  where status = 'active';

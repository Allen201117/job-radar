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
set statement_timeout = '1800s';

create table if not exists jobs (
  id                uuid primary key default gen_random_uuid(),
  source_id         uuid,
  company           text not null,
  title             text not null,
  location          text,
  country_code      text,
  job_scope         text not null default 'domestic',
  job_type          text,
  grad_class        smallint,   -- 届别（2027 = 2027 届）；只认硬信号，抽不出留 NULL（见 crawler/grad_class.py）
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
  confirmed_closed_at timestamptz,   -- 我们确认下架的时刻（判死时写，best-effort；v3 时间记真 02 §4.1）
  sponsorship_signal text,
  search_doc        tsvector,   -- 保留列；v1 不填（FTS 后置 pass 再启用）
  canonical_jd_url  text,
  constraint jobs_company_title_location_jd_url_key unique (company, title, location, jd_url)
);

-- 增量列（既有库 create-if-not-exists 不会补列 → 显式幂等 alter）。
alter table jobs add column if not exists confirmed_closed_at timestamptz;
alter table jobs add column if not exists country_code text;
alter table jobs add column if not exists job_scope text;
alter table jobs alter column job_scope set default 'domestic';
update jobs set job_scope = 'domestic' where job_scope is null;
alter table jobs alter column job_scope set not null;
alter table jobs add column if not exists sponsorship_signal text;

-- ── 招聘类型物化（2026-09-03，第1步：只加列 + 回填，暂不改任何读写行为）──────────────
-- 为什么要存：判「社招/校招/实习」的规则只有一份权威实现，在 JS（lib/china-keyword-expansion.js
-- 的 recruitmentCategory，七层裁决 + 完整单测）。而检索侧只能用「正向信号并集」的 SQL 近似去捞，
-- 两套判据结构不同 → 必然捞进大量注定被否决的岗（live 实测「深圳+校招」候选 4354 条里 43% 是
-- 这么来的：37% 挂在社招门户下、SQL 那套压根没看门户信号）。把 JS 的裁决结果存下来，检索与筛选
-- 从此查同一个字段，结构上不可能再不一致。
--
-- ⚠️ 必须存**两个**值，缺一不可 —— job-filter.jobFilterMatch 同时用到它们：
--     有明确依据 → 类型不符就淘汰；无明确依据 → 选社招放行降级、选校招/实习淘汰。
--   只存 category 而不存 explicit，SQL 仍然无法精确表达这条规则。
-- ⚠️ NULL = 「还没算」，不等于「不是」。检索必须放行 NULL 走原有兜底，否则回填期间和分类失败时
--   新岗会从筛选结果里凭空消失（新岗恰恰是用户最想看的）。
-- 值域：recruitment_category ∈ {社招, 校招, 实习}；两列由同一次 JS 计算同时写入，不允许只写一个。
alter table jobs add column if not exists recruitment_category text;
alter table jobs add column if not exists recruitment_explicit boolean;
-- 届别（2026-08-04，2027 届秋招）。存量行留 NULL 不回填：届别只认岗位文本里的硬信号，
-- 靠入库时间倒推等于猜，会把上一届残岗标成当季（详见 crawler/grad_class.py 注释）。
-- 存量岗会在下一轮列表重抓时由 normalizer 自然补上（抽得出才补）。
alter table jobs add column if not exists grad_class smallint;

-- ── 岗位生命周期事件（append-only 里程碑；02 spec §5.1）──
-- 只记里程碑，不记心跳：每岗一辈子 ~2–4 条（首见/拿到官方发布/若干天确认/下架）。
-- event_key 幂等去重（FIRST_SEEN/OFFICIAL_POSTED 一辈子一条；CONFIRMED_OPEN/CLOSED/REAPPEARED 按天）。
-- 不做 RLS（在 jobs-db，不直供客户端读）；expired→active 不产生 REAPPEARED（保 expired sticky）。
create table if not exists job_events (
  id            uuid primary key default gen_random_uuid(),
  event_key     text not null unique,
  job_id        uuid not null references jobs(id) on delete cascade,
  source_id     uuid,
  event_type    text not null check (event_type in (
                  'FIRST_SEEN',
                  'OFFICIAL_POSTED',
                  'CONFIRMED_OPEN',
                  'CLOSED',
                  'REAPPEARED'
                )),
  occurred_at   timestamptz not null default now(),
  observed_at   timestamptz not null default now(),
  payload       jsonb not null default '{}'::jsonb
);
create index if not exists idx_job_events_job_time on job_events (job_id, occurred_at desc);
create index if not exists idx_job_events_type_time on job_events (event_type, occurred_at desc);

-- ── 撤岗墓碑：岗位行被 purge 物理删除后，唯一活下来的「这个岗曾被确认关闭」的证据 ──────────
-- 为什么需要它（2026-09-08 立，修 F1）：
--   purge-expired 每天 `delete from jobs where status='expired'`（近 14 天实测均值 **2,871 行/天**、
--   合计 40,199 行），而 job_events.job_id 是 ON DELETE CASCADE → CLOSED 事件跟着一起没。
--   于是 jobs_db._find_existing_id_by_canonical 按 canonical 查不到任何行 → 走 fresh INSERT →
--   同一个岗以**全新 uuid + 全新 first_seen_at** 变回 active。
--   而 wt/hotjob 的列表本来就夹带已关闭岗（52% / 71%，见 CLAUDE.md），所以这条链是真能跑通的：
--   判死 → purge → 列表再见 → 又变新岗。sticky-expired 只保护「行还在」的情况，救不了已删的身份。
-- ⚠️ 刻意**不做**「命中墓碑就拒绝入库」：公司确实会重开同一个岗位链接，一刀切拒收 = 把真机会永久
--   删掉，违反「宁可漏判不可错杀」。所以本表先只做两件事：① 保住关闭证据；② 用 reopen_count/
--   reopened_at 把「复活率」变成**可查询的数字**——在拿到这个数字之前，任何拦截策略都是拍脑袋。
create table if not exists job_closures (
  canonical_jd_url text primary key,
  job_id           uuid not null,          -- 被删那一行的 id；**刻意不做外键**（那一行马上就要被删掉）
  source_id        uuid,
  company          text,
  title            text,
  first_seen_at    timestamptz,            -- 原始首次见到时间，复活时可用来判断「这真是新岗吗」
  closed_at        timestamptz not null,   -- 探活确认撤岗的时刻（confirmed_closed_at，缺失则用 purge 时刻）
  purged_at        timestamptz not null default now(),
  reason           text,
  reopened_at      timestamptz,            -- 最近一次「同 canonical 又被当新岗插进来」的时刻
  reopen_count     integer not null default 0
);
create index if not exists job_closures_closed_at_idx on job_closures (closed_at desc);
create index if not exists job_closures_reopened_idx on job_closures (reopened_at desc) where reopened_at is not null;

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

-- ── 招聘类型物化两列的「所有权」归数据库（2026-09-03）────────────────────────────────
-- recruitment_category / recruitment_explicit 是**派生数据**：它必须是「库里那一行」的函数。
-- 但规则本体是七层裁决（lib/china-keyword-expansion.js，几百行正则 + 完整单测），照抄进 SQL
-- 就是制造第二份会漂移的实现 —— 本库在 canonicalize_jd_url 上吃过这个亏，不再犯。
-- 所以这个触发器**不算分类，只管作废与保权**：
--
--   ① 分类输入变了 → 旧结论作废（置 NULL）。NULL = 「还没算」≠「不是」，检索侧对它退回
--      安全的信号超集（lib/jobs-store/search.ts），结果照样正确，只是候选略宽。
--   ② 分类输入没变、却有人想改这两列 → **驳回，保留库里那份**。
--      这条正是 2026-09-03 那个 bug 的结构性封堵：列表重抓拿「本次抓到的瘦 payload」算分类，
--      而 summary / job_type / experience 落库走 COALESCE 保留旧值 → 写进来的结论是按瘦数据
--      算的、和最终那一行对不上。实测 8,140 行 / 1.93% 漂移，其中约 1,161 行是真校招/实习岗被
--      记成社招 —— 而检索按这两列**排除**候选，等于用户搜「校招」永远搜不到它们。
--   ③ 唯一有权写值的是重算任务（scripts/backfill-recruitment-category.js）：它读的是库里最终
--      那一行，结论必然自洽。靠 `set jobradar.reclassify = 'on'` 表明身份。
--
-- 为什么用触发器而不是「让每个写入方自己注意」：写入方有 4 条以上（爬虫 upsert / 爬虫富化 /
-- app upsert / app 富化），还会继续增加，语言也不同。靠自觉 = 下一个新路径原样复发。
-- INSERT 不拦：新行的 payload 就是整行内容，写入方算出来的必然自洽。
-- ⚠️ 改分类输入字段清单时，这里与 crawler/recruitment_classify._FIELDS 必须同步
--    （crawler/test_jobs_db_upsert.py 会拿两边对拍）。
create or replace function jobs_guard_recruitment_class()
returns trigger language plpgsql as $function$
begin
  if coalesce(current_setting('jobradar.reclassify', true), '') = 'on' then
    return new;  -- ③ 重算任务：放行
  end if;
  if (new.title, new.summary, new.job_type, new.jd_url, new.apply_url, new.company, new.experience)
     is distinct from
     (old.title, old.summary, old.job_type, old.jd_url, old.apply_url, old.company, old.experience)
  then
    new.recruitment_category := null;  -- ① 依据变了 → 结论作废
    new.recruitment_explicit := null;
  else
    new.recruitment_category := old.recruitment_category;  -- ② 依据没变 → 不许改结论
    new.recruitment_explicit := old.recruitment_explicit;
  end if;
  return new;
end;
$function$;

drop trigger if exists jobs_recruitment_class_guard_trg on jobs;
create trigger jobs_recruitment_class_guard_trg
  before update on jobs
  for each row execute function jobs_guard_recruitment_class();

-- ── 招聘阶段谓词（校招 / 实习）：与 lib/jobs-store/opportunities.ts 的 stageRecallPatterns 逐字对齐 ──
-- 它存在的唯一理由是**给下面两个分区索引写谓词**；应用层 SQL 不调它、也不需要改。
-- 之所以「不改应用层也能生效」：这是个简单 SQL 函数且标了 immutable，Postgres 建索引时会把它
-- **内联**成常量折叠后的那串 OR-of-LIKE，与召回 SQL 里的 where 子句结构完全相同 → 谓词匹配成立。
-- ⚠️ 改这里必须同步改 lib/jobs-store/opportunities.ts 的 stageRecallPatterns，否则谓词不再匹配、
-- 索引会被 planner 静默忽略（不报错，只是又变慢）。改完用 EXPLAIN 确认仍走 *_campus_gin / *_intern_gin。
-- ⚠️ 这里的词表必须是 lib/china-keyword-expansion.js 里 sourceDeclaredCategory + hasStrongCampusSignal
-- + hasInternSignal 在 **title / job_type / jd_url 三个字段上**全部正向信号的**超集**，
-- 否则「后置判它符合、前置压根没召回」（2026-09-08 修的 F8）：标题叫「管培生」的在招校招岗
-- 六个旧词一个都不含 → 校招用户在 /today 永远看不见它，而 /jobs 页筛得到（那条链走物化列）。
-- 只许加词、不许减词：加词只会让候选变多（后置门照样精筛），减词=静默漏掉真岗，精度红线。
-- 📌 已知残差（刻意不修）：hasStrongCampusSignal 还扫 summary，本函数只看三个短字段——
--    「标题看不出、只有正文写着应届」的岗仍会漏。把 summary 加进索引谓词会显著放大这两个
--    分区索引，属于要先量后改的容量决策，不在本次修复范围。
create or replace function job_stage_match(p_title text, p_job_type text, p_jd_url text, p_stage text)
returns boolean language sql immutable parallel safe as $function$
  select case p_stage
    when 'campus' then
         lower(p_title) like any(array['%校招%','%校园%','%应届%','%campus%','%graduate%','%届%','%管培生%','%管理培训生%','%留学生专项%','%new grad%','%entry-level%','%entry level%'])
      or lower(coalesce(p_job_type,'')) like any(array['%校招%','%校园%','%应届%','%campus%','%graduate%','%届%','%管培生%','%管理培训生%','%留学生专项%','%new grad%','%entry-level%','%entry level%'])
      or lower(coalesce(p_jd_url,'')) like any(array['%campus%','%xiaozhao%'])
    when 'intern' then
         lower(p_title) like any(array['%实习%','%intern%','%shixi%'])
      or lower(coalesce(p_job_type,'')) like any(array['%实习%','%intern%','%shixi%'])
      or lower(coalesce(p_jd_url,'')) like any(array['%shixi%','%intern%'])
    else true
  end
$function$;

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
  where j.status = 'active'
    and j.company is not null
    and j.company <> ''
    and j.summary is not null
    and char_length(btrim(j.summary)) >= 60
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
create index if not exists jobs_job_scope_status_idx        on jobs (job_scope, status) where status = 'active';
create index if not exists jobs_status_first_seen_idx       on jobs (status, first_seen_at desc);
create index if not exists jobs_valid_active_idx            on jobs (id) where status = 'active' and summary is not null and char_length(btrim(summary)) >= 60;

-- ── 中文 bigram 全文检索 GIN（search_doc）：app 搜索主路径（lib/jobs-store/search.ts 的 textSearch）──
create index if not exists jobs_search_doc_gin on jobs using gin (search_doc);

-- 「等待重算的行」专用小索引：触发器把结论作废后（recruitment_category 置 NULL），
-- 补算任务要按 id 翻页找出这些行。不建这个索引，它就得为了几百行去全表 42 万行捞一遍。
-- 部分索引只装 NULL 行，平时几乎不占空间。
create index if not exists jobs_recruitment_unclassified_idx on jobs (id) where recruitment_category is null;

-- ── 校招 / 实习分区 GIN：治 /today 召回的方向层慢（2026-08-27 加）──
-- 病因：召回方向层的 tsquery 命中十几万行后，**还要逐行堆扫**才能应用招聘阶段过滤
-- （title/job_type/jd_url 三个 like，走不了索引），实测某真实校招画像 14.7 万行只留下 7,456 行。
-- 修法：把「阶段」下沉成索引谓词，让 GIN 扫描本身只返回该阶段的岗。
-- live 实测（实习档同一条召回，前后对照各 3 轮，全程未删任何索引）：3,211/3,376/5,648ms → 316/317/482ms（≈−90%）。
-- 成本：campus ≈ 8MB / intern ≈ 4MB；CREATE INDEX CONCURRENTLY 各 4–6 秒建成、全程不锁写。
-- ⚠️ 应用层 SQL 一行没改就生效（靠 job_stage_match 被内联后与 where 子句结构相同）。
-- 社招（无阶段过滤）用不到这两个索引，仍走全量 jobs_search_doc_gin —— 已知边界，不是漏配。
-- 生产上首次创建请用 CONCURRENTLY；本文件是幂等重建用，普通 create 即可。
-- ⚠️ **改了 job_stage_match 的词表就必须重建这两个索引**，所以这里先 drop 再 create。
-- 原因：索引条目是按**建索引那一刻**的谓词算出来的，`create or replace function` 不会回头
-- 重算它们。只换函数不重建 = 新词命中的行根本不在索引里，而 planner 仍然认为这个部分索引
-- 覆盖了整个 where 条件 → **静默少返回岗位**，不报错、不变慢，只是查不到（比漂移更隐蔽）。
drop index if exists jobs_search_doc_campus_gin;
drop index if exists jobs_search_doc_intern_gin;
create index if not exists jobs_search_doc_campus_gin on jobs using gin (search_doc)
  where status = 'active' and job_stage_match(title, job_type, jd_url, 'campus');
create index if not exists jobs_search_doc_intern_gin on jobs using gin (search_doc)
  where status = 'active' and job_stage_match(title, job_type, jd_url, 'intern');

-- 注：原 jobs_title_trgm_idx / jobs_company_trgm_idx（pg_trgm GIN，title/company ILIKE 辅助）已于
-- 2026-06-20 下架——生产实测 5 天 0 次 idx_scan（搜索的 ilike 都在 FTS 收窄后的小集合上过滤、用不到它们），
-- 白吃每次 upsert 的 GIN 维护开销 + 36MB 缓存。pg_trgm 扩展保留；若未来有全表 ILIKE 热查询可按需重建。

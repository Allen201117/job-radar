-- ============================================================
-- 141 — bigram 回填提速/防超时：截断超长输入 + 给回填 RPC 自己的更长 statement_timeout
-- ============================================================
-- 现象：140 的 chinese_bigrams 用循环拼接(O(n²))；中文摘要常无空格→整段成「一个超长词」→单行开销爆炸，
--   批量回填撞 anon/service 角色的 statement_timeout(~10s)。两手治理：
--   ① chinese_bigrams 截断输入到前 4000 字符(标题+摘要头足够检索；同时限制索引膨胀)；
--   ② backfill_search_bigrams 用函数级 SET statement_timeout='180s'，让大批次也能跑完。
-- 幂等；push 后由 migrate.yml 自动应用。已回填的存量行(用旧函数)无需重来，差异仅长摘要尾部，无害。

create or replace function chinese_bigrams(t text) returns text as $$
declare
  tok text;
  res text := '';
  i int;
  n int;
begin
  -- 截断超长输入，规避无空格中文长串的 O(n²) 拼接开销 + 控制索引大小。
  foreach tok in array regexp_split_to_array(left(lower(coalesce(t, '')), 4000), '\s+')
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

-- 回填 RPC 加函数级更长超时（让批次不被角色默认 ~10s 砍断）。
create or replace function backfill_search_bigrams(batch int default 2000) returns int
language plpgsql
set statement_timeout = '180s'
as $$
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
$$;

grant execute on function backfill_search_bigrams(int) to service_role;

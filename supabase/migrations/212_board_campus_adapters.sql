-- 212 — classify_source_board：把新增的「专职校招 adapter」纳入 campus 判定
--
-- 起因：2027 届秋招补校招供给时接入了 tencent_campus（join.qq.com，869 岗）。
-- 它的 source_url 是 `https://join.qq.com/` —— **不含任何 campus/school/grad 令牌**，
-- 于是 classify_source_board 走到最后的兜底分支判成了 `social`。
-- 后果不是「显示不好看」，而是这个源会**被校招车道漏掉**：
--   · campus-crawl 车道选源用 `board in ('campus','mixed')` → 869 个校招岗不会进高频刷新
--   · 校招供给覆盖度量的 hasCampusSource 同样只认 campus/mixed → 腾讯会被误判成「没接校招通道」
--
-- 判据不能靠 URL 令牌：一家公司的校招域名叫什么完全随它高兴（join.qq.com 就没有任何令牌）。
-- **adapter 本身是不是只抓校招，才是确定的事实** —— 这正是规则②（bytedance_campus）已有的思路，
-- 这里把新的几个专职校招 adapter 一并纳入。
--
-- 派生列不存业务数据，drop + 重建无损（回滚方式见迁移 187 末尾）。

create or replace function public.classify_source_board(p_adapter text, p_url text)
returns text
language sql
immutable
as $$
  select case
    -- ① adapter 一次抓全社招+校招+实习
    when coalesce(p_adapter, '') in ('tencent', 'baidu', 'wt', 'beisen') then 'mixed'
    -- ② 专职校招 adapter：只抓校招/实习，与社招是两个独立源。
    --    ⚠️ 判据是 adapter 而不是 URL —— 校招域名叫什么各家随意（join.qq.com 无任何令牌）。
    when coalesce(p_adapter, '') in (
      'bytedance_campus', 'tencent_campus', 'hikvision', 'jd_campus',
      'alibaba_campus', 'meituan_campus', 'kuaishou_campus'
    ) then 'campus'
    -- ③ 阿里 BU 的 off-campus = 社招频道，必须先短路
    when coalesce(p_url, '') ~* 'off-campus' then 'social'
    -- ④ URL 校招令牌
    when coalesce(p_url, '') ~* '(campus|/school|school\.html|/grad|university|xiaozhao)' then 'campus'
    -- ⑤ URL 实习令牌
    when coalesce(p_url, '') ~* '(intern|shixi)' then 'intern'
    else 'social'
  end
$$;

comment on function public.classify_source_board(text, text) is
  '由 (adapter_name, source_url) 派生招聘板块：mixed=一次抓全三类 / campus / intern / social。'
  'sources.board 的唯一权威；改规则须 drop+add sources.board 列重建（见迁移 187 注释）。';

-- 派生列必须重建才会用上新规则（generated 列不会因函数改变而自动重算）。
alter table public.sources drop column if exists board;
alter table public.sources
  add column board text
  generated always as (public.classify_source_board(adapter_name, source_url)) stored;

comment on column public.sources.board is
  '招聘板块（派生列，不可写）：mixed=adapter 一次抓全三类 / campus / intern / social。'
  '⚠️ 仅静态分类；判「该源有没有校招供给」须叠加实际产出，见迁移 187 注释第 3 条。';

create index if not exists sources_campus_board_idx
  on public.sources (board)
  where enabled and board in ('campus', 'mixed');

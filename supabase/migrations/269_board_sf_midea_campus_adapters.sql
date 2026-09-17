-- 269 — classify_source_board：把 sf_express_campus / midea_campus 纳入 campus 判定
--
-- 与迁移 212 / 220 同一个理由：**adapter 只抓校招，是确定的事实；URL 长什么样不是。**
--
-- 这两家一正一反，正好说明为什么不能只靠 URL 令牌：
--   · 顺丰校招门户的列表路由是 `https://crs-pub.sf-express.com/#/positionList` ——
--     **一个 campus/school/grad 令牌都没有**（站内也找不到带令牌的等价路由：
--     它的路由表只有 /positionList /traineeList /allList /homePage 这些）。
--     只走规则④会被判成 social → 被 campus-crawl 车道整条漏掉，
--     校招供给度量的 hasCampusSource 还会误报「顺丰没接校招通道」。
--   · 美的校招门户是 `https://careers.midea.com/schoolOut/post`，眼下含 `/school` 令牌、
--     走规则④也判得对；但同样钉进规则②，防「哪天美的把 schoolOut 改个名」时静默退回 social。
--
-- ⚠️ 本函数是**全量重建**写法：新迁移必须把既有规则一条不落抄全（这里是在 235 的基础上
--    只往规则②的名单里加两个 adapter，其余逐字照抄）。
-- 派生列不存业务数据，drop + 重建无损（回滚方式见迁移 187 末尾）。

create or replace function public.classify_source_board(p_adapter text, p_url text)
returns text
language sql
immutable
as $$
  select case
    -- ① adapter 一次抓全社招+校招+实习
    when coalesce(p_adapter, '') in ('tencent', 'baidu', 'wt', 'beisen', 'chnenergy') then 'mixed'
    -- ② 专职校招 adapter：只抓校招/实习，与社招是两个独立源。
    --    ⚠️ 判据是 adapter 而不是 URL —— 校招域名叫什么各家随意
    --    （join.qq.com / crs-pub.sf-express.com 都没有任何令牌）。
    when coalesce(p_adapter, '') in (
      'bytedance_campus', 'tencent_campus', 'hikvision', 'jd_campus',
      'alibaba_campus', 'meituan_campus', 'kuaishou_campus', 'huawei_campus',
      'sf_express_campus', 'midea_campus'
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

-- drop column 会连带删掉这个部分索引，必须重建（同迁移 212 / 220）。
create index if not exists sources_campus_board_idx
  on public.sources (board)
  where enabled and board in ('campus', 'mixed');

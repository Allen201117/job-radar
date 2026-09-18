-- 276 — classify_source_board：把 duoyi_campus（多益网络校招官网 xz.duoyi.com）纳入 campus 判定
--
-- 与迁移 212 / 220 / 269 同一个理由：**adapter 只抓校招，是确定的事实；URL 长什么样不是。**
-- 多益校招官网的列表路由是 `https://xz.duoyi.com/v40/#/positions`——host 前缀 `xz`（校招拼音首字母）
-- 之外没有任何 campus/school/grad 令牌；社招是 `sz.duoyi.com` 同一路径、同一套 /v40/api，
-- 只差 `recruit=10|20` 渠道码（见 crawler/adapters/duoyi.py）。只走规则④两条都判 social →
-- campus-crawl 车道整条漏掉校招那一条，校招供给度量也会误报「多益没接校招通道」。
-- 故校招那一条源的 adapter_name 用 `duoyi_campus`（run.py 里与 `duoyi` 是同一个类，同 zto/zto_campus 先例）。
--
-- ⚠️ 本函数是**全量重建**写法：在 269 的基础上只往规则②的名单里加 `duoyi_campus`，其余逐字照抄。
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
      'sf_express_campus', 'midea_campus', 'duoyi_campus'
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

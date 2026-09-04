-- 220 — classify_source_board：把 huawei_campus 纳入 campus 判定
--
-- 与迁移 212 同一个理由：**adapter 只抓校招，是确定的事实；URL 长什么样不是**。
-- huawei_campus 的 source_url（career.huawei.com/cn/campus-recruitment）眼下含 campus 令牌，
-- 走规则④也能判对；但把它钉在规则②里，是为了防「哪天华为改了路径」时静默退回 social ——
-- 退回的后果不是显示难看，是这个源被校招车道整条漏掉（campus-crawl 按 board 选源）。
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
      'alibaba_campus', 'meituan_campus', 'kuaishou_campus', 'huawei_campus'
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

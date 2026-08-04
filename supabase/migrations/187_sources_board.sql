-- 187: sources.board —— 把「这是不是校招板块源」变成系统里可查询的一等概念
--
-- 背景（2026-08-04）：系统此前无法回答「哪些源是校招源」，只能在应用层用正则扫 source_url 里
-- 有没有 campus 字样（lib/campus-sources.ts 的 isCampusSource）。这个判据已经出过一次事故
-- （校招专区把「有真校招岗但 URL 不含 campus 令牌」的源判成 ⚙️ 待接入，卡面同时列着真岗，自打脸），
-- 而 2027 届秋招要开高频校招车道，选源必须有个可靠依据。
--
-- 设计：board 是**纯派生列**（generated always as … stored），从 (adapter_name, source_url) 算出，
-- 单一权威、不可写、零 drift——不做 SQL/TS/Python 三处镜像（canonical_jd_url 那套镜像已被证明是
-- drift 温床，见 CLAUDE.md 数据质量段）。改规则 = 改这个函数（需 drop + add 列，见文末回滚段）。
--
-- ⚠️ 两个 live 实测得来的判据，改动前务必看懂：
--
-- 1) mixed 名单来自 **adapter 源码事实**，不是猜的：
--    · tencent  —— adapters/tencent.py `BOARD_ATTRS = (("1","社招"),("2","校招"),("3","实习"))`，三板块都翻
--    · baidu    —— adapters/baidu.py  `RECRUIT_TYPES = ("SOCIAL","CAMPUS","INTERN")`，三类都翻
--    · wt       —— adapters/wt.py     `_RECRUIT_TYPES = (2, 1, 12)`，社/校/实都翻
--    · beisen   —— china_ats.py 发 `Category: []`（不按招聘类别过滤）→ URL 路径根本不参与筛选，
--                  /campus 与 /social 抓回同一份全量（迁移 186 已据此去重）
--    live 佐证：beisen 里 **URL 不含 campus 令牌**的 113 个源照样产出 2094 个校招岗。
--    新增 / 改动 adapter 使其覆盖类别变化时，**必须同步这份名单**，否则校招车道会漏抓或空跑。
--
-- 2) `off-campus` 必须先排除，否则 13 个阿里 BU 源会被误判成校招源：
--    阿里各 BU 的**社招**频道地址字面就是 `…/off-campus/position-list`（校招是另一个 channel），
--    裸 `campus` 正则命中它 = 把纯社招源标成校招源 → 车道空烧 + 专区徽章错报「已接入校招」。
--
-- 3) board 只是**静态分类**，不是校招供给的唯一判据。真实产出（该源到底有没有产校招岗）由
--    调用方另行叠加（crawler/campus_lane.py 的 union 选源、campus-zone 的 campusJobCount 优先）。
--    原因：live 实测有 20 个源「adapter 非 mixed + URL 无令牌」却在产大量校招岗
--    （比亚迪 2053 / 小红书 585 / Citi 267 / 华为 198 / 米哈游 119 / 蚂蚁 109 …）——
--    这些自建门户把校招社招混在一个列表里，任何静态规则都判不出来，只能靠产出反查。
--    **所以：board 用于「还没产出过的新源」与徽章展示；选源必须 board ∪ 实际产出。**

-- 派生规则（immutable，供 generated 列使用）
create or replace function public.classify_source_board(p_adapter text, p_url text)
returns text
language sql
immutable
as $$
  select case
    -- ① adapter 一次抓全社招+校招+实习（判据见文件头 1）
    when coalesce(p_adapter, '') in ('tencent', 'baidu', 'wt', 'beisen') then 'mixed'
    -- ② 专职校招 adapter（字节校招/实习与社招是两个独立源）
    when coalesce(p_adapter, '') = 'bytedance_campus' then 'campus'
    -- ③ 阿里 BU 的 off-campus = 社招频道，必须先短路（判据见文件头 2）
    when coalesce(p_url, '') ~* 'off-campus' then 'social'
    -- ④ URL 校招令牌（moka campus-recruitment / hotjob school.html / 拼多多 campus/grad /
    --    OPPO university…campus / 北森 zhiye /campus）
    when coalesce(p_url, '') ~* '(campus|/school|school\.html|/grad|university|xiaozhao)' then 'campus'
    -- ⑤ URL 实习令牌（hotjob interns.html / 百度 intern-list）
    when coalesce(p_url, '') ~* '(intern|shixi)' then 'intern'
    else 'social'
  end
$$;

comment on function public.classify_source_board(text, text) is
  '由 (adapter_name, source_url) 派生招聘板块：mixed=一次抓全三类 / campus / intern / social。'
  'sources.board 的唯一权威；改规则须 drop+add sources.board 列重建（见迁移 187 注释）。';

alter table public.sources
  add column if not exists board text
  generated always as (public.classify_source_board(adapter_name, source_url)) stored;

comment on column public.sources.board is
  '招聘板块（派生列，不可写）：mixed=adapter 一次抓全三类 / campus / intern / social。'
  '⚠️ 仅静态分类；判「该源有没有校招供给」须叠加实际产出，见迁移 187 注释第 3 条。';

-- 校招车道选源用（board in (campus,mixed) 且 enabled）；源表仅千行级，部分索引足够。
create index if not exists sources_campus_board_idx
  on public.sources (board)
  where enabled and board in ('campus', 'mixed');

-- 回滚 / 改规则：
--   alter table public.sources drop column board;
--   （再重新 create or replace function + add column 即可；派生列不存业务数据，重建无损）

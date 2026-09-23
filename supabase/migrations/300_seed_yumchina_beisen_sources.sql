-- 300 — 接入百胜中国（北森老版 SSR 租户 yumchina，社招 + 校招），带入库口径
--
-- 决定来源：迁移 296 刻意没接百胜中国，列为待创始人拍板；2026-09-23 由「项目更新汇总与验收」会话
-- 代创始人拍板（创始人可否决）：① 先取到地点，取不到地点的岗不入库；② 只收近 12 个月发布的岗。
--
-- ── 为什么之前取不到地点 ──
--   百胜的列表表格是 class=listtable、表头用 <thead><th>，而老版 SSR 解析只从 <td> 行认表头 →
--   列映射为空，「工作地点」「发布时间」两列整列丢失（2392/2392 无地点）。已改为表头也认 <th>，
--   并新认「发布时间」列（china_ats._SSR_HEAD_CELL_RE / _SSR_COL_ALIASES）。地点取单元格 title 里的
--   整串（「浙江省-绍兴市-诸暨市」），不取页面上被截断的「浙江省-绍兴市-...」。
--
-- ── 入库口径（china_ats._SSR_TENANT_POLICY，只对 yumchina 生效，其余老版 SSR 租户行为不变）──
--   没有地点的不收；发布超过 365 天的不收；发布日期缺失也不收（证明不了是近期的）。
--   先筛后补正文（补正文每轮有上限，先补后筛会把名额花在要被筛掉的旧岗上）。
--
-- ── 接入前 live 验过的事实（2026-09-23，本机 adapter 端到端 fetch→parse→validate_job_quality）──
--   社招 /social：列表 2392 = 站点自报 2392（160 页翻到底，fetch_complete=True），地点 2392/2392、
--                 发布时间 2392/2392 都取到；按口径保留 554（2026-04~09 共 507 + 2025-09-24 之后 47），
--                 valid 554 / jd_url 唯一 554 / 地点全部识别为国内。
--   校招 /campus：列表 96 = 自报 96，按口径保留 3（其余是旧批次）。
--   · 归属：页面自报「百胜中国招聘系统」；详情 /zpdetail/{id} 真开 3 条全 HTTP 200。
--   · 岗位构成：约 70% 是「肯德基/必胜客餐厅储备经理」按城市铺开，标题带城市，不是纯重复副本。
-- ⚠️ 遗留：这条路径关掉了「列表缺席即撤岗」（china_ats._httpx_fetch_ssr_paged 注释），所以今天收进来的岗
--    满 12 个月后会被程序筛掉、不再上报，但库里那一行**不会自动下架**。2025-09~12 发布的 47 个会在
--    今年年底前陆续满期——需要后续补一个「按入库口径到期下架」的机制，不要编造截止日来凑。
-- ⚠️ 原「百胜中国」国聘源（iguopin，本档每轮 skipped、0 岗）保留不动，停不停用是单独的决定。
-- 回滚：update sources set enabled=false where source_url like 'https://yumchina.zhiye.com/%';

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select v.company, v.url, 'official', 'beisen', 'http', true, '{CN}', 'private', '餐饮', '消费/零售', 'private', v.notes
from (values
  ('百胜中国', 'https://yumchina.zhiye.com/social',
   '2026-09-23 缺口复核接入（口径：有地点 + 近 365 天发布）：北森老版 SSR 租户 yumchina，页面自报「百胜中国招聘系统」。列表 2392，按口径保留 554。'),
  ('百胜中国', 'https://yumchina.zhiye.com/campus',
   '2026-09-23 缺口复核接入（口径同社招）：百胜中国校招，列表 96，按口径保留 3。')
) as v(company, url, notes)
where not exists (select 1 from public.sources s where s.source_url = v.url);

-- 297 — 接入中信银行招聘官网（job.citicbank.com，新 adapter citicbank）：社招 752 + 校招 253
--
-- 为什么：中信银行是必投清单里的缺口公司，漏斗把它的入口记成了 careers.citics.com ——那是**中信证券**，
-- 另一家公司；库里唯一沾边的「中信银行信用卡中心」wecruit 源租户已不存在（每轮 skipped「官网不存在」）。
-- 2026-09-23 缺口复核找到真正的招聘官网：title「中信银行招聘官网」，meta 自述「中信银行各单位校园招聘、
-- 社会招聘和实习生招聘的官方渠道」，覆盖总行各部门 + 全部分行。
--
-- ── 接入前 live 验过的事实（2026-09-23，本机 adapter 端到端 fetch→parse→validate_job_quality）──
--   社招 #/social：parsed 752 / valid 752 / jd_url 唯一 752 / 自报 752 / fetch_complete=True /
--                 正文≥60字 748（99.5%）/ 地点全部识别为国内（广东 125、山东 83、江苏 83、北京 81…）
--   校招 #/campus：parsed 253 / valid 253 / 唯一 253 / 自报 253 / 正文 253（100%）
--   · should_skip() 两条都返回 None；_source_is_httpx_safe 为 True（走并发快车道）。
--   · 两个渠道的岗位 ID 互不重叠（1004/1004 唯一），所以拆成两条源各抓一个渠道；
--     校招那条 URL 带 campus → sources.board 生成列判 campus。
--   · 逐岗详情 /static/positionDetail_{ID}_{type}.html 服务端渲染；假 ID（99999999）返回 HTTP 404
--     「系统错误，请联系管理员」→ 真假 id 对拍通过，也是日后逐岗探活的现成信号（本次未接探活）。
--   · 发布日期绝大多数在 2026 年（最早 2023-07-15）。
-- ⚠️ 刻意没开 supports_absence_liveness（列表缺席即撤岗）：虽然接口总数与前端「新的机会(N)」一致，
--    但那条链路会走到 purge 永久删除，CLAUDE.md 要求先证明列表是全集再开，留给后续单独核。
-- 回滚：update sources set enabled=false where adapter_name='citicbank';

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select v.company, v.url, 'official', 'citicbank', 'http', true, '{CN}', 'soe', '银行', '金融', 'soe', v.notes
from (values
  ('中信银行', 'https://job.citicbank.com/#/social',
   '2026-09-23 缺口复核接入：中信银行招聘官网社招渠道（recruitmentType=01）。live 752 = 自报 752，正文 748。原台账入口 careers.citics.com 是中信证券。'),
  ('中信银行', 'https://job.citicbank.com/#/campus',
   '2026-09-23 缺口复核接入：中信银行招聘官网校招渠道（recruitmentType=02）。live 253 = 自报 253，正文 253。')
) as v(company, url, notes)
where not exists (select 1 from public.sources s where s.source_url = v.url);

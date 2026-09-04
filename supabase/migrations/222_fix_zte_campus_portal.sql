-- 222 — 中兴校招换到真正的 Moka 门户（1 → 100 岗）
--
-- 库里原有的中兴校招源 `app.mokahr.com/campus-recruitment/zte/94063` 是一个**没做完的模板页**：
-- 2026-09-04 live 渲染出来的正文是「在这里输入主标题 / 副标题 / 模块标题 / 链接标题 /
-- © 2021-2022 公司名称」，只挂着 1 个「中兴捧月」岗。此前据此判「中兴没开校招」——结论是错的。
--
-- 真正的门户是 `zte/46903`：live 渲染显示「应届生招聘 共59个职位 / 实习生招聘 共41个职位」，
-- 用我们现有的 moka adapter 直接跑通 **100 岗**，jd_url 形如
-- `…/campus-recruitment/zte/46903#/job/{uuid}`，零代码改动。
-- （线索来自两个独立第三方开源项目的实测记录，但入库前已自己 live 复核过，不是照抄。）
--
-- 旧源 disable 不删：保留行可回滚，也留个痕说明「那个 slug 是模板页、别再加回来」。
-- Idempotent: guarded by source_url。
-- ⚠️ crawl_method 只接受 'http' / 'playwright' / 'manual'；写 'browser' 会整批回滚（迁移 211 踩过）。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中兴通讯股份有限公司', 'https://app.mokahr.com/campus-recruitment/zte/46903', 'official',
       'moka', 'playwright', 'private', '通信·科技',
       '中兴通讯校园招聘（Moka 租户 zte/46903）。live 2026-09-04：应届生 59 + 实习生 41 = 100 岗。'
       '⚠️ 另一个 slug zte/94063 是没做完的模板页（正文全是「在这里输入主标题」占位符、只有 1 个岗），'
       '已 disable；别再把它当成「中兴没开校招」的证据。'
where not exists (
  select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/zte/46903');

update sources
   set enabled = false,
       notes = coalesce(notes, '') ||
               ' [2026-09-04 disable] 该 slug 是未完成的 Moka 模板页（正文为「在这里输入主标题」等占位符），'
               '只有 1 个岗。真正的中兴校招门户是 zte/46903（100 岗），见迁移 222。'
 where source_url = 'https://app.mokahr.com/campus-recruitment/zte/94063'
   and enabled;

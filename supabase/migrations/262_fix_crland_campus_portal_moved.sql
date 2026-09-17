-- 262：华润置地校招门户搬家了（moka orgId 143067 → 168540），不是「没有校招」（2026-09-18）
--
-- ⚠️ 这家在**必投清单**里，另有同事在跑必投缺口那条线；这条单独成文件就是为了万一撞车能整份丢掉。
--    本文件只动 crland 这一个 moka 租户，不碰任何其它源。
--
-- 现象：库里 `华润置地` 已经有一条 enabled 的校招源
--   https://app.mokahr.com/campus-recruitment/crland/143067
-- 但 jobs 里这家一个 active 岗都没有；must_apply_gap_attempts 记的是
--   state=no_active_jobs / fail_reason=「未找到可信官方招聘入口」（2026-09-15），
-- 迁移 255 的国聘校招通道对它也是 reported_total=290 / valid=0。
-- 三条证据叠在一起很容易读成「华润置地没开校招」——**不是**。
--
-- 根因：同一个 moka 租户 crland 下的**门户 orgId 换了**。2026-09-18 同一套 MokaAdapter 端到端对拍：
--   campus-recruitment/crland/143067 → 解析 0 个岗（门户还在、但已空）
--   campus-recruitment/crland/168540 → 446 个岗全过质量门，443 个在中国大陆；
--     标题形如「百匠新人-投资管理岗(有巢-南京)」「万象生-营运岗（商业-天津)」，
--     抽 3 个 jd_url 回读 HTTP 200。
-- 归属：同租户 crland（库里 `华润万象生活` 的社招源 social-recruitment/crland/143066 也在这个租户下），
--   不存在张冠李戴；也**不是新增影子源**——旧的那条同时置 disabled（保留行可回滚，按 CLAUDE.md 不删）。

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '华润置地', 'https://app.mokahr.com/campus-recruitment/crland/168540', 'official', 'moka', 'playwright',
       true, '{CN}', 'soe', '地产/建筑',
       '2026-09-18 端到端探活：446 岗全过质量门（443 个在华）；抽 3 个 jd_url 回读 HTTP 200。取代已空的 orgId 143067。'
where not exists (select 1 from public.sources
                  where source_url = 'https://app.mokahr.com/campus-recruitment/crland/168540');

update public.sources
   set enabled = false,
       notes = coalesce(notes || ' ', '') ||
               '[2026-09-18] 该 moka 门户 orgId 已空（端到端解析 0 岗），校招搬到 orgId 168540；'
               '保留行可回滚，按 CLAUDE.md「0 产出的源 disable、别删」。'
 where source_url = 'https://app.mokahr.com/campus-recruitment/crland/143067'
   and enabled = true;

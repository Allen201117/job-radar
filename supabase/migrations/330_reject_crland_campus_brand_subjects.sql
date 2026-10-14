-- 330 — 洞察：华润置地 / 华润万象生活 画像下的三个校招品牌名不是业务线，判噪声（2026-10-12，创始人同日同意）
--
-- 「万象生」「万悦生」「百匠新人」是华润置地校招门户（Moka crland/168540）自定义字段「校招品牌」的取值，
-- 抽取器按「标题开头 X-」把它们当成了业务线。它们不是业务线，而且两家公司都在用：
--   门户全量 441 个岗里，百匠新人同时出现在开发 32、商业 37、物业 12、有巢 7、文体 5，万悦生在物业 111、酒管 5，
--   万象生在商业 205、文体 18（逐岗对账见 docs/reviews/2026-10-11-moka-source-identity-and-closed-portals.md §10）。
-- 同日把这个门户里万象生活的岗逐行改挂到「华润万象生活」之后，这三个名字在两家画像下各有一个主体：
--   华润万象生活：万象生 212 / 万悦生 111 / 百匠新人 49；华润置地：百匠新人 45 / 万象生 21 / 万悦生 5。
--
-- 做法与管理后台「判噪声」那个按钮一样（app/api/insights/admin/subjects 的 PATCH）：
--   · 主体标 rejected，**保留行不删**——抽取器下一轮据此跳过（bu_extract），派生层只算 active 主体（bu_signals），不会被抽回来；
--   · 主体名下还在展的派生条目一起退役，否则条目留在 active、只是没有页面展示它们。
-- 只动这两家画像下、标题抽取出来的这三个业务线主体；公司主体、不挂主体的条目、别的画像一律不碰。
-- 第四个校招品牌「销冠生」只有 2 个岗、没到建主体的门槛，现在没有这个主体，没处理。
--
-- 幂等：已经 rejected 的主体不再改；条目那一句按「主体已是 rejected」找，重跑不会漏。

update insight_subjects s
   set status = 'rejected', updated_at = now()
  from company_profiles p
 where p.id = s.company_id
   and p.company in ('华润置地', '华润万象生活')
   and s.kind = 'business_unit'
   and s.origin = 'derived_title'
   and s.name in ('万象生', '万悦生', '百匠新人')
   and s.status <> 'rejected';

update insight_items i
   set status = 'retired', updated_at = now()
  from insight_subjects s
  join company_profiles p on p.id = s.company_id
 where i.subject_id = s.id
   and p.company in ('华润置地', '华润万象生活')
   and s.kind = 'business_unit'
   and s.origin = 'derived_title'
   and s.name in ('万象生', '万悦生', '百匠新人')
   and s.status = 'rejected'
   and i.status = 'active';

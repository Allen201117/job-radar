-- 305 — 北森租户普查（2026-09-24，307 个在用租户逐个翻全量列表）查出的两类问题：同一门户两个域名重复收录、源名起窄。
--
-- 一、同一个北森门户挂在两个域名上，各有一条源 → 同一批岗入库两行、两个公司名（都 status=success，没有失败信号）
--   停用                                          保留                                        核实（全集）
--   中环半导体 tjsemi.zhiye.com/social           TCL中环 zhonghuan.zhiye.com/social          同一个 PortalId d44a07d3…；香港库 758 个在招岗 jobAdId 逐个对上 758/758
--   贝壳找房   ke.zhiye.com/social               贝壳 Beike campus.ke.com/campus             同一个 PortalId 605d7a6c…；45 个在招岗 45/45
--   保留哪条：中环半导体 2022 年已更名 TCL中环；贝壳社招（join.ke.com，476 个在招）本来就叫「贝壳 Beike」，校招跟它统一。
--   库里已有的重复行不会因停用自己消失 → 香港库走 remove-jobs-by-url-prefix.yml（only_twins_under + twin_key=jobadid），
--   只标「保留门户下有同一 jobAdId 在招」的行为 removed（可逆，purge 不删）。
--
-- 二、源名起窄：门户是整个集团的，源却记成其中一个子品牌 → 别的子公司的岗全挂在这个子品牌名下
--   泰康之家 → 泰康保险：jobtaikang.zhiye.com 页面自称「泰康招聘门户」，1,562 个岗的招聘机构是泰康在线 123 / 泰康口腔 98 /
--     人寿总公司 95 / 集团总部 70 / 各地分公司…，养老社区与医院约三分之一。「泰康保险」与必投清单、国聘两条源同名。
--   建发房产 → 建发集团：chinacdc.zhiye.com/subzw/ 页面自称「建发集团」，是集团的子公司职位页；列表「招聘公司」列 79 个岗里
--     联发集团 31 / 参股企业 15 / 建发旅游 10 / 建发致新 9 / 建发物业 7 / 建发健康 4 / 建发合诚 2 / 建发股份 1，**建发房产 0 个**。
--     已停用的 /campus 那条同租户源一并改名，免得哪天重新启用又带回旧名。
--   ⚠️ 必投清单「建发房产」的匹配是 %建发%，改名后照样计入——那是北极星口径，本迁移不动。
--   库里已有行的 company 由 rename-job-company.yml 按前缀改（company 在 jobs_db._UPDATE_COLS 里，下一轮重抓也会自愈）。
--
-- where 都带 id + 当前 url + 旧值，重复执行无副作用。

update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-24 停用：与 zhonghuan.zhiye.com/social（TCL中环）是同一个北森门户（PortalId d44a07d3），758 个在招岗 jobAdId 逐个相同，重复入库。$md$
 where id = 'd7a3d24a-e4a5-42a2-bacb-66e1070a848b'
   and source_url = 'https://tjsemi.zhiye.com/social'
   and enabled;

update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-24 停用：与 campus.ke.com/campus（贝壳 Beike）是同一个北森门户（PortalId 605d7a6c），45 个在招岗 jobAdId 逐个相同，重复入库。$md$
 where id = '73617439-37da-4aa5-8fd8-8363834ed055'
   and source_url = 'https://ke.zhiye.com/social'
   and enabled;

update sources
   set company = '泰康保险',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-24 改名 泰康之家 → 泰康保险：门户自称「泰康招聘门户」，岗位来自泰康在线 / 泰康口腔 / 泰康人寿 / 集团总部 / 各地分公司等，养老社区只占一部分。$md$
 where id = '1ea1e4ba-972b-4999-ac64-f37fc591d6f1'
   and source_url = 'https://jobtaikang.zhiye.com/social'
   and company = '泰康之家';

update sources
   set company = '建发集团',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-24 改名 建发房产 → 建发集团：页面自称「建发集团」，是集团子公司职位页，列表「招聘公司」列里没有建发房产（联发集团 / 建发旅游 / 建发致新 / 建发物业…）。$md$
 where id in ('d4ab324b-d8eb-4350-a2a4-a9c9bb5e2a32', '1859e446-64d2-44b0-82fe-84864f0de6f2')
   and source_url like 'https://chinacdc.zhiye.com/%'
   and company = '建发房产';

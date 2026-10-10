-- 311 — 纠正张冠李戴：jks.hotjob.cn/wt/JKS 是「金科服务」（物业）不是「晶科能源」（光伏）（2026-10-10 查实）
--
-- 怎么发现的：给 wt 源补归属核对（audit_hotjob_attribution.audit_wt）时，全部 40 个 enabled wt 源逐个看门户自报，
--   除 310 的中国电信外只有这一条对不上。
-- 现象：sources 里 company='晶科能源控股有限公司'（notes「光伏组件，probe live 探活 在华 95 岗」，2026-06-10 seed），
--   香港库该前缀下 85 个 active + 2 个 expired 岗全挂这个名字。
-- live + 真库核验（全部只读）：
--   · 落地页 <title>=金科服务招聘；meta keywords「金科服务社会招聘,金科服务校园招聘…」；页面里「金科」11 次、
--     「晶科 / Jinko / 光伏」0 次。
--   · 列表全量翻完 84 岗，orgName 84/84 = 金科服务；标题是「心悦管家-华中区域-云阳世界城」「工程维修（基层级）」
--     「2027届-心悦管家-渝西区域」，地点成都 / 重庆 / 武汉 —— 物业公司的岗，不是光伏厂的岗。
--   · 库里 company 含「晶科」的行只有这一个前缀，「晶科能源」名下没有任何真岗。
-- 后果（比 310 重）：晶科能源在必投清单（能源/化工）里，缺口台账一直记它 healthy（健康岗 77、校招渠道 healthy、
--   近 3 天校招岗 11）—— 全是金科服务的物业岗撑起来的，晶科能源实际是零源缺口；公司类型筛「大厂」同理。
--   洞察页给晶科能源写的「大专及以上 54.2%、成都 26.5%」也是拿这批岗算的。
--
-- 处置：这条源本身是好的（岗位真实、jd_url 稳定、fetch_complete=True），只是挂错了名 → 保留、改公司名与行业标签。
--   存量 87 行走 rename-job-company.yml（按 jd_url 前缀点名）改名；`company` 在 jobs_db._UPDATE_COLS 里，
--   之后每轮重抓都按新名字写。晶科能源回到「零源缺口」，由缺口漏斗重新找入口。
--   「晶科能源控股有限公司」画像下由岗位库派生的在招指标一并撤下（理由同 310 ③）；上市状态那条说的是真的晶科能源，不动。
-- ⚠️ industry_group / ownership 受 CHECK 约束（迁移 265）：物业服务 → '地产/建筑'；金科服务是民营 → private。
-- Idempotent：where 带旧公司名 / status='active'，重复执行无副作用。

update sources
   set company = '金科服务',
       industry = '物业服务',
       industry_group = '地产/建筑',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-10 公司名由「晶科能源控股有限公司」纠正为「金科服务」：BRAND 代号 JKS 是金科服务。落地页 title=金科服务招聘，列表 84 个岗的 orgName 全是金科服务，岗位是心悦管家 / 工程维修（物业），与晶科能源（光伏）无关。$md$
 where source_url = 'https://jks.hotjob.cn/wt/JKS/web/index'
   and company = '晶科能源控股有限公司';

update insight_items
   set status = 'retired',
       updated_at = now()
 where company_id in (select id from company_profiles where company = '晶科能源控股有限公司')
   and origin = 'derived'
   and status = 'active';

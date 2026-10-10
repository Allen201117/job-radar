-- 311 — 纠正张冠李戴：www.hotjob.cn/wt/CT 是「财通证券」不是「中国电信」（2026-10-10 查实，创始人同日同意处置）
--
-- 现象：sources 里 company='中国电信'、adapter_name='wt'、source_url='https://www.hotjob.cn/wt/CT/web/index'
--   的源（迁移 105，2026-06-09 按 probe 探活结果 seed）一直在出岗，香港库该前缀下 215 个 active 岗全挂「中国电信」。
-- 根因：按 BRAND 代号 CT 猜的公司名，只看了探活出岗、没看门户自报是谁（同 248 / 274 / 291）。
-- live + 真库核验（全部只读）：
--   · 首页 302 → https://wecruit.hotjob.cn/SU60613f74bef57c36adc66d0b/pb/index.html；该租户 suite/config 自报
--     companyName=财通证券、suiteName=财通证券招聘官网、组织树=财通证券。它就是迁移 277 接的财通证券 hotjob 源。
--   · wt 列表全量翻完 215 岗，orgName：财通证券 168 / 分支机构 32 / 浙江财通资本投资有限公司 6 / 财通基金管理有限公司 3 /
--     财通证券上海分公司 2 / 永安期货股份有限公司 2 / 财通证券资产管理有限公司 2 —— 没有一条与中国电信有关。
--   · wt 的 215 个 postId 与财通门户三个渠道（社招 135 / 校招 72 / 实习 8）的 215 个 externalKey 一一对应，标题逐字相同：
--     两个接口吐的是同一个租户的同一批岗。库里因此同一批岗存了两份：wt 前缀 215 行（中国电信）+ 财通门户 207 行（财通证券）；
--     差的 8 行是实习岗——277 只接了社招、校招两个渠道。
--   · 库里 company='中国电信' 的行只有这一个前缀（215 active + 1 expired），「中国电信」名下没有任何真岗。
--   · 中国电信自己的招聘站：集团官网校招公告（www.chinatelecom.com.cn/ct/zp/168256.html）原文写
--     「集团自建招聘网站投递链接（https://job.chinatelecom.com.cn/）」，落地 /wt/TELE/web/index（title「中国电信招聘」，
--     校招 3,366 / 实习 12 / 社招 0）。本迁移不接它，另行评估。
-- 后果：按「中国电信」筛出来的是财通证券的投行 / 财富 / 营业部岗（归属准确性红线）；公司类型筛「央国企」时这 215 个岗
--   顶着中国电信的名字出现；洞察页给中国电信写的「在招 215 个、杭州 38.6%、金融业务 36.3%」全是拿这批岗算的。
--
-- 处置：
--   ① 停用 wt/CT 这条源（保留行可回滚）。存量 215 个 active 岗走 remove-jobs-by-url-prefix.yml 标 removed（可逆）。
--   ② 补上财通证券的实习渠道（同租户 interns.html），那 8 个实习岗以后挂在对的名字、对的链接下。
--      接入前 live 验过（2026-10-10，纯 httpx）：should_skip → None；fetch → parse 8/8，自报 total=8，fetch_complete=True；
--      validate_job_quality 8/8，正文 8/8（≥60 字），jd_url 唯一 8/8；浏览器实开 1 条详情页，渲染出岗位正文与「立即投递」。
--   ③ 把「中国电信」画像下由岗位库派生的在招指标撤下。派生任务对「一个岗都没有的公司」不会自己撤
--      （bu_signals 遇到 0 岗直接跳过那家公司），不撤就要等 14 天有效期过完才消失。只动 origin='derived'：
--      年报、上市状态、公开讨论那几条说的是真的中国电信，不动。
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列（迁移 187/269/276），显式赋值整批迁移会回滚。
-- Idempotent：update 的 where 带 enabled / status='active'，insert 带 not exists，重复执行无副作用。

update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-10 停用：BRAND 代号 CT 是财通证券，不是中国电信。首页 302 到 wecruit SU60613f74…（租户自报 companyName=财通证券），列表 215 个岗的 orgName 是财通证券及其子公司 / 分支机构，postId 与财通门户 215 个 externalKey 一一对应、标题逐字相同。财通证券的岗由 hotjob 源提供（迁移 277 社招 / 校招 + 迁移 311 实习）。中国电信自己的招聘站是 job.chinatelecom.com.cn/wt/TELE（集团官网校招公告原文给的地址），未接。$md$
 where source_url = 'https://www.hotjob.cn/wt/CT/web/index'
   and company = '中国电信'
   and enabled;

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select '财通证券', 'https://wecruit.hotjob.cn/SU60613f74bef57c36adc66d0b/pb/interns.html', 'official', 'hotjob', 'http',
       true, '{CN}', 'soe', '证券', '金融', 'soe',
       '2026-10-10 接入：财通证券实习板块（同租户 interns.html；社招 / 校招见迁移 277）。这 8 个实习岗此前只在挂错名的 wt/CT 源里。live：should_skip → None，自报 total=8，parse 8/8，validate_job_quality 8/8，正文 8/8，fetch_complete=True；浏览器实开 1 条详情页渲染出岗位与「立即投递」。'
where not exists (select 1 from public.sources where source_url = 'https://wecruit.hotjob.cn/SU60613f74bef57c36adc66d0b/pb/interns.html');

update insight_items
   set status = 'retired',
       updated_at = now()
 where company_id in (select id from company_profiles where company = '中国电信')
   and origin = 'derived'
   and status = 'active';

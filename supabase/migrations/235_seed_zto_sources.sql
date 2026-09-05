-- 234 — 接入中通快递自建门户（社招 + 校招），修正一次误判
--
-- 缺口台账把中通记成 `no_stable_jd`（「没有稳定逐岗链接」）并因此天天空烧重试。
-- **这是误判**，与 2026-09-05 推翻的「国有大行=公告制」同一类错误：
-- 只看了官网校招页（那页确实只有「蓝天计划」项目介绍 + 宣讲会 + 一个投递按钮，没有岗位列表），
-- 就断定整家公司没有一岗一页。实际社招/校招在 /social 与 /campus-position 下有完整逐岗列表。
--
-- 2026-09-05 live 核实（adapter crawler/adapters/zto.py，纯 httpx 零浏览器）：
--   · 社招 postType=1：reported_total=79，fetch_complete=True，parse 79 条，
--     76/79 有 ≥60 字正文，normalizer 质量门 79/79 通过；
--   · 校招 postType=2：reported_total=22，fetch_complete=True，parse 22 条，22/22 有正文；
--   · 随机抽 8 条逐岗页 https://hr.zto.com/position-detail?id={id}：
--     HTTP 200 8/8，且「列表标题 == 详情接口 postNameOut」8/8 一致（防张冠李戴）。
--   · 派生的子品牌都仍以「中通」开头（中通星联/云仓/餐饮/双彩/冷链），
--     不会掉出必投清单的 `%中通%` 匹配。
--
-- 🚫 刻意不接 postType=3（一线招聘，201 岗）：该档返回体带**真实 HR 姓名与手机号**
--    （contactUserName/contactUserPhone，社招校招档为 null），且内容是驾驶员/装卸工，
--    与目标用户无关。隐私 + 信噪比双重理由，详见 crawler/adapters/zto.py 模块注释。
--
-- ⚠️ 不要写 board 列：它是 GENERATED ALWAYS AS classify_source_board(adapter_name, source_url)，
--    显式赋值会报 cannot insert a non-DEFAULT value into column "board" 并让**整个文件一起回滚**。
-- ⚠️ 校招源的 source_url **必须含 `campus` 令牌**（/campus-position）：board 靠
--    classify_source_board 规则④从 URL 推 campus。zto_campus 没有钉进规则②的 adapter 白名单
--    （那要 drop+重建 sources.board 派生列，今天有多条 session 在改迁移，不动共享设施）。
--    若哪天中通改了前端路径，这个源会静默退回 social —— 届时应把 'zto_campus' 加进规则②。
-- Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中通快递', 'https://hr.zto.com/social', 'official', 'zto', 'http', 'private', '物流/供应链',
       '中通快递 社招（自建门户 hr.zto.com，postType=1）。列表 getPostInfoPageList + 详情 getPostInfoDetail 均为公开 JSON，网关 recruiting.gw.zt-express.com（不在 hr.zto.com 上，后者对任何 POST 返 405）。2026-09-05 live 79 岗、fetch_complete=True、抽验 8/8 逐岗页 200 且标题一致。'
where not exists (select 1 from sources where source_url = 'https://hr.zto.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中通快递', 'https://hr.zto.com/campus-position', 'official', 'zto_campus', 'http', 'private', '物流/供应链',
       '中通快递 校招（自建门户 hr.zto.com，postType=2，与社招同接口）。2026-09-05 live 22 岗（管理培训生各方向 = 蓝天计划的岗位侧）、fetch_complete=True、22/22 有正文。URL 必须保留 campus 令牌，board 判定依赖它。'
where not exists (select 1 from sources where source_url = 'https://hr.zto.com/campus-position');

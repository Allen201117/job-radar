-- 174 — 必投清单零覆盖大厂接入：腾讯音乐 / 蚂蚁集团 / 米哈游（2026-07-06 live 验证）。
-- 三家均为自建 SPA 招聘站，但岗位数据走公开 JSON 接口（零登录零浏览器，bespoke httpx adapter）：
--   腾讯音乐 join.tencentmusic.com：job/list(社招 118) + uc-job/list(校招/实习 129)，
--     逐岗 /social|campus/post-details/?id= SSR 直出正文；标题核验 3/3 通过。
--   蚂蚁集团 hrcareersweb.antgroup.com：social/campus position/search（社招 947 + 校招/实习 328），
--     逐岗 talent.antgroup.com/off-campus-position|campus-position?positionId= 可渲染；标题核验 3/3。
--   米哈游 ats.openout.mihoyo.com：v1/job/list hireType 0(社招 597)+1(校招/实习 153) + v1/job/info 逐岗正文，
--     逐岗 jobs.mihoyo.com/#/position|#/campus/position/{id} hash 路由可渲染；标题核验 3/3。
-- 质量门：normalizer 全量放行（0 丢弃），JD 正文≥60 字覆盖 99-100%。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '腾讯音乐 TME', 'https://join.tencentmusic.com/social', 'official', 'tencent_music', 'http', 'private', '音乐娱乐/互联网', '腾讯音乐（2026-07-06 live 验证：job/list+uc-job/list 公开接口 247 岗社招+校招，逐岗 post-details SSR 正文，标题核验通过）'
where not exists (select 1 from sources where source_url = 'https://join.tencentmusic.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '蚂蚁集团', 'https://talent.antgroup.com/off-campus-position', 'official', 'antgroup', 'http', 'private', '金融科技/互联网', '蚂蚁集团（2026-07-06 live 验证：hrcareersweb position/search 公开接口 1272 岗社招+校招，逐岗 positionId 详情可渲染，标题核验通过）'
where not exists (select 1 from sources where source_url = 'https://talent.antgroup.com/off-campus-position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '米哈游 miHoYo', 'https://jobs.mihoyo.com/#/position', 'official', 'mihoyo', 'http', 'private', '游戏/互联网', '米哈游（2026-07-06 live 验证：ats-portal v1/job/list+info 公开接口 750 岗社招+校招+实习，逐岗 hash 详情可渲染，标题核验通过）'
where not exists (select 1 from sources where source_url = 'https://jobs.mihoyo.com/#/position');

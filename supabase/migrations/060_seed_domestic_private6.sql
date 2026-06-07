-- 060 — 国内私企扩源批6（飞书 + Moka，live 验证）
-- crawl_method=playwright，segment='private'+industry。Idempotent。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '它石智航 TARS', 'https://tarsrobot.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '具身智能',
       '它石智航（具身智能机器人，飞书招聘泛化适配器，live 40 岗）'
where not exists (select 1 from sources where source_url = 'https://tarsrobot.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '搜狐 Sohu', 'https://app.mokahr.com/campus-recruitment/sohu/5682', 'official', 'moka', 'playwright', 'private', '互联网·媒体',
       '搜狐（互联网·媒体，Moka 渲染 DOM，live 验证）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/sohu/5682');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '博乐科技 Bole Games', 'https://app.mokahr.com/social-recruitment/bolegames/37642', 'official', 'moka', 'playwright', 'private', '游戏',
       '博乐科技（游戏，Moka 渲染 DOM，live 20 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/bolegames/37642');

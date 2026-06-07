-- 055 — 国内私企扩源批4（飞书 + Moka，live 验证）
-- crawl_method=playwright，segment='private'+industry。Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '智元机器人 AGIBot', 'https://agirobot.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '人形机器人',
       '智元机器人（人形机器人，飞书招聘泛化适配器，live 40 岗）'
where not exists (select 1 from sources where source_url = 'https://agirobot.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '影石 Insta360', 'https://arashivision.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '智能影像',
       '影石 Insta360（智能影像，飞书招聘泛化适配器，live 14 岗）'
where not exists (select 1 from sources where source_url = 'https://arashivision.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'xTool', 'https://xtool.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '激光设备',
       'xTool（激光设备，飞书招聘泛化适配器，live 40 岗）'
where not exists (select 1 from sources where source_url = 'https://xtool.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '安克创新 Anker', 'https://anker-in.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '消费电子',
       '安克创新 Anker（消费电子，飞书招聘泛化适配器，live 40 岗）'
where not exists (select 1 from sources where source_url = 'https://anker-in.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '文远知行 WeRide', 'https://app.mokahr.com/apply/jingchi/2138', 'official', 'moka', 'playwright', 'private', '自动驾驶',
       '文远知行 WeRide（自动驾驶，Moka 渲染 DOM，live 33 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/jingchi/2138');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '唯品会 VIP.com', 'https://app-tc.mokahr.com/campus-recruitment/vipshophr/8015', 'official', 'moka', 'playwright', 'private', '电商',
       '唯品会（电商，Moka 渲染 DOM，live 25 岗）'
where not exists (select 1 from sources where source_url = 'https://app-tc.mokahr.com/campus-recruitment/vipshophr/8015');

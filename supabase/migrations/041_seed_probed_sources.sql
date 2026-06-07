-- 041 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '礼来 Eli Lilly', 'https://lilly.wd5.myworkdayjobs.com/wday/cxs/lilly/LLY/jobs', 'official', 'workday', 'http', 'foreign', '医药', '礼来 Eli Lilly（医药，probe live 探活 在华 54 岗）'
where not exists (select 1 from sources where source_url = 'https://lilly.wd5.myworkdayjobs.com/wday/cxs/lilly/LLY/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '江森自控 Johnson Controls', 'https://jci.wd5.myworkdayjobs.com/wday/cxs/jci/JCI/jobs', 'official', 'workday', 'http', 'foreign', '工业·楼宇', '江森自控 Johnson Controls（工业·楼宇，probe live 探活 在华 109 岗）'
where not exists (select 1 from sources where source_url = 'https://jci.wd5.myworkdayjobs.com/wday/cxs/jci/JCI/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '博通 Broadcom', 'https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs', 'official', 'workday', 'http', 'foreign', '半导体', '博通 Broadcom（半导体，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '亚德诺 ADI', 'https://analogdevices.wd1.myworkdayjobs.com/wday/cxs/analogdevices/External/jobs', 'official', 'workday', 'http', 'foreign', '半导体', '亚德诺 ADI（半导体，probe live 探活 在华 26 岗）'
where not exists (select 1 from sources where source_url = 'https://analogdevices.wd1.myworkdayjobs.com/wday/cxs/analogdevices/External/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '恩智浦 NXP', 'https://nxp.wd3.myworkdayjobs.com/wday/cxs/nxp/careers/jobs', 'official', 'workday', 'http', 'foreign', '半导体', '恩智浦 NXP（半导体，probe live 探活 在华 45 岗）'
where not exists (select 1 from sources where source_url = 'https://nxp.wd3.myworkdayjobs.com/wday/cxs/nxp/careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '贝莱德 BlackRock', 'https://blackrock.wd1.myworkdayjobs.com/wday/cxs/blackrock/BlackRock_Professional/jobs', 'official', 'workday', 'http', 'foreign', '金融·资管', '贝莱德 BlackRock（金融·资管，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://blackrock.wd1.myworkdayjobs.com/wday/cxs/blackrock/BlackRock_Professional/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Stellantis', 'https://stellantis.wd3.myworkdayjobs.com/wday/cxs/stellantis/External_Career_Site_ID01/jobs', 'official', 'workday', 'http', 'foreign', '汽车', 'Stellantis（汽车，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://stellantis.wd3.myworkdayjobs.com/wday/cxs/stellantis/External_Career_Site_ID01/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '安波福 Aptiv', 'https://aptiv.wd5.myworkdayjobs.com/wday/cxs/aptiv/APTIV_CAREERS/jobs', 'official', 'workday', 'http', 'foreign', '汽车零部件', '安波福 Aptiv（汽车零部件，probe live 探活 在华 189 岗）'
where not exists (select 1 from sources where source_url = 'https://aptiv.wd5.myworkdayjobs.com/wday/cxs/aptiv/APTIV_CAREERS/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '博格华纳 BorgWarner', 'https://borgwarner.wd5.myworkdayjobs.com/wday/cxs/borgwarner/BorgWarner_Careers/jobs', 'official', 'workday', 'http', 'foreign', '汽车零部件', '博格华纳 BorgWarner（汽车零部件，probe live 探活 在华 45 岗）'
where not exists (select 1 from sources where source_url = 'https://borgwarner.wd5.myworkdayjobs.com/wday/cxs/borgwarner/BorgWarner_Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '史赛克 Stryker', 'https://stryker.wd1.myworkdayjobs.com/wday/cxs/stryker/StrykerCareers/jobs', 'official', 'workday', 'http', 'foreign', '医疗器械', '史赛克 Stryker（医疗器械，probe live 探活 在华 21 岗）'
where not exists (select 1 from sources where source_url = 'https://stryker.wd1.myworkdayjobs.com/wday/cxs/stryker/StrykerCareers/jobs');

-- BD 碧迪 已剔除：其 Workday 是 USA 专属 site，在华岗为 Humacao（波多黎各）误判，真实在华=0。
insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '百特 Baxter', 'https://baxter.wd1.myworkdayjobs.com/wday/cxs/baxter/baxter/jobs', 'official', 'workday', 'http', 'foreign', '医疗', '百特 Baxter（医疗，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://baxter.wd1.myworkdayjobs.com/wday/cxs/baxter/baxter/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '亿滋 Mondelez', 'https://mdlz.wd3.myworkdayjobs.com/wday/cxs/mdlz/External/jobs', 'official', 'workday', 'http', 'foreign', '消费·食品', '亿滋 Mondelez（消费·食品，probe live 探活 在华 58 岗）'
where not exists (select 1 from sources where source_url = 'https://mdlz.wd3.myworkdayjobs.com/wday/cxs/mdlz/External/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '卡夫亨氏 Kraft Heinz', 'https://heinz.wd1.myworkdayjobs.com/wday/cxs/heinz/KraftHeinz_Careers/jobs', 'official', 'workday', 'http', 'foreign', '消费·食品', '卡夫亨氏 Kraft Heinz（消费·食品，probe live 探活 在华 16 岗）'
where not exists (select 1 from sources where source_url = 'https://heinz.wd1.myworkdayjobs.com/wday/cxs/heinz/KraftHeinz_Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '空气产品 Air Products', 'https://airproducts.wd5.myworkdayjobs.com/wday/cxs/airproducts/AP0001/jobs', 'official', 'workday', 'http', 'foreign', '化工·气体', '空气产品 Air Products（化工·气体，probe live 探活 在华 45 岗）'
where not exists (select 1 from sources where source_url = 'https://airproducts.wd5.myworkdayjobs.com/wday/cxs/airproducts/AP0001/jobs');

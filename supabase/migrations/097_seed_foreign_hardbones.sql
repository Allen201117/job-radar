-- 097 — 外企100强「硬骨头」第二/三轮（probe.py live 探活通过，仅含真返回在华岗位的源）
-- 攻坚自建/Oracle/多站点 Workday 巨头：curl 跟踪招聘页 + grep 后端 host + 发现真实 site/siteNumber。
-- 文件名用 _seed_foreign_hardbones 后缀（区别于并行域内扩源的 _seed_probed_sources，避免迁移文件撞名丢内容）。
-- 含原 095/096 被并行 session 覆盖前的外企源（Thermo Fisher/MMC/Baxter/Dell/Nike/Danaher）+ 新增 Nokia/Honeywell/J&J。
-- 去重：MMC 同租户多站点取并集最大者；Dell/Nokia/Honeywell Oracle 取确认的 CX_1（careers 页自指）。
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Johnson & Johnson 强生', 'https://jj.wd5.myworkdayjobs.com/wday/cxs/jj/JJ/jobs', 'official', 'workday', 'http', 'foreign', '医药·医疗器械', 'Johnson & Johnson 强生（医药·医疗器械，probe live 探活 在华 242 岗）'
where not exists (select 1 from sources where source_url = 'https://jj.wd5.myworkdayjobs.com/wday/cxs/jj/JJ/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Thermo Fisher 赛默飞', 'https://thermofisher.wd5.myworkdayjobs.com/wday/cxs/thermofisher/ThermofisherCareers/jobs', 'official', 'workday', 'http', 'foreign', '生命科学', 'Thermo Fisher 赛默飞（生命科学，probe live 探活 在华 251 岗）'
where not exists (select 1 from sources where source_url = 'https://thermofisher.wd5.myworkdayjobs.com/wday/cxs/thermofisher/ThermofisherCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Danaher 丹纳赫', 'https://danaher.wd1.myworkdayjobs.com/wday/cxs/danaher/DanaherJobs/jobs', 'official', 'workday', 'http', 'foreign', '生命科学', 'Danaher 丹纳赫（生命科学，probe live 探活 在华 112 岗）'
where not exists (select 1 from sources where source_url = 'https://danaher.wd1.myworkdayjobs.com/wday/cxs/danaher/DanaherJobs/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Nike', 'https://nike.wd1.myworkdayjobs.com/wday/cxs/nike/nke/jobs', 'official', 'workday', 'http', 'foreign', '消费·运动', 'Nike（消费·运动，probe live 探活 在华 83 岗）'
where not exists (select 1 from sources where source_url = 'https://nike.wd1.myworkdayjobs.com/wday/cxs/nike/nke/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Marsh McLennan 威达信', 'https://mmc.wd1.myworkdayjobs.com/wday/cxs/mmc/Mmc/jobs', 'official', 'workday', 'http', 'foreign', '金融·保险经纪', 'Marsh McLennan 威达信（金融·保险经纪，probe live 探活 在华 35 岗）'
where not exists (select 1 from sources where source_url = 'https://mmc.wd1.myworkdayjobs.com/wday/cxs/mmc/Mmc/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Honeywell 霍尼韦尔', 'https://ibqbjb.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1', 'official', 'oracle', 'http', 'foreign', '工业·航空', 'Honeywell 霍尼韦尔（工业·航空，probe live 探活 在华 19 岗）'
where not exists (select 1 from sources where source_url = 'https://ibqbjb.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Nokia 诺基亚', 'https://fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1', 'official', 'oracle', 'http', 'foreign', '电信设备', 'Nokia 诺基亚（电信设备，probe live 探活 在华 3 岗；careers.nokia.com 自指 CX_1）'
where not exists (select 1 from sources where source_url = 'https://fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Dell 戴尔', 'https://iawmqy.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1', 'official', 'oracle', 'http', 'foreign', '硬件·IT', 'Dell 戴尔（硬件·IT，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://iawmqy.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Baxter 百特', 'https://baxter.wd1.myworkdayjobs.com/wday/cxs/baxter/Baxter/jobs', 'official', 'workday', 'http', 'foreign', '医疗器械', 'Baxter 百特（医疗器械，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://baxter.wd1.myworkdayjobs.com/wday/cxs/baxter/Baxter/jobs');

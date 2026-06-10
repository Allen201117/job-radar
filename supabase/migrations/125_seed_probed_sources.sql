-- 125 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国五矿', 'https://minmetals.hotjob.cn/wt/minmetals/web/index', 'official', 'wt', 'http', 'private', '金属', '中国五矿（金属，probe live 探活 在华 259 岗）'
where not exists (select 1 from sources where source_url = 'https://minmetals.hotjob.cn/wt/minmetals/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '越秀集团', 'https://yuexiu.hotjob.cn/wt/YUEXIU/web/index', 'official', 'wt', 'http', 'private', '综合', '越秀集团（综合，probe live 探活 在华 192 岗）'
where not exists (select 1 from sources where source_url = 'https://yuexiu.hotjob.cn/wt/YUEXIU/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '哪吒汽车', 'https://hozonauto.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '汽车', '哪吒汽车（合众新能源汽车，feishu，FeishuGenericAdapter live 600 岗；slug=hozonauto=Hozon 哪吒母公司，引擎 title-verify 因名不字面匹配标疑已 live 核正）'
where not exists (select 1 from sources where source_url = 'https://hozonauto.jobs.feishu.cn/index/position');

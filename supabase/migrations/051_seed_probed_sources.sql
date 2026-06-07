-- 051 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '艾默生 Emerson', 'https://hdjq.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1001', 'official', 'oracle', 'http', 'foreign', '工业自动化', '艾默生 Emerson（工业自动化，probe live 探活 在华 38 岗）'
where not exists (select 1 from sources where source_url = 'https://hdjq.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1001');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '霍尼韦尔 Honeywell', 'https://ibqbjb.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1', 'official', 'oracle', 'http', 'foreign', '工业·航空', '霍尼韦尔 Honeywell（工业·航空，probe live 探活 在华 17 岗）'
where not exists (select 1 from sources where source_url = 'https://ibqbjb.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '美国运通 American Express', 'https://egug.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1', 'official', 'oracle', 'http', 'foreign', '金融·支付', '美国运通 American Express（金融·支付，probe live 探活 在华 4 岗）'
where not exists (select 1 from sources where source_url = 'https://egug.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '纽约梅隆银行 BNY Mellon', 'https://eofe.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1001', 'official', 'oracle', 'http', 'foreign', '金融·资管', '纽约梅隆银行 BNY Mellon（金融·资管，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://eofe.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1001');

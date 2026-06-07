-- 042 — 中国私企模块扩源（Moka 批 2）：MokaAdapter 渲染后解析 DOM，jd_url={base}#/job/{uuid}（live 验证）
-- crawl_method=playwright，segment='private'+industry。Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁德时代 CATL', 'https://app.mokahr.com/campus-recruitment/catlhr/148948', 'official', 'moka', 'playwright', 'private', '新能源·电池',
       '宁德时代（新能源·电池，Moka，渲染 DOM 解析，live 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/catlhr/148948');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Shopee', 'https://app.mokahr.com/apply/shopee/2963', 'official', 'moka', 'playwright', 'private', '跨境电商',
       'Shopee（跨境电商，Moka，渲染 DOM 解析，live 37 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/shopee/2963');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '高途', 'https://app.mokahr.com/campus-recruitment/bjhl/102145', 'official', 'moka', 'playwright', 'private', '教育',
       '高途（教育，Moka，渲染 DOM 解析，live 34 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/bjhl/102145');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '寒武纪', 'https://app.mokahr.com/campus-recruitment/cambricon/44201', 'official', 'moka', 'playwright', 'private', 'AI芯片',
       '寒武纪（AI芯片，Moka，渲染 DOM 解析，live 21 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/cambricon/44201');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '最右', 'https://app.mokahr.com/apply/xiaochuankeji/3519', 'official', 'moka', 'playwright', 'private', '互联网',
       '最右（互联网，Moka，渲染 DOM 解析，live 14 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/xiaochuankeji/3519');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '第四范式 4Paradigm', 'https://app.mokahr.com/apply/4paradigm/5072', 'official', 'moka', 'playwright', 'private', 'AI',
       '第四范式（AI，Moka，渲染 DOM 解析，live 9 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/4paradigm/5072');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '极米科技 XGIMI', 'https://app.mokahr.com/campus_apply/xgimi/5463', 'official', 'moka', 'playwright', 'private', '消费电子',
       '极米科技（消费电子，Moka，渲染 DOM 解析，live 6 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/xgimi/5463');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '飞鱼科技', 'https://app.mokahr.com/campus_apply/feiyu/142123', 'official', 'moka', 'playwright', 'private', '游戏',
       '飞鱼科技（游戏，Moka，渲染 DOM 解析，live 6 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/feiyu/142123');

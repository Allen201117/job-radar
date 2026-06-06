-- 039 — 中国私企模块扩源（Moka）：MokaAdapter 重写为「渲染后解析 DOM」（Moka 接口数据加密，拦截 JSON 拿不到明文）
-- 岗位卡渲染为 a[href*='#/job/{uuid}']，jd_url = {base}#/job/{uuid}（hash 路由真实 per-job，live 验证）。
-- crawl_method=playwright。带 segment='private'+industry。Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'SHEIN', 'https://app.mokahr.com/apply/shein/2933', 'official', 'moka', 'playwright', 'private', '跨境电商',
       'SHEIN（跨境电商，Moka，渲染后 DOM 解析，live 37 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/shein/2933');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '雪球', 'https://app.mokahr.com/apply/xueqiu/3591', 'official', 'moka', 'playwright', 'private', '互联网金融',
       '雪球（互联网金融，Moka，渲染后 DOM 解析，live 14 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/xueqiu/3591');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '金山办公 WPS', 'https://app.mokahr.com/apply/wps/3471', 'official', 'moka', 'playwright', 'private', '软件',
       '金山办公 WPS（软件，Moka，渲染后 DOM 解析，live 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/wps/3471');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '好未来', 'https://app.mokahr.com/campus-recruitment/tal/146099', 'official', 'moka', 'playwright', 'private', '教育',
       '好未来（教育，Moka，渲染后 DOM 解析，live 33 岗·校招）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/tal/146099');

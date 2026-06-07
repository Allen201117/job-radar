-- 044 — 中国私企模块扩源（Moka 批 3）：渲染后解析 DOM，jd_url={base}#/job/{uuid}（live 验证）
-- crawl_method=playwright，segment='private'+industry。Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '携程集团 Trip.com', 'https://app.mokahr.com/campus_apply/trip/37757', 'official', 'moka', 'playwright', 'private', '在线旅游',
       '携程集团（在线旅游，Moka，渲染 DOM 解析，live 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/trip/37757');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '虎牙 Huya', 'https://app.mokahr.com/apply/huya/4111', 'official', 'moka', 'playwright', 'private', '直播',
       '虎牙（直播，Moka，渲染 DOM 解析，live 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/huya/4111');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '希望学', 'https://app.mokahr.com/campus-recruitment/xiwang/146380', 'official', 'moka', 'playwright', 'private', '教育',
       '希望学（教育，Moka，渲染 DOM 解析，live 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/xiwang/146380');

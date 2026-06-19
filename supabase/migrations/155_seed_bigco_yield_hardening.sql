-- 155 — 大厂浏览器源产出硬化 + 顺丰社招重试（2026-06-19 live 验证）。
-- 快手：Ant 分页完整拦截，单跑 39 -> 1437 个在华社招。
-- 比亚迪：公开 queryList 拉全 2163 行，官方 Vue Router 批量生成 AES 加密详情 URL；
--          过滤海外/空地点后单跑 19 -> 2037 个在华社招。
-- 顺丰：HTTPS 老社招站恢复可用；SearchJob.do 当前 2143 岗。持续并发全量会返回瞬时
--       空页/非 JSON，因此低频顺序抓最近 50 页，live 产出 499 个在华岗位。

update sources
set notes = '快手（2026-06-19 live 验证：Ant 全分页签名拦截，单跑 1437 个在华社招；逐岗 hash 详情页）'
where source_url = 'https://zhaopin.kuaishou.cn/#/official/social/?workLocationCode=domestic';

update sources
set notes = '比亚迪（2026-06-19 live 验证：queryList 2163 行 + 官方 Vue Router 批量生成 AES 加密详情 URL；单跑 2037 个在华社招）'
where source_url = 'https://job.byd.com/portal/pc/#/social/socialMainPageSocial';

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '顺丰 SF Express', 'https://hr.sf-express.com/jobMainHandler/main/9999', 'official', 'sf_express', 'http', 'private', '物流/供应链', '顺丰（2026-06-19 live 验证：SearchJob.do 当前 2143 岗；低频顺序抓最近 50 页，单跑 499 个在华岗位；逐岗 JobSearchById/{id},{positionType}）'
where not exists (
  select 1 from sources
  where source_url = 'https://hr.sf-express.com/jobMainHandler/main/9999'
);

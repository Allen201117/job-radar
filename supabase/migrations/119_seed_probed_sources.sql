-- 119 — 扩源（小红书自建门户，新 adapter xiaohongshu，live 全量验证 1214 岗）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url。
-- 自建门户公开接口 pageQueryPosition（零浏览器 httpx），社招 862/校招 352/实习与校招重叠去重；
-- 逐岗稳定深链 job.xiaohongshu.com/{social|campus}/position/{id}（render-verify 过质量门）。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '小红书', 'https://job.xiaohongshu.com/', 'official', 'xiaohongshu', 'http', 'private', '互联网·社区电商', '小红书（互联网·社区电商，自建门户 pageQueryPosition 零浏览器，live 全量 1214 岗：社862/校352）'
where not exists (select 1 from sources where source_url = 'https://job.xiaohongshu.com/');

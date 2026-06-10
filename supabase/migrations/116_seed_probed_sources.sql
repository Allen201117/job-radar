-- 116 — 扩源（网易自建门户 adapter=netease，probe live 探活 789 岗）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '网易', 'https://hr.163.com/job-list.html', 'official', 'netease', 'http', 'private', '互联网·游戏', '网易（互联网·游戏，probe live 探活 789 岗，hr.163.com queryPage 公开接口，零浏览器）'
where not exists (select 1 from sources where source_url = 'https://hr.163.com/job-list.html');

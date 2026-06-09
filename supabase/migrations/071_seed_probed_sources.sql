-- 071 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '库洛游戏 Kuro', 'https://kurogame.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '游戏', '库洛游戏 Kuro（游戏，probe live 探活 在华 35 岗）'
where not exists (select 1 from sources where source_url = 'https://kurogame.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '莉莉丝游戏 Lilith', 'https://lilithgames.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '游戏', '莉莉丝游戏 Lilith（游戏，probe live 探活 在华 40 岗）'
where not exists (select 1 from sources where source_url = 'https://lilithgames.jobs.feishu.cn/index/position');

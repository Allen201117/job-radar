-- 073 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '满帮集团 Manbang', 'https://app.mokahr.com/social-recruitment/manbang/46269', 'official', 'moka', 'playwright', 'private', '物流科技', '满帮集团 Manbang（物流科技，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/manbang/46269');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '后摩智能 Houmo', 'https://houmo.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', 'AI芯片·具身智能', '后摩智能 Houmo（AI芯片·具身智能，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://houmo.jobs.feishu.cn/index/position');

-- 065 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '零跑汽车', 'https://leapmotor.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '汽车', '零跑汽车（汽车，probe live 探活 在华 70 岗）'
where not exists (select 1 from sources where source_url = 'https://leapmotor.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '欣旺达', 'https://sunwoda.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '电池', '欣旺达（电池，probe live 探活 在华 65 岗）'
where not exists (select 1 from sources where source_url = 'https://sunwoda.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '国轩高科', 'https://gotion.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '电池', '国轩高科（电池，probe live 探活 在华 55 岗）'
where not exists (select 1 from sources where source_url = 'https://gotion.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '双汇', 'https://shuanghui.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '食品', '双汇（食品，probe live 探活 在华 8 岗）'
where not exists (select 1 from sources where source_url = 'https://shuanghui.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '周大福', 'https://ctf.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '珠宝', '周大福（珠宝，probe live 探活 在华 44 岗）'
where not exists (select 1 from sources where source_url = 'https://ctf.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '科大讯飞', 'https://iflytek.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', 'AI·语音', '科大讯飞（AI·语音，probe live 探活 在华 73 岗）'
where not exists (select 1 from sources where source_url = 'https://iflytek.zhiye.com/social/jobs');

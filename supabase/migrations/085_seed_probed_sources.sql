-- 085 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '招商证券 CMS', 'https://wecruit.hotjob.cn/SU629dbc0c0dcad452299bc0f7/pb/social.html', 'official', 'hotjob', 'playwright', 'private', '证券', '招商证券 CMS（证券，probe live 探活 在华 54 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU629dbc0c0dcad452299bc0f7/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华润电力 CR Power', 'https://wecruit.hotjob.cn/SU6149ff530dcad47003d01511/pb/social.html', 'official', 'hotjob', 'playwright', 'private', '能源电力', '华润电力 CR Power（能源电力，probe live 探活 在华 35 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6149ff530dcad47003d01511/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云南白药 YNBY', 'https://wecruit.hotjob.cn/SU6136b970bef57c3b638162c4/pb/social.html', 'official', 'hotjob', 'playwright', 'private', '医药健康', '云南白药 YNBY（医药健康，probe live 探活 在华 8 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6136b970bef57c3b638162c4/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '迪卡侬中国 Decathlon', 'https://wecruit.hotjob.cn/SU64631fe6bef57c0907f133c4/pb/social.html', 'official', 'hotjob', 'playwright', 'private', '消费·运动零售', '迪卡侬中国 Decathlon（消费·运动零售，probe live 探活 在华 56 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU64631fe6bef57c0907f133c4/pb/social.html');

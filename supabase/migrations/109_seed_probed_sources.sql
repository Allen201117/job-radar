-- 109 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '京东集团', 'https://jd.hotjob.cn/SU6923bd7fd14e321454349e91/pb/social.html', 'official', 'hotjob', 'http', 'private', '互联网', '京东集团（互联网，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://jd.hotjob.cn/SU6923bd7fd14e321454349e91/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '京东集团', 'https://jd.hotjob.cn/SU6923bd7fd14e321454349e91/pb/school.html', 'official', 'hotjob', 'http', 'private', '互联网', '京东集团（互联网，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://jd.hotjob.cn/SU6923bd7fd14e321454349e91/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海亮集团', 'https://hailiang.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '有色金属', '海亮集团（有色金属，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://hailiang.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '创维集团', 'https://skyworth.hotjob.cn/SU668b8b251c240e2e76ea71d8/pb/school.html', 'official', 'hotjob', 'http', 'private', '家电', '创维集团（家电，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://skyworth.hotjob.cn/SU668b8b251c240e2e76ea71d8/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '物美科技集团', 'https://wumart.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '零售', '物美科技集团（零售，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://wumart.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '北京蓝色光标数据科技', 'https://bluefocus.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '营销传播', '北京蓝色光标数据科技（营销传播，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://bluefocus.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '极兔速递', 'https://jtexpress.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '物流', '极兔速递（物流，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://jtexpress.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广东小鹏汽车科技', 'https://xiaopeng.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '汽车', '广东小鹏汽车科技（汽车，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://xiaopeng.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海龙旗科技', 'https://longcheer.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '智能制造', '上海龙旗科技（智能制造，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://longcheer.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '安克创新', 'https://anker-in.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '消费电子', '安克创新（消费电子，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://anker-in.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云南白药', 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/social.html', 'official', 'hotjob', 'http', 'private', '中药', '云南白药（中药，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云南白药', 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/school.html', 'official', 'hotjob', 'http', 'private', '中药', '云南白药（中药，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云南白药', 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/interns.html', 'official', 'hotjob', 'http', 'private', '中药', '云南白药（中药，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '莉莉丝', 'https://lilithgames.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '游戏', '莉莉丝（游戏，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://lilithgames.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '商汤科技', 'https://sensetime.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '人工智能', '商汤科技（人工智能，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://sensetime.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '奇安信', 'https://qianxin.hotjob.cn/SU6588fd1a1eb80578ea63e804/pb/social.html', 'official', 'hotjob', 'http', 'private', '网络安全', '奇安信（网络安全，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://qianxin.hotjob.cn/SU6588fd1a1eb80578ea63e804/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '奇安信', 'https://qianxin.hotjob.cn/SU6588fd1a1eb80578ea63e804/pb/interns.html', 'official', 'hotjob', 'http', 'private', '网络安全', '奇安信（网络安全，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://qianxin.hotjob.cn/SU6588fd1a1eb80578ea63e804/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '歌尔股份', 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/social.html', 'official', 'hotjob', 'http', 'private', '智能制造', '歌尔股份（智能制造，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '歌尔股份', 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/school.html', 'official', 'hotjob', 'http', 'private', '智能制造', '歌尔股份（智能制造，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '歌尔股份', 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/interns.html', 'official', 'hotjob', 'http', 'private', '智能制造', '歌尔股份（智能制造，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国中车', 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/social.html', 'official', 'hotjob', 'http', 'private', '轨道交通', '中国中车（轨道交通，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国中车', 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/school.html', 'official', 'hotjob', 'http', 'private', '轨道交通', '中国中车（轨道交通，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国中车', 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/interns.html', 'official', 'hotjob', 'http', 'private', '轨道交通', '中国中车（轨道交通，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '天赐材料', 'https://tinci.hotjob.cn/SU62c3b55d2f9d241e4c8e260f/pb/social.html', 'official', 'hotjob', 'http', 'private', '锂电', '天赐材料（锂电，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://tinci.hotjob.cn/SU62c3b55d2f9d241e4c8e260f/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '天赐材料', 'https://tinci.hotjob.cn/SU62c3b55d2f9d241e4c8e260f/pb/school.html', 'official', 'hotjob', 'http', 'private', '锂电', '天赐材料（锂电，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://tinci.hotjob.cn/SU62c3b55d2f9d241e4c8e260f/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '天赐材料', 'https://tinci.hotjob.cn/SU62c3b55d2f9d241e4c8e260f/pb/interns.html', 'official', 'hotjob', 'http', 'private', '锂电', '天赐材料（锂电，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://tinci.hotjob.cn/SU62c3b55d2f9d241e4c8e260f/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '隆基绿能', 'https://longi.hotjob.cn/SU649d2f9c0dcad4644b43df7e/pb/social.html', 'official', 'hotjob', 'http', 'private', '光伏', '隆基绿能（光伏，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://longi.hotjob.cn/SU649d2f9c0dcad4644b43df7e/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '隆基绿能', 'https://longi.hotjob.cn/SU649d2f9c0dcad4644b43df7e/pb/school.html', 'official', 'hotjob', 'http', 'private', '光伏', '隆基绿能（光伏，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://longi.hotjob.cn/SU649d2f9c0dcad4644b43df7e/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海天味业', 'https://wecruit.hotjob.cn/SU6322dfb70dcad46a862da4c5/pb/social.html', 'official', 'hotjob', 'http', 'private', '食品', '海天味业（食品，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6322dfb70dcad46a862da4c5/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海天味业', 'https://wecruit.hotjob.cn/SU6322dfb70dcad46a862da4c5/pb/school.html', 'official', 'hotjob', 'http', 'private', '食品', '海天味业（食品，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6322dfb70dcad46a862da4c5/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海天味业', 'https://wecruit.hotjob.cn/SU6322dfb70dcad46a862da4c5/pb/interns.html', 'official', 'hotjob', 'http', 'private', '食品', '海天味业（食品，probe live 探活 在华 4 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6322dfb70dcad46a862da4c5/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海底捞', 'https://haidilao.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '餐饮', '海底捞（餐饮，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://haidilao.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '柳工', 'https://liugong.hotjob.cn/SU6132e87abef57c3b637dcb71/pb/social.html', 'official', 'hotjob', 'http', 'private', '工程机械', '柳工（工程机械，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://liugong.hotjob.cn/SU6132e87abef57c3b637dcb71/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '柳工', 'https://liugong.hotjob.cn/SU6132e87abef57c3b637dcb71/pb/school.html', 'official', 'hotjob', 'http', 'private', '工程机械', '柳工（工程机械，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://liugong.hotjob.cn/SU6132e87abef57c3b637dcb71/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '蔚来汽车', 'https://nio.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '汽车', '蔚来汽车（汽车，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://nio.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '小马智行', 'https://ponyai.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '自动驾驶', '小马智行（自动驾驶，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://ponyai.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁德新能源', 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/social.html', 'official', 'hotjob', 'http', 'private', '锂电', '宁德新能源（锂电，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁德新能源', 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/school.html', 'official', 'hotjob', 'http', 'private', '锂电', '宁德新能源（锂电，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁德新能源', 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/interns.html', 'official', 'hotjob', 'http', 'private', '锂电', '宁德新能源（锂电，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/interns.html');

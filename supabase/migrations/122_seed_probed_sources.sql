-- 122 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
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
select '长城汽车', 'https://gwm.hotjob.cn/wt/GWM/web/index', 'official', 'wt', 'http', 'private', '汽车', '长城汽车（汽车，probe live 探活 在华 3290 岗）'
where not exists (select 1 from sources where source_url = 'https://gwm.hotjob.cn/wt/GWM/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '内蒙古伊利实业集团', 'https://yili.hotjob.cn/wt/yili/web/index', 'official', 'wt', 'http', 'private', '食品', '内蒙古伊利实业集团（食品，probe live 探活 在华 884 岗）'
where not exists (select 1 from sources where source_url = 'https://yili.hotjob.cn/wt/yili/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'TCL实业控股', 'https://tcl.hotjob.cn/wt/TCL/web/index', 'official', 'wt', 'http', 'private', '家电', 'TCL实业控股（家电，probe live 探活 在华 1508 岗）'
where not exists (select 1 from sources where source_url = 'https://tcl.hotjob.cn/wt/TCL/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '万达控股集团', 'https://wanda.hotjob.cn/wt/wanda/web/index', 'official', 'wt', 'http', 'private', '地产', '万达控股集团（地产，probe live 探活 在华 568 岗）'
where not exists (select 1 from sources where source_url = 'https://wanda.hotjob.cn/wt/wanda/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新疆特变电工集团', 'https://tbea.hotjob.cn/wt/TBEA/web/index', 'official', 'wt', 'http', 'private', '电气', '新疆特变电工集团（电气，probe live 探活 在华 1529 岗）'
where not exists (select 1 from sources where source_url = 'https://tbea.hotjob.cn/wt/TBEA/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '创维集团', 'https://skyworth.hotjob.cn/SU668b8b251c240e2e76ea71d8/pb/school.html', 'official', 'hotjob', 'http', 'private', '家电', '创维集团（家电，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://skyworth.hotjob.cn/SU668b8b251c240e2e76ea71d8/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '浙江华友钴业', 'https://huayou.hotjob.cn/wt/HUAYOU/web/index', 'official', 'wt', 'http', 'private', '锂电', '浙江华友钴业（锂电，probe live 探活 在华 419 岗）'
where not exists (select 1 from sources where source_url = 'https://huayou.hotjob.cn/wt/HUAYOU/web/index');

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
select '郑州宇通企业集团', 'https://yutong.hotjob.cn/wt/yutong/web/index', 'official', 'wt', 'http', 'private', '汽车', '郑州宇通企业集团（汽车，probe live 探活 在华 19 岗）'
where not exists (select 1 from sources where source_url = 'https://yutong.hotjob.cn/wt/yutong/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中伟新材料', 'https://cngr.hotjob.cn/wt/CNGR/web/index', 'official', 'wt', 'http', 'private', '锂电', '中伟新材料（锂电，probe live 探活 在华 495 岗）'
where not exists (select 1 from sources where source_url = 'https://cngr.hotjob.cn/wt/CNGR/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广东小鹏汽车科技', 'https://xiaopeng.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '汽车', '广东小鹏汽车科技（汽车，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://xiaopeng.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海龙旗科技', 'https://longcheer.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '智能制造', '上海龙旗科技（智能制造，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://longcheer.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '江苏润阳新能源科技', 'https://runergy.hotjob.cn/wt/RUNERGY/web/index', 'official', 'wt', 'http', 'private', '光伏', '江苏润阳新能源科技（光伏，probe live 探活 在华 70 岗）'
where not exists (select 1 from sources where source_url = 'https://runergy.hotjob.cn/wt/RUNERGY/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '安克创新', 'https://anker-in.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '消费电子', '安克创新（消费电子，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://anker-in.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云南白药', 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/social.html', 'official', 'hotjob', 'http', 'private', '中药', '云南白药（中药，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云南白药', 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/school.html', 'official', 'hotjob', 'http', 'private', '中药', '云南白药（中药，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云南白药', 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/interns.html', 'official', 'hotjob', 'http', 'private', '中药', '云南白药（中药，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '用友网络', 'https://yonyou.hotjob.cn/wt/yonyou/web/index', 'official', 'wt', 'http', 'private', '软件', '用友网络（软件，probe live 探活 在华 312 岗）'
where not exists (select 1 from sources where source_url = 'https://yonyou.hotjob.cn/wt/yonyou/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '奇安信', 'https://qianxin.hotjob.cn/SU6588fd1a1eb80578ea63e804/pb/social.html', 'official', 'hotjob', 'http', 'private', '网络安全', '奇安信（网络安全，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://qianxin.hotjob.cn/SU6588fd1a1eb80578ea63e804/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '奇安信', 'https://qianxin.hotjob.cn/SU6588fd1a1eb80578ea63e804/pb/interns.html', 'official', 'hotjob', 'http', 'private', '网络安全', '奇安信（网络安全，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://qianxin.hotjob.cn/SU6588fd1a1eb80578ea63e804/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '莉莉丝', 'https://lilithgames.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '游戏', '莉莉丝（游戏，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://lilithgames.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '商汤科技', 'https://sensetime.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '人工智能', '商汤科技（人工智能，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://sensetime.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '歌尔股份', 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/social.html', 'official', 'hotjob', 'http', 'private', '智能制造', '歌尔股份（智能制造，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '歌尔股份', 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/school.html', 'official', 'hotjob', 'http', 'private', '智能制造', '歌尔股份（智能制造，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '歌尔股份', 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/interns.html', 'official', 'hotjob', 'http', 'private', '智能制造', '歌尔股份（智能制造，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '立讯精密', 'https://luxshare.hotjob.cn/wt/LUXSHARE/web/index', 'official', 'wt', 'http', 'private', '智能制造', '立讯精密（智能制造，probe live 探活 在华 570 岗）'
where not exists (select 1 from sources where source_url = 'https://luxshare.hotjob.cn/wt/LUXSHARE/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国中车', 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/social.html', 'official', 'hotjob', 'http', 'private', '轨道交通', '中国中车（轨道交通，probe live 探活 在华 12 岗）'
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
select '隆基绿能', 'https://longi.hotjob.cn/SU649d2f9c0dcad4644b43df7e/pb/social.html', 'official', 'hotjob', 'http', 'private', '光伏', '隆基绿能（光伏，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://longi.hotjob.cn/SU649d2f9c0dcad4644b43df7e/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '隆基绿能', 'https://longi.hotjob.cn/SU649d2f9c0dcad4644b43df7e/pb/school.html', 'official', 'hotjob', 'http', 'private', '光伏', '隆基绿能（光伏，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://longi.hotjob.cn/SU649d2f9c0dcad4644b43df7e/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海天味业', 'https://wecruit.hotjob.cn/SU6322dfb70dcad46a862da4c5/pb/social.html', 'official', 'hotjob', 'http', 'private', '食品', '海天味业（食品，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6322dfb70dcad46a862da4c5/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海天味业', 'https://wecruit.hotjob.cn/SU6322dfb70dcad46a862da4c5/pb/school.html', 'official', 'hotjob', 'http', 'private', '食品', '海天味业（食品，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6322dfb70dcad46a862da4c5/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海天味业', 'https://wecruit.hotjob.cn/SU6322dfb70dcad46a862da4c5/pb/interns.html', 'official', 'hotjob', 'http', 'private', '食品', '海天味业（食品，probe live 探活 在华 4 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6322dfb70dcad46a862da4c5/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '飞鹤', 'https://feihe.hotjob.cn/wt/feihe/web/index', 'official', 'wt', 'http', 'private', '食品', '飞鹤（食品，probe live 探活 在华 33 岗）'
where not exists (select 1 from sources where source_url = 'https://feihe.hotjob.cn/wt/feihe/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '伊利股份', 'https://yili.hotjob.cn/wt/yili/web/index', 'official', 'wt', 'http', 'private', '食品', '伊利股份（食品，probe live 探活 在华 884 岗）'
where not exists (select 1 from sources where source_url = 'https://yili.hotjob.cn/wt/yili/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海底捞', 'https://haidilao.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '餐饮', '海底捞（餐饮，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://haidilao.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '李宁', 'https://lining.hotjob.cn/wt/lining/web/index', 'official', 'wt', 'http', 'private', '服装', '李宁（服装，probe live 探活 在华 30 岗）'
where not exists (select 1 from sources where source_url = 'https://lining.hotjob.cn/wt/lining/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '柳工', 'https://liugong.hotjob.cn/SU6132e87abef57c3b637dcb71/pb/social.html', 'official', 'hotjob', 'http', 'private', '工程机械', '柳工（工程机械，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://liugong.hotjob.cn/SU6132e87abef57c3b637dcb71/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '柳工', 'https://liugong.hotjob.cn/SU6132e87abef57c3b637dcb71/pb/school.html', 'official', 'hotjob', 'http', 'private', '工程机械', '柳工（工程机械，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://liugong.hotjob.cn/SU6132e87abef57c3b637dcb71/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中联重科', 'https://zoomlion.hotjob.cn/wt/zoomlion/web/index', 'official', 'wt', 'http', 'private', '工程机械', '中联重科（工程机械，probe live 探活 在华 867 岗）'
where not exists (select 1 from sources where source_url = 'https://zoomlion.hotjob.cn/wt/zoomlion/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '蔚来汽车', 'https://nio.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '汽车', '蔚来汽车（汽车，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://nio.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁德新能源', 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/social.html', 'official', 'hotjob', 'http', 'private', '锂电', '宁德新能源（锂电，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁德新能源', 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/school.html', 'official', 'hotjob', 'http', 'private', '锂电', '宁德新能源（锂电，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁德新能源', 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/interns.html', 'official', 'hotjob', 'http', 'private', '锂电', '宁德新能源（锂电，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '小马智行', 'https://ponyai.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '自动驾驶', '小马智行（自动驾驶，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://ponyai.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '格科微', 'https://galaxycore.hotjob.cn/wt/GALAXYCORE/web/index', 'official', 'wt', 'http', 'private', '半导体', '格科微（半导体，probe live 探活 在华 136 岗）'
where not exists (select 1 from sources where source_url = 'https://galaxycore.hotjob.cn/wt/GALAXYCORE/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '雷士照明', 'https://nvc.hotjob.cn/wt/NVC/web/index', 'official', 'wt', 'http', 'private', '照明', '雷士照明（照明，NVC 品牌，probe live 探活 在华 42 岗；原引擎误标得邦照明，已 live 核正=雷士）'
where not exists (select 1 from sources where source_url = 'https://nvc.hotjob.cn/wt/NVC/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'TCL华星', 'https://csot.hotjob.cn/wt/CSOT/web/index', 'official', 'wt', 'http', 'private', '显示面板', 'TCL华星（显示面板，probe live 探活 在华 13 岗）'
where not exists (select 1 from sources where source_url = 'https://csot.hotjob.cn/wt/CSOT/web/index');

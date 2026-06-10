-- 127 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '爱康国宾健康管理集团有限公司', 'https://ikang.hotjob.cn/SU6548656f6202cc6e3a56621b/pb/social.html', 'official', 'hotjob', 'http', 'private', '医疗服务', '爱康国宾健康管理集团有限公司（医疗服务，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://ikang.hotjob.cn/SU6548656f6202cc6e3a56621b/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '爱康国宾健康管理集团有限公司', 'https://ikang.hotjob.cn/SU6548656f6202cc6e3a56621b/pb/school.html', 'official', 'hotjob', 'http', 'private', '医疗服务', '爱康国宾健康管理集团有限公司（医疗服务，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://ikang.hotjob.cn/SU6548656f6202cc6e3a56621b/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '康师傅控股有限公司', 'https://masterkong.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '方便食品/饮料', '康师傅控股有限公司（方便食品/饮料，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://masterkong.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '燕京啤酒股份有限公司', 'https://yanjingbeer.hotjob.cn/wt/yanjingbeer/web/index', 'official', 'wt', 'http', 'private', '啤酒', '燕京啤酒股份有限公司（啤酒，probe live 探活 在华 76 岗）'
where not exists (select 1 from sources where source_url = 'https://yanjingbeer.hotjob.cn/wt/yanjingbeer/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '霸王茶姬（北京）餐饮管理有限公司', 'https://chagee.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '新茶饮', '霸王茶姬（北京）餐饮管理有限公司（新茶饮，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://chagee.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '晶科能源控股有限公司', 'https://jks.hotjob.cn/wt/JKS/web/index', 'official', 'wt', 'http', 'private', '光伏组件', '晶科能源控股有限公司（光伏组件，probe live 探活 在华 95 岗）'
where not exists (select 1 from sources where source_url = 'https://jks.hotjob.cn/wt/JKS/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '一汽-大众汽车有限公司', 'https://faw-zhaopin.hotjob.cn/SU64bb3226bef57c7e364a7a2c/pb/social.html', 'official', 'hotjob', 'http', 'private', '汽车整车/合资', '一汽-大众汽车有限公司（汽车整车/合资，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://faw-zhaopin.hotjob.cn/SU64bb3226bef57c7e364a7a2c/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '一汽-大众汽车有限公司', 'https://faw-zhaopin.hotjob.cn/SU64bb3226bef57c7e364a7a2c/pb/school.html', 'official', 'hotjob', 'http', 'private', '汽车整车/合资', '一汽-大众汽车有限公司（汽车整车/合资，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://faw-zhaopin.hotjob.cn/SU64bb3226bef57c7e364a7a2c/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '一汽-大众汽车有限公司', 'https://faw-zhaopin.hotjob.cn/SU64bb3226bef57c7e364a7a2c/pb/interns.html', 'official', 'hotjob', 'http', 'private', '汽车整车/合资', '一汽-大众汽车有限公司（汽车整车/合资，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://faw-zhaopin.hotjob.cn/SU64bb3226bef57c7e364a7a2c/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '轻舟智航科技有限公司', 'https://qcraft.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '智能驾驶/自动驾驶', '轻舟智航科技有限公司（智能驾驶/自动驾驶，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://qcraft.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东软集团股份有限公司', 'https://neusoft.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '企业软件/IT服务', '东软集团股份有限公司（企业软件/IT服务，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://neusoft.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '亚信安全', 'https://asiainfo-sec.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '电信IT/数字化', '亚信安全（电信IT/数字化，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://asiainfo-sec.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '爱奇艺股份有限公司', 'https://iq.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '长视频/影视', '爱奇艺股份有限公司（长视频/影视，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://iq.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华发股份有限公司', 'https://huafa.hotjob.cn/wt/huafa/web/index', 'official', 'wt', 'http', 'private', '房地产开发', '华发股份有限公司（房地产开发，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://huafa.hotjob.cn/wt/huafa/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '居然之家投资控股集团有限公司', 'https://juran.hotjob.cn/SU6437d44e2f9d2448ab674ec1/pb/social.html', 'official', 'hotjob', 'http', 'private', '家居建材零售', '居然之家投资控股集团有限公司（家居建材零售，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://juran.hotjob.cn/SU6437d44e2f9d2448ab674ec1/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '居然之家投资控股集团有限公司', 'https://juran.hotjob.cn/SU6437d44e2f9d2448ab674ec1/pb/school.html', 'official', 'hotjob', 'http', 'private', '家居建材零售', '居然之家投资控股集团有限公司（家居建材零售，probe live 探活 在华 4 岗）'
where not exists (select 1 from sources where source_url = 'https://juran.hotjob.cn/SU6437d44e2f9d2448ab674ec1/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '天风证券股份有限公司', 'https://tfzq.hotjob.cn/wt/tfzq/web/index', 'official', 'wt', 'http', 'private', '综合证券', '天风证券股份有限公司（综合证券，probe live 探活 在华 16 岗）'
where not exists (select 1 from sources where source_url = 'https://tfzq.hotjob.cn/wt/tfzq/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '南方基金管理股份有限公司', 'https://southernfund.hotjob.cn/wt/southernfund/web/index', 'official', 'wt', 'http', 'private', '公募基金', '南方基金管理股份有限公司（公募基金，probe live 探活 在华 25 岗）'
where not exists (select 1 from sources where source_url = 'https://southernfund.hotjob.cn/wt/southernfund/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '博时基金管理有限公司', 'https://bosera.hotjob.cn/SU65f940241c240e0a2275bda8/pb/social.html', 'official', 'hotjob', 'http', 'private', '公募基金', '博时基金管理有限公司（公募基金，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://bosera.hotjob.cn/SU65f940241c240e0a2275bda8/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '博时基金管理有限公司', 'https://bosera.hotjob.cn/SU65f940241c240e0a2275bda8/pb/school.html', 'official', 'hotjob', 'http', 'private', '公募基金', '博时基金管理有限公司（公募基金，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://bosera.hotjob.cn/SU65f940241c240e0a2275bda8/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '博时基金管理有限公司', 'https://bosera.hotjob.cn/SU65f940241c240e0a2275bda8/pb/interns.html', 'official', 'hotjob', 'http', 'private', '公募基金', '博时基金管理有限公司（公募基金，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://bosera.hotjob.cn/SU65f940241c240e0a2275bda8/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '度小满金融科技（北京）有限公司', 'https://duxiaoman.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '消费金融/金融科技', '度小满金融科技（北京）有限公司（消费金融/金融科技，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://duxiaoman.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '招联消费金融有限公司', 'https://zhaolian.hotjob.cn/wt/zhaolian/web/index', 'official', 'wt', 'http', 'private', '消费金融', '招联消费金融有限公司（消费金融，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://zhaolian.hotjob.cn/wt/zhaolian/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '三棵树涂料股份有限公司', 'https://skshu.hotjob.cn/wt/SKSHU/web/index', 'official', 'wt', 'http', 'private', '涂料/建筑涂料', '三棵树涂料股份有限公司（涂料/建筑涂料，probe live 探活 在华 47 岗）'
where not exists (select 1 from sources where source_url = 'https://skshu.hotjob.cn/wt/SKSHU/web/index');

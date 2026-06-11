-- 133 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '米其林（中国）投资有限公司', 'https://michelin.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '轮胎/橡胶', '米其林（中国）投资有限公司（轮胎/橡胶，probe live 探活 11 岗）'
where not exists (select 1 from sources where source_url = 'https://michelin.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '米其林（中国）投资有限公司', 'https://michelin.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '轮胎/橡胶', '米其林（中国）投资有限公司（轮胎/橡胶，probe live 探活 2 岗）'
where not exists (select 1 from sources where source_url = 'https://michelin.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国燃气控股有限公司', 'https://chinagasholdings.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '工业/燃气分销', '中国燃气控股有限公司（工业/燃气分销，probe live 探活 42 岗）'
where not exists (select 1 from sources where source_url = 'https://chinagasholdings.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国燃气控股有限公司', 'https://chinagasholdings.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '工业/燃气分销', '中国燃气控股有限公司（工业/燃气分销，probe live 探活 56 岗）'
where not exists (select 1 from sources where source_url = 'https://chinagasholdings.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国旺旺控股有限公司', 'https://wantwant.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '消费/零食饮料', '中国旺旺控股有限公司（消费/零食饮料，probe live 探活 126 岗）'
where not exists (select 1 from sources where source_url = 'https://wantwant.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国旺旺控股有限公司', 'https://wantwant.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '消费/零食饮料', '中国旺旺控股有限公司（消费/零食饮料，probe live 探活 2 岗）'
where not exists (select 1 from sources where source_url = 'https://wantwant.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海医药集团股份有限公司', 'https://sph.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '医药商业流通/批发分销', '上海医药集团股份有限公司（医药商业流通/批发分销，probe live 探活 85 岗）'
where not exists (select 1 from sources where source_url = 'https://sph.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海医药集团股份有限公司', 'https://sph.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '医药商业流通/批发分销', '上海医药集团股份有限公司（医药商业流通/批发分销，probe live 探活 57 岗）'
where not exists (select 1 from sources where source_url = 'https://sph.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '漱玉平民大药房连锁股份有限公司', 'https://sypm.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '连锁药店/零售药店', '漱玉平民大药房连锁股份有限公司（连锁药店/零售药店，probe live 探活 91 岗）'
where not exists (select 1 from sources where source_url = 'https://sypm.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '漱玉平民大药房连锁股份有限公司', 'https://sypm.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '连锁药店/零售药店', '漱玉平民大药房连锁股份有限公司（连锁药店/零售药店，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://sypm.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '健之佳健康连锁集团股份有限公司', 'https://jianzhijia.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '连锁药店/零售药店', '健之佳健康连锁集团股份有限公司（连锁药店/零售药店，probe live 探活 9 岗）'
where not exists (select 1 from sources where source_url = 'https://jianzhijia.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '健之佳健康连锁集团股份有限公司', 'https://jianzhijia.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '连锁药店/零售药店', '健之佳健康连锁集团股份有限公司（连锁药店/零售药店，probe live 探活 2 岗）'
where not exists (select 1 from sources where source_url = 'https://jianzhijia.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '扬翔股份有限公司', 'https://yangxiang.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '农牧饲料/养殖', '扬翔股份有限公司（农牧饲料/养殖，probe live 探活 46 岗）'
where not exists (select 1 from sources where source_url = 'https://yangxiang.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '扬翔股份有限公司', 'https://yangxiang.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '农牧饲料/养殖', '扬翔股份有限公司（农牧饲料/养殖，probe live 探活 20 岗）'
where not exists (select 1 from sources where source_url = 'https://yangxiang.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '泰和新材集团股份有限公司', 'https://tayho.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '芳纶/高性能纤维', '泰和新材集团股份有限公司（芳纶/高性能纤维，probe live 探活 40 岗）'
where not exists (select 1 from sources where source_url = 'https://tayho.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '赛轮集团股份有限公司', 'https://sailuntire.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '轮胎/橡胶', '赛轮集团股份有限公司（轮胎/橡胶，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://sailuntire.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '赛轮集团股份有限公司', 'https://sailuntire.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '轮胎/橡胶', '赛轮集团股份有限公司（轮胎/橡胶，probe live 探活 88 岗）'
where not exists (select 1 from sources where source_url = 'https://sailuntire.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '山东玲珑轮胎股份有限公司', 'https://linglong.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '轮胎/橡胶', '山东玲珑轮胎股份有限公司（轮胎/橡胶，probe live 探活 65 岗）'
where not exists (select 1 from sources where source_url = 'https://linglong.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '山东玲珑轮胎股份有限公司', 'https://linglong.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '轮胎/橡胶', '山东玲珑轮胎股份有限公司（轮胎/橡胶，probe live 探活 25 岗）'
where not exists (select 1 from sources where source_url = 'https://linglong.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '途牛旅游网', 'https://tuniu.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '在线旅游', '途牛旅游网（在线旅游，probe live 探活 6 岗）'
where not exists (select 1 from sources where source_url = 'https://tuniu.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '长隆集团有限公司', 'https://chimelong.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '主题公园/景区', '长隆集团有限公司（主题公园/景区，probe live 探活 160 岗）'
where not exists (select 1 from sources where source_url = 'https://chimelong.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '烟台杰瑞石油服务集团股份有限公司', 'https://jereh.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '专用车/石油装备', '烟台杰瑞石油服务集团股份有限公司（专用车/石油装备，probe live 探活 32 岗）'
where not exists (select 1 from sources where source_url = 'https://jereh.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '烟台杰瑞石油服务集团股份有限公司', 'https://jereh.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '专用车/石油装备', '烟台杰瑞石油服务集团股份有限公司（专用车/石油装备，probe live 探活 54 岗）'
where not exists (select 1 from sources where source_url = 'https://jereh.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '卡斯柯信号有限公司', 'https://casco.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '轨道交通装备/信号', '卡斯柯信号有限公司（轨道交通装备/信号，probe live 探活 36 岗）'
where not exists (select 1 from sources where source_url = 'https://casco.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '卡斯柯信号有限公司', 'https://casco.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '轨道交通装备/信号', '卡斯柯信号有限公司（轨道交通装备/信号，probe live 探活 42 岗）'
where not exists (select 1 from sources where source_url = 'https://casco.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '日立能源（中国）有限公司', 'https://hitachienergy.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '输变电设备/电力变压器/HVDC', '日立能源（中国）有限公司（输变电设备/电力变压器/HVDC，probe live 探活 275 岗）'
where not exists (select 1 from sources where source_url = 'https://hitachienergy.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '日立能源（中国）有限公司', 'https://hitachienergy.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '输变电设备/电力变压器/HVDC', '日立能源（中国）有限公司（输变电设备/电力变压器/HVDC，probe live 探活 5 岗）'
where not exists (select 1 from sources where source_url = 'https://hitachienergy.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '青蛙王子（中国）日化有限公司', 'https://qwwz.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '日化/个护', '青蛙王子（中国）日化有限公司（日化/个护，probe live 探活 34 岗）'
where not exists (select 1 from sources where source_url = 'https://qwwz.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '青蛙王子（中国）日化有限公司', 'https://qwwz.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '日化/个护', '青蛙王子（中国）日化有限公司（日化/个护，probe live 探活 4 岗）'
where not exists (select 1 from sources where source_url = 'https://qwwz.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳有方科技股份有限公司', 'https://neoway.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '物联网模组', '深圳有方科技股份有限公司（物联网模组，probe live 探活 43 岗）'
where not exists (select 1 from sources where source_url = 'https://neoway.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳有方科技股份有限公司', 'https://neoway.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '物联网模组', '深圳有方科技股份有限公司（物联网模组，probe live 探活 15 岗）'
where not exists (select 1 from sources where source_url = 'https://neoway.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '法国圣戈班（中国）投资有限公司', 'https://app.mokahr.com/social-recruitment/saint-gobain/142246', 'official', 'moka', 'playwright', 'private', '建材/工业材料', '法国圣戈班（中国）投资有限公司（建材/工业材料，probe live 探活 在华 29 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/saint-gobain/142246');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '弗吉亚（中国）投资有限公司', 'https://app.mokahr.com/social-recruitment/faurecia/146092', 'official', 'moka', 'playwright', 'private', '汽车内饰', '弗吉亚（中国）投资有限公司（汽车内饰，probe live 探活 在华 72 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/faurecia/146092');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '大陆汽车电子（芜湖）有限公司', 'https://app.mokahr.com/social-recruitment/continental/56212', 'official', 'moka', 'playwright', 'private', '汽车零部件', '大陆汽车电子（芜湖）有限公司（汽车零部件，probe live 探活 32 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/continental/56212');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '伊顿电气（上海）有限公司', 'https://app.mokahr.com/social-recruitment/eaton/147226', 'official', 'moka', 'playwright', 'private', '电气/液压', '伊顿电气（上海）有限公司（电气/液压，probe live 探活 85 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/eaton/147226');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '思摩尔国际控股有限公司', 'https://app.mokahr.com/social-recruitment/smoore/126055', 'official', 'moka', 'playwright', 'private', '工业/雾化科技', '思摩尔国际控股有限公司（工业/雾化科技，probe live 探活 在华 35 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/smoore/126055');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '国药控股股份有限公司', 'https://app.mokahr.com/social-recruitment/sinopharm/56224', 'official', 'moka', 'playwright', 'private', '医药商业流通/批发分销', '国药控股股份有限公司（医药商业流通/批发分销，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/sinopharm/56224');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '卡宾服饰（中国）有限公司', 'https://app.mokahr.com/social-recruitment/cabbeen/29323', 'official', 'moka', 'playwright', 'private', '时尚男装', '卡宾服饰（中国）有限公司（时尚男装，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/cabbeen/29323');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '阿克苏诺贝尔（中国）投资有限公司', 'https://app.mokahr.com/social-recruitment/akzonobel/116138', 'official', 'moka', 'playwright', 'private', '建筑/工业涂料', '阿克苏诺贝尔（中国）投资有限公司（建筑/工业涂料，probe live 探活 在华 24 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/akzonobel/116138');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '紫金矿业集团股份有限公司', 'https://app.mokahr.com/social-recruitment/zijinmining/72010', 'official', 'moka', 'playwright', 'private', '矿业-金矿/铜矿', '紫金矿业集团股份有限公司（矿业-金矿/铜矿，probe live 探活 81 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/zijinmining/72010');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华测检测认证集团股份有限公司', 'https://app.mokahr.com/social-recruitment/cti/145979', 'official', 'moka', 'playwright', 'private', '环境检测/第三方检测', '华测检测认证集团股份有限公司（环境检测/第三方检测，probe live 探活 在华 424 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/cti/145979');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '亚朵酒店', 'https://app.mokahr.com/social-recruitment/atour/151068', 'official', 'moka', 'playwright', 'private', '酒店连锁', '亚朵酒店（酒店连锁，probe live 探活 在华 23 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/atour/151068');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '三维家信息科技有限公司', 'https://app.mokahr.com/social-recruitment/3vjia/46197', 'official', 'moka', 'playwright', 'private', '定制家居/软件', '三维家信息科技有限公司（定制家居/软件，probe live 探活 2 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/3vjia/46197');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '惠生（中国）投资有限公司', 'https://app.mokahr.com/social-recruitment/wison/115997', 'official', 'moka', 'playwright', 'private', '船舶/海洋工程', '惠生（中国）投资有限公司（船舶/海洋工程，probe live 探活 在华 133 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/wison/115997');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '重庆登康口腔护理用品股份有限公司', 'https://app.mokahr.com/social-recruitment/dengkang/36633', 'official', 'moka', 'playwright', 'private', '口腔护理', '重庆登康口腔护理用品股份有限公司（口腔护理，probe live 探活 11 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/dengkang/36633');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '南孚电池（亚锦科技）', 'https://app.mokahr.com/social-recruitment/nanfu/40971', 'official', 'moka', 'playwright', 'private', '日用品', '南孚电池（亚锦科技）（日用品，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/nanfu/40971');

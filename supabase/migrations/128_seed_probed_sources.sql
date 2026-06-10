-- 128 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '长鑫存储技术有限公司', 'https://cxmt.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '存储芯片/DRAM', '长鑫存储技术有限公司（存储芯片/DRAM，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://cxmt.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '长鑫存储技术有限公司', 'https://cxmt.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '存储芯片/DRAM', '长鑫存储技术有限公司（存储芯片/DRAM，probe live 探活 44 岗）'
where not exists (select 1 from sources where source_url = 'https://cxmt.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '芯海科技（深圳）股份有限公司', 'https://chipsea.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', 'MCU/模拟混合信号芯片', '芯海科技（深圳）股份有限公司（MCU/模拟混合信号芯片，probe live 探活 47 岗）'
where not exists (select 1 from sources where source_url = 'https://chipsea.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '芯海科技（深圳）股份有限公司', 'https://chipsea.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', 'MCU/模拟混合信号芯片', '芯海科技（深圳）股份有限公司（MCU/模拟混合信号芯片，probe live 探活 24 岗）'
where not exists (select 1 from sources where source_url = 'https://chipsea.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '睿智医药科技有限公司', 'https://chempartner.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', 'CXO/新药研发外包', '睿智医药科技有限公司（CXO/新药研发外包，probe live 探活 75 岗）'
where not exists (select 1 from sources where source_url = 'https://chempartner.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '睿智医药科技有限公司', 'https://chempartner.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', 'CXO/新药研发外包', '睿智医药科技有限公司（CXO/新药研发外包，probe live 探活 18 岗）'
where not exists (select 1 from sources where source_url = 'https://chempartner.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '正大天晴药业集团股份有限公司', 'https://cttq.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '创新药/肝病肿瘤', '正大天晴药业集团股份有限公司（创新药/肝病肿瘤，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://cttq.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '正大天晴药业集团股份有限公司', 'https://cttq.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '创新药/肝病肿瘤', '正大天晴药业集团股份有限公司（创新药/肝病肿瘤，probe live 探活 99 岗）'
where not exists (select 1 from sources where source_url = 'https://cttq.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新产业生物医学工程股份有限公司', 'https://snibe.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', 'IVD体外诊断', '新产业生物医学工程股份有限公司（IVD体外诊断，probe live 探活 235 岗）'
where not exists (select 1 from sources where source_url = 'https://snibe.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新产业生物医学工程股份有限公司', 'https://snibe.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', 'IVD体外诊断', '新产业生物医学工程股份有限公司（IVD体外诊断，probe live 探活 17 岗）'
where not exists (select 1 from sources where source_url = 'https://snibe.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '盐津铺子食品股份有限公司', 'https://yanjinpuzi.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '休闲零食', '盐津铺子食品股份有限公司（休闲零食，probe live 探活 12 岗）'
where not exists (select 1 from sources where source_url = 'https://yanjinpuzi.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '盐津铺子食品股份有限公司', 'https://yanjinpuzi.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '休闲零食', '盐津铺子食品股份有限公司（休闲零食，probe live 探活 10 岗）'
where not exists (select 1 from sources where source_url = 'https://yanjinpuzi.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '来伊份股份有限公司', 'https://laiyifen.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '休闲零食', '来伊份股份有限公司（休闲零食，probe live 探活 93 岗）'
where not exists (select 1 from sources where source_url = 'https://laiyifen.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '来伊份股份有限公司', 'https://laiyifen.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '休闲零食', '来伊份股份有限公司（休闲零食，probe live 探活 9 岗）'
where not exists (select 1 from sources where source_url = 'https://laiyifen.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '白象食品股份有限公司', 'https://baixiangfood.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '方便食品', '白象食品股份有限公司（方便食品，probe live 探活 238 岗）'
where not exists (select 1 from sources where source_url = 'https://baixiangfood.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '白象食品股份有限公司', 'https://baixiangfood.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '方便食品', '白象食品股份有限公司（方便食品，probe live 探活 116 岗）'
where not exists (select 1 from sources where source_url = 'https://baixiangfood.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '益禾堂餐饮管理有限公司', 'https://yihetang.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '新茶饮', '益禾堂餐饮管理有限公司（新茶饮，probe live 探活 16 岗）'
where not exists (select 1 from sources where source_url = 'https://yihetang.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '益禾堂餐饮管理有限公司', 'https://yihetang.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '新茶饮', '益禾堂餐饮管理有限公司（新茶饮，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://yihetang.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '资生堂（中国）投资有限公司', 'https://shiseido.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '美妆个护', '资生堂（中国）投资有限公司（美妆个护，probe live 探活 2 岗）'
where not exists (select 1 from sources where source_url = 'https://shiseido.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '慕思健康睡眠股份有限公司', 'https://derucci.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '家居家纺', '慕思健康睡眠股份有限公司（家居家纺，probe live 探活 8 岗）'
where not exists (select 1 from sources where source_url = 'https://derucci.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '慕思健康睡眠股份有限公司', 'https://derucci.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '家居家纺', '慕思健康睡眠股份有限公司（家居家纺，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://derucci.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '大润发（北京）商业有限公司（欧尚、大润发）', 'https://rt-mart.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '消费零售', '大润发（北京）商业有限公司（欧尚、大润发）（消费零售，probe live 探活 22 岗）'
where not exists (select 1 from sources where source_url = 'https://rt-mart.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '大润发（北京）商业有限公司（欧尚、大润发）', 'https://rt-mart.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '消费零售', '大润发（北京）商业有限公司（欧尚、大润发）（消费零售，probe live 探活 8 岗）'
where not exists (select 1 from sources where source_url = 'https://rt-mart.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳贝特瑞新能源材料股份有限公司', 'https://btrchina.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '锂电负极材料', '深圳贝特瑞新能源材料股份有限公司（锂电负极材料，probe live 探活 24 岗）'
where not exists (select 1 from sources where source_url = 'https://btrchina.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东方日升新能源股份有限公司', 'https://risen.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '光伏组件', '东方日升新能源股份有限公司（光伏组件，probe live 探活 40 岗）'
where not exists (select 1 from sources where source_url = 'https://risen.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东方日升新能源股份有限公司', 'https://risen.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '光伏组件', '东方日升新能源股份有限公司（光伏组件，probe live 探活 13 岗）'
where not exists (select 1 from sources where source_url = 'https://risen.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上汽通用汽车有限公司', 'https://sgm.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '汽车整车/合资', '上汽通用汽车有限公司（汽车整车/合资，probe live 探活 59 岗）'
where not exists (select 1 from sources where source_url = 'https://sgm.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上汽通用汽车有限公司', 'https://sgm.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '汽车整车/合资', '上汽通用汽车有限公司（汽车整车/合资，probe live 探活 18 岗）'
where not exists (select 1 from sources where source_url = 'https://sgm.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '北京天融信科技股份有限公司', 'https://topsec.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '网络安全', '北京天融信科技股份有限公司（网络安全，probe live 探活 12 岗）'
where not exists (select 1 from sources where source_url = 'https://topsec.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '北京天融信科技股份有限公司', 'https://topsec.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '网络安全', '北京天融信科技股份有限公司（网络安全，probe live 探活 8 岗）'
where not exists (select 1 from sources where source_url = 'https://topsec.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '山石网科通信技术股份有限公司', 'https://hillstonenet.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '网络安全', '山石网科通信技术股份有限公司（网络安全，probe live 探活 21 岗）'
where not exists (select 1 from sources where source_url = 'https://hillstonenet.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '山石网科通信技术股份有限公司', 'https://hillstonenet.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '网络安全', '山石网科通信技术股份有限公司（网络安全，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://hillstonenet.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '启明星辰信息技术集团股份有限公司', 'https://venustech.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '网络安全', '启明星辰信息技术集团股份有限公司（网络安全，probe live 探活 32 岗）'
where not exists (select 1 from sources where source_url = 'https://venustech.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '启明星辰信息技术集团股份有限公司', 'https://venustech.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '网络安全', '启明星辰信息技术集团股份有限公司（网络安全，probe live 探活 4 岗）'
where not exists (select 1 from sources where source_url = 'https://venustech.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海汉得信息技术股份有限公司', 'https://hand-china.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '企业软件/ERP实施', '上海汉得信息技术股份有限公司（企业软件/ERP实施，probe live 探活 26 岗）'
where not exists (select 1 from sources where source_url = 'https://hand-china.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳市纵腾集团有限公司', 'https://zongteng.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '跨境电商物流', '深圳市纵腾集团有限公司（跨境电商物流，probe live 探活 141 岗）'
where not exists (select 1 from sources where source_url = 'https://zongteng.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳市纵腾集团有限公司', 'https://zongteng.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '跨境电商物流', '深圳市纵腾集团有限公司（跨境电商物流，probe live 探活 4 岗）'
where not exists (select 1 from sources where source_url = 'https://zongteng.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '厦门象屿股份有限公司', 'https://xiangyu.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '大宗商品供应链', '厦门象屿股份有限公司（大宗商品供应链，probe live 探活 271 岗）'
where not exists (select 1 from sources where source_url = 'https://xiangyu.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '厦门象屿股份有限公司', 'https://xiangyu.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '大宗商品供应链', '厦门象屿股份有限公司（大宗商品供应链，probe live 探活 62 岗）'
where not exists (select 1 from sources where source_url = 'https://xiangyu.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '志邦家居股份有限公司', 'https://zbom.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '定制家居/建材', '志邦家居股份有限公司（定制家居/建材，probe live 探活 8 岗）'
where not exists (select 1 from sources where source_url = 'https://zbom.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国银河证券股份有限公司', 'https://chinastock.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '综合证券', '中国银河证券股份有限公司（综合证券，probe live 探活 44 岗）'
where not exists (select 1 from sources where source_url = 'https://chinastock.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国银河证券股份有限公司', 'https://chinastock.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '综合证券', '中国银河证券股份有限公司（综合证券，probe live 探活 33 岗）'
where not exists (select 1 from sources where source_url = 'https://chinastock.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新松机器人自动化股份有限公司', 'https://siasun.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '工业机器人', '新松机器人自动化股份有限公司（工业机器人，probe live 探活 15 岗）'
where not exists (select 1 from sources where source_url = 'https://siasun.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '创想三维科技股份有限公司', 'https://creality.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '3D打印', '创想三维科技股份有限公司（3D打印，probe live 探活 43 岗）'
where not exists (select 1 from sources where source_url = 'https://creality.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '创想三维科技股份有限公司', 'https://creality.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '3D打印', '创想三维科技股份有限公司（3D打印，probe live 探活 43 岗）'
where not exists (select 1 from sources where source_url = 'https://creality.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广州文搏智能科技有限公司（FlashForge）', 'https://flashforge.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '3D打印', '广州文搏智能科技有限公司（FlashForge）（3D打印，probe live 探活 31 岗）'
where not exists (select 1 from sources where source_url = 'https://flashforge.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳市英威腾电气股份有限公司', 'https://invt.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '工业自动化/变频器', '深圳市英威腾电气股份有限公司（工业自动化/变频器，probe live 探活 225 岗）'
where not exists (select 1 from sources where source_url = 'https://invt.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳市英威腾电气股份有限公司', 'https://invt.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '工业自动化/变频器', '深圳市英威腾电气股份有限公司（工业自动化/变频器，probe live 探活 95 岗）'
where not exists (select 1 from sources where source_url = 'https://invt.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宇树科技（杭州）有限公司', 'https://unitree.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '四足机器人/人形机器人', '宇树科技（杭州）有限公司（四足机器人/人形机器人，probe live 探活 30 岗）'
where not exists (select 1 from sources where source_url = 'https://unitree.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宇树科技（杭州）有限公司', 'https://unitree.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '四足机器人/人形机器人', '宇树科技（杭州）有限公司（四足机器人/人形机器人，probe live 探活 14 岗）'
where not exists (select 1 from sources where source_url = 'https://unitree.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '巨化集团有限公司', 'https://juhua.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '氟化工/氯碱', '巨化集团有限公司（氟化工/氯碱，probe live 探活 48 岗）'
where not exists (select 1 from sources where source_url = 'https://juhua.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '巨化集团有限公司', 'https://juhua.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '氟化工/氯碱', '巨化集团有限公司（氟化工/氯碱，probe live 探活 46 岗）'
where not exists (select 1 from sources where source_url = 'https://juhua.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '通威集团有限公司', 'https://tongwei.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '水产养殖/饲料/新能源', '通威集团有限公司（水产养殖/饲料/新能源，probe live 探活 7 岗）'
where not exists (select 1 from sources where source_url = 'https://tongwei.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '通威集团有限公司', 'https://tongwei.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '水产养殖/饲料/新能源', '通威集团有限公司（水产养殖/饲料/新能源，probe live 探活 6 岗）'
where not exists (select 1 from sources where source_url = 'https://tongwei.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '正大集团（中国）有限公司', 'https://cpgroup.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '农业/食品/养殖', '正大集团（中国）有限公司（农业/食品/养殖，probe live 探活 485 岗）'
where not exists (select 1 from sources where source_url = 'https://cpgroup.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '正大集团（中国）有限公司', 'https://cpgroup.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '农业/食品/养殖', '正大集团（中国）有限公司（农业/食品/养殖，probe live 探活 288 岗）'
where not exists (select 1 from sources where source_url = 'https://cpgroup.zhiye.com/campus');

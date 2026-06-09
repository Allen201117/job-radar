-- 110 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '三一集团', 'https://sany.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '工程机械', '三一集团（工程机械，probe live 探活 28 岗）'
where not exists (select 1 from sources where source_url = 'https://sany.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '三一集团', 'https://sany.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '工程机械', '三一集团（工程机械，probe live 探活 188 岗）'
where not exists (select 1 from sources where source_url = 'https://sany.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '神州数码集团', 'https://digitalchina.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '科技', '神州数码集团（科技，probe live 探活 228 岗）'
where not exists (select 1 from sources where source_url = 'https://digitalchina.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '神州数码集团', 'https://digitalchina.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '科技', '神州数码集团（科技，probe live 探活 100 岗）'
where not exists (select 1 from sources where source_url = 'https://digitalchina.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '德力西集团', 'https://delixi.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '电气', '德力西集团（电气，probe live 探活 18 岗）'
where not exists (select 1 from sources where source_url = 'https://delixi.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '德力西集团', 'https://delixi.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '电气', '德力西集团（电气，probe live 探活 2 岗）'
where not exists (select 1 from sources where source_url = 'https://delixi.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '扬子江药业集团', 'https://yangzijiang.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '医药', '扬子江药业集团（医药，probe live 探活 323 岗）'
where not exists (select 1 from sources where source_url = 'https://yangzijiang.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '扬子江药业集团', 'https://yangzijiang.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '医药', '扬子江药业集团（医药，probe live 探活 107 岗）'
where not exists (select 1 from sources where source_url = 'https://yangzijiang.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁波合盛集团', 'https://hoshine.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '化工', '宁波合盛集团（化工，probe live 探活 195 岗）'
where not exists (select 1 from sources where source_url = 'https://hoshine.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁波合盛集团', 'https://hoshine.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '化工', '宁波合盛集团（化工，probe live 探活 28 岗）'
where not exists (select 1 from sources where source_url = 'https://hoshine.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳传音控股', 'https://transsion.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '消费电子', '深圳传音控股（消费电子，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://transsion.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳传音控股', 'https://transsion.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '消费电子', '深圳传音控股（消费电子，probe live 探活 55 岗）'
where not exists (select 1 from sources where source_url = 'https://transsion.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '河南双汇投资发展', 'https://shuanghui.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '食品', '河南双汇投资发展（食品，probe live 探活 26 岗）'
where not exists (select 1 from sources where source_url = 'https://shuanghui.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '河南双汇投资发展', 'https://shuanghui.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '食品', '河南双汇投资发展（食品，probe live 探活 17 岗）'
where not exists (select 1 from sources where source_url = 'https://shuanghui.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '振石控股集团', 'https://zhenshigroup.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '新材料', '振石控股集团（新材料，probe live 探活 25 岗）'
where not exists (select 1 from sources where source_url = 'https://zhenshigroup.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '振石控股集团', 'https://zhenshigroup.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '新材料', '振石控股集团（新材料，probe live 探活 27 岗）'
where not exists (select 1 from sources where source_url = 'https://zhenshigroup.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华峰集团', 'https://huafeng.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '化工', '华峰集团（化工，probe live 探活 22 岗）'
where not exists (select 1 from sources where source_url = 'https://huafeng.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华峰集团', 'https://huafeng.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '化工', '华峰集团（化工，probe live 探活 30 岗）'
where not exists (select 1 from sources where source_url = 'https://huafeng.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新华三信息技术', 'https://h3c.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '通信', '新华三信息技术（通信，probe live 探活 286 岗）'
where not exists (select 1 from sources where source_url = 'https://h3c.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新华三信息技术', 'https://h3c.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '通信', '新华三信息技术（通信，probe live 探活 49 岗）'
where not exists (select 1 from sources where source_url = 'https://h3c.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '金发科技', 'https://kingfa.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '新材料', '金发科技（新材料，probe live 探活 14 岗）'
where not exists (select 1 from sources where source_url = 'https://kingfa.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '金发科技', 'https://kingfa.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '新材料', '金发科技（新材料，probe live 探活 73 岗）'
where not exists (select 1 from sources where source_url = 'https://kingfa.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁波申洲针织', 'https://shenzhou.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '服装', '宁波申洲针织（服装，probe live 探活 23 岗）'
where not exists (select 1 from sources where source_url = 'https://shenzhou.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东方日升新能源', 'https://risen.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '光伏', '东方日升新能源（光伏，probe live 探活 40 岗）'
where not exists (select 1 from sources where source_url = 'https://risen.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东方日升新能源', 'https://risen.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '光伏', '东方日升新能源（光伏，probe live 探活 13 岗）'
where not exists (select 1 from sources where source_url = 'https://risen.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海天塑机集团', 'https://haitian.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '装备制造', '海天塑机集团（装备制造，probe live 探活 221 岗）'
where not exists (select 1 from sources where source_url = 'https://haitian.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海天塑机集团', 'https://haitian.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '装备制造', '海天塑机集团（装备制造，probe live 探活 62 岗）'
where not exists (select 1 from sources where source_url = 'https://haitian.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '苏州东山精密制造', 'https://dsbj.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '智能制造', '苏州东山精密制造（智能制造，probe live 探活 8 岗）'
where not exists (select 1 from sources where source_url = 'https://dsbj.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '苏州东山精密制造', 'https://dsbj.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '智能制造', '苏州东山精密制造（智能制造，probe live 探活 11 岗）'
where not exists (select 1 from sources where source_url = 'https://dsbj.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳市东阳光实业发展', 'https://hec.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '医药', '深圳市东阳光实业发展（医药，probe live 探活 36 岗）'
where not exists (select 1 from sources where source_url = 'https://hec.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳市东阳光实业发展', 'https://hec.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '医药', '深圳市东阳光实业发展（医药，probe live 探活 49 岗）'
where not exists (select 1 from sources where source_url = 'https://hec.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '国轩高科', 'https://gotion.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '锂电', '国轩高科（锂电，probe live 探活 349 岗）'
where not exists (select 1 from sources where source_url = 'https://gotion.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '国轩高科', 'https://gotion.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '锂电', '国轩高科（锂电，probe live 探活 430 岗）'
where not exists (select 1 from sources where source_url = 'https://gotion.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳市汇川技术', 'https://inovance.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '工业自动化', '深圳市汇川技术（工业自动化，probe live 探活 385 岗）'
where not exists (select 1 from sources where source_url = 'https://inovance.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宗申产业集团', 'https://zongshen.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '摩托车', '宗申产业集团（摩托车，probe live 探活 34 岗）'
where not exists (select 1 from sources where source_url = 'https://zongshen.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宗申产业集团', 'https://zongshen.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '摩托车', '宗申产业集团（摩托车，probe live 探活 5 岗）'
where not exists (select 1 from sources where source_url = 'https://zongshen.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '卓胜微', 'https://maxscend.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '半导体', '卓胜微（半导体，probe live 探活 75 岗）'
where not exists (select 1 from sources where source_url = 'https://maxscend.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新易盛', 'https://eoptolink.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '光通信', '新易盛（光通信，probe live 探活 58 岗）'
where not exists (select 1 from sources where source_url = 'https://eoptolink.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新易盛', 'https://eoptolink.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '光通信', '新易盛（光通信，probe live 探活 31 岗）'
where not exists (select 1 from sources where source_url = 'https://eoptolink.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '纳思达', 'https://ninestar.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '半导体', '纳思达（半导体，probe live 探活 7 岗）'
where not exists (select 1 from sources where source_url = 'https://ninestar.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '纳思达', 'https://ninestar.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '半导体', '纳思达（半导体，probe live 探活 25 岗）'
where not exists (select 1 from sources where source_url = 'https://ninestar.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '迈瑞医疗', 'https://mindray.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '医疗器械', '迈瑞医疗（医疗器械，probe live 探活 200 岗）'
where not exists (select 1 from sources where source_url = 'https://mindray.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '复星医药', 'https://fosunpharma.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '医药', '复星医药（医药，probe live 探活 10 岗）'
where not exists (select 1 from sources where source_url = 'https://fosunpharma.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '复星医药', 'https://fosunpharma.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '医药', '复星医药（医药，probe live 探活 10 岗）'
where not exists (select 1 from sources where source_url = 'https://fosunpharma.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '信达生物', 'https://innoventbio.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '生物医药', '信达生物（生物医药，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://innoventbio.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '信达生物', 'https://innoventbio.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '生物医药', '信达生物（生物医药，probe live 探活 108 岗）'
where not exists (select 1 from sources where source_url = 'https://innoventbio.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '泰格医药', 'https://tigermed.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '医药外包', '泰格医药（医药外包，probe live 探活 302 岗）'
where not exists (select 1 from sources where source_url = 'https://tigermed.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '凯莱英', 'https://asymchem.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '医药外包', '凯莱英（医药外包，probe live 探活 325 岗）'
where not exists (select 1 from sources where source_url = 'https://asymchem.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '凯莱英', 'https://asymchem.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '医药外包', '凯莱英（医药外包，probe live 探活 61 岗）'
where not exists (select 1 from sources where source_url = 'https://asymchem.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '药明康德', 'https://wuxiapptec.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '医药外包', '药明康德（医药外包，probe live 探活 493 岗）'
where not exists (select 1 from sources where source_url = 'https://wuxiapptec.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '科大讯飞', 'https://iflytek.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '人工智能', '科大讯飞（人工智能，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://iflytek.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '传音控股', 'https://transsion.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '消费电子', '传音控股（消费电子，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://transsion.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '传音控股', 'https://transsion.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '消费电子', '传音控股（消费电子，probe live 探活 55 岗）'
where not exists (select 1 from sources where source_url = 'https://transsion.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '公牛集团', 'https://gongniu.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '电工', '公牛集团（电工，probe live 探活 16 岗）'
where not exists (select 1 from sources where source_url = 'https://gongniu.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '公牛集团', 'https://gongniu.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '电工', '公牛集团（电工，probe live 探活 19 岗）'
where not exists (select 1 from sources where source_url = 'https://gongniu.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '石头科技', 'https://roborock.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '智能硬件', '石头科技（智能硬件，probe live 探活 271 岗）'
where not exists (select 1 from sources where source_url = 'https://roborock.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '石头科技', 'https://roborock.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '智能硬件', '石头科技（智能硬件，probe live 探活 22 岗）'
where not exists (select 1 from sources where source_url = 'https://roborock.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海信集团', 'https://haixin.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '家电', '海信集团（家电，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://haixin.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'TCL中环', 'https://zhonghuan.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '光伏', 'TCL中环（光伏，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://zhonghuan.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '蜂巢能源', 'https://svolt.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '锂电', '蜂巢能源（锂电，probe live 探活 170 岗）'
where not exists (select 1 from sources where source_url = 'https://svolt.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '蜂巢能源', 'https://svolt.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '锂电', '蜂巢能源（锂电，probe live 探活 62 岗）'
where not exists (select 1 from sources where source_url = 'https://svolt.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '赣锋锂业', 'https://ganfenglithium.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '锂电', '赣锋锂业（锂电，probe live 探活 41 岗）'
where not exists (select 1 from sources where source_url = 'https://ganfenglithium.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '通威股份', 'https://tongwei.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '光伏', '通威股份（光伏，probe live 探活 7 岗）'
where not exists (select 1 from sources where source_url = 'https://tongwei.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '通威股份', 'https://tongwei.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '光伏', '通威股份（光伏，probe live 探活 6 岗）'
where not exists (select 1 from sources where source_url = 'https://tongwei.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '金风科技', 'https://goldwind.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '新能源', '金风科技（新能源，probe live 探活 88 岗）'
where not exists (select 1 from sources where source_url = 'https://goldwind.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东鹏饮料', 'https://dongpeng.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '食品饮料', '东鹏饮料（食品饮料，probe live 探活 22 岗）'
where not exists (select 1 from sources where source_url = 'https://dongpeng.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '妙可蓝多', 'https://milkground.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '食品', '妙可蓝多（食品，probe live 探活 139 岗）'
where not exists (select 1 from sources where source_url = 'https://milkground.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '喜茶', 'https://heytea.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '餐饮', '喜茶（餐饮，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://heytea.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '喜茶', 'https://heytea.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '餐饮', '喜茶（餐饮，probe live 探活 21 岗）'
where not exists (select 1 from sources where source_url = 'https://heytea.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '泡泡玛特', 'https://popmart.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '潮玩', '泡泡玛特（潮玩，probe live 探活 130 岗）'
where not exists (select 1 from sources where source_url = 'https://popmart.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '申洲国际', 'https://shenzhou.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '服装', '申洲国际（服装，probe live 探活 23 岗）'
where not exists (select 1 from sources where source_url = 'https://shenzhou.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '永辉超市', 'https://yhchaoshi.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '零售', '永辉超市（零售，probe live 探活 34 岗）'
where not exists (select 1 from sources where source_url = 'https://yhchaoshi.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '永辉超市', 'https://yhchaoshi.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '零售', '永辉超市（零售，probe live 探活 5 岗）'
where not exists (select 1 from sources where source_url = 'https://yhchaoshi.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '豪迈科技', 'https://himile.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '装备制造', '豪迈科技（装备制造，probe live 探活 349 岗）'
where not exists (select 1 from sources where source_url = 'https://himile.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '豪迈科技', 'https://himile.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '装备制造', '豪迈科技（装备制造，probe live 探活 16 岗）'
where not exists (select 1 from sources where source_url = 'https://himile.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '汇川技术', 'https://inovance.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '工业自动化', '汇川技术（工业自动化，probe live 探活 385 岗）'
where not exists (select 1 from sources where source_url = 'https://inovance.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '石头世纪', 'https://roborock.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '智能硬件', '石头世纪（智能硬件，probe live 探活 271 岗）'
where not exists (select 1 from sources where source_url = 'https://roborock.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '石头世纪', 'https://roborock.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '智能硬件', '石头世纪（智能硬件，probe live 探活 22 岗）'
where not exists (select 1 from sources where source_url = 'https://roborock.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '有赞', 'https://youzan.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '软件', '有赞（软件，probe live 探活 127 岗）'
where not exists (select 1 from sources where source_url = 'https://youzan.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '有赞', 'https://youzan.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '软件', '有赞（软件，probe live 探活 6 岗）'
where not exists (select 1 from sources where source_url = 'https://youzan.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '零跑汽车', 'https://leapmotor.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '汽车', '零跑汽车（汽车，probe live 探活 32 岗）'
where not exists (select 1 from sources where source_url = 'https://leapmotor.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '图达通', 'https://seyond.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '激光雷达', '图达通（激光雷达，probe live 探活 10 岗）'
where not exists (select 1 from sources where source_url = 'https://seyond.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '安集科技', 'https://anjimicro.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '半导体材料', '安集科技（半导体材料，probe live 探活 3 岗）'
where not exists (select 1 from sources where source_url = 'https://anjimicro.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '安集科技', 'https://anjimicro.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '半导体材料', '安集科技（半导体材料，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://anjimicro.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '晶丰明源', 'https://bpsemi.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '半导体', '晶丰明源（半导体，probe live 探活 53 岗）'
where not exists (select 1 from sources where source_url = 'https://bpsemi.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '晶丰明源', 'https://bpsemi.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '半导体', '晶丰明源（半导体，probe live 探活 85 岗）'
where not exists (select 1 from sources where source_url = 'https://bpsemi.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '艾为电子', 'https://awinic.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '半导体', '艾为电子（半导体，probe live 探活 49 岗）'
where not exists (select 1 from sources where source_url = 'https://awinic.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '容百科技', 'https://ronbay.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '锂电', '容百科技（锂电，probe live 探活 33 岗）'
where not exists (select 1 from sources where source_url = 'https://ronbay.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '容百科技', 'https://ronbay.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '锂电', '容百科技（锂电，probe live 探活 109 岗）'
where not exists (select 1 from sources where source_url = 'https://ronbay.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '传音手机', 'https://transsion.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '消费电子', '传音手机（消费电子，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://transsion.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '传音手机', 'https://transsion.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '消费电子', '传音手机（消费电子，probe live 探活 55 岗）'
where not exists (select 1 from sources where source_url = 'https://transsion.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '亿道信息', 'https://emdoor.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '智能制造', '亿道信息（智能制造，probe live 探活 53 岗）'
where not exists (select 1 from sources where source_url = 'https://emdoor.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广和通', 'https://fibocom.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '物联网', '广和通（物联网，probe live 探活 144 岗）'
where not exists (select 1 from sources where source_url = 'https://fibocom.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广和通', 'https://fibocom.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '物联网', '广和通（物联网，probe live 探活 42 岗）'
where not exists (select 1 from sources where source_url = 'https://fibocom.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海目星', 'https://hymson.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '激光设备', '海目星（激光设备，probe live 探活 130 岗）'
where not exists (select 1 from sources where source_url = 'https://hymson.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海目星', 'https://hymson.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '激光设备', '海目星（激光设备，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://hymson.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华海清科', 'https://hwatsing.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '半导体设备', '华海清科（半导体设备，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://hwatsing.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华海清科', 'https://hwatsing.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '半导体设备', '华海清科（半导体设备，probe live 探活 16 岗）'
where not exists (select 1 from sources where source_url = 'https://hwatsing.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '聚辰股份', 'https://giantec.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '半导体', '聚辰股份（半导体，probe live 探活 3 岗）'
where not exists (select 1 from sources where source_url = 'https://giantec.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '洲明科技', 'https://unilumin.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', 'LED显示', '洲明科技（LED显示，probe live 探活 18 岗）'
where not exists (select 1 from sources where source_url = 'https://unilumin.zhiye.com/social');

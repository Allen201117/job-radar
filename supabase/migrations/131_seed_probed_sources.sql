-- 131 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '苏州瑞可达连接系统股份有限公司', 'https://recodeal.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '新能源连接器', '苏州瑞可达连接系统股份有限公司（新能源连接器，probe live 探活 75 岗）'
where not exists (select 1 from sources where source_url = 'https://recodeal.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '苏州瑞可达连接系统股份有限公司', 'https://recodeal.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '新能源连接器', '苏州瑞可达连接系统股份有限公司（新能源连接器，probe live 探活 11 岗）'
where not exists (select 1 from sources where source_url = 'https://recodeal.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '时代天使生物科技有限公司', 'https://angelalign.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '口腔', '时代天使生物科技有限公司（口腔，probe live 探活 24 岗）'
where not exists (select 1 from sources where source_url = 'https://angelalign.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '时代天使生物科技有限公司', 'https://angelalign.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '口腔', '时代天使生物科技有限公司（口腔，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://angelalign.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '北醒（北京）光子科技有限公司', 'https://benewake.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '激光雷达/ToF传感器', '北醒（北京）光子科技有限公司（激光雷达/ToF传感器，probe live 探活 13 岗）'
where not exists (select 1 from sources where source_url = 'https://benewake.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '北醒（北京）光子科技有限公司', 'https://benewake.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '激光雷达/ToF传感器', '北醒（北京）光子科技有限公司（激光雷达/ToF传感器，probe live 探活 4 岗）'
where not exists (select 1 from sources where source_url = 'https://benewake.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海威迈斯新能源有限公司', 'https://vmax.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '热管理/车载电源', '上海威迈斯新能源有限公司（热管理/车载电源，probe live 探活 69 岗）'
where not exists (select 1 from sources where source_url = 'https://vmax.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳市普渡科技有限公司', 'https://pudutech.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '服务机器人/配送机器人', '深圳市普渡科技有限公司（服务机器人/配送机器人，probe live 探活 148 岗）'
where not exists (select 1 from sources where source_url = 'https://pudutech.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳市普渡科技有限公司', 'https://pudutech.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '服务机器人/配送机器人', '深圳市普渡科技有限公司（服务机器人/配送机器人，probe live 探活 29 岗）'
where not exists (select 1 from sources where source_url = 'https://pudutech.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '无锡信捷电气股份有限公司', 'https://xinje.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '运动控制/工业机器人', '无锡信捷电气股份有限公司（运动控制/工业机器人，probe live 探活 50 岗）'
where not exists (select 1 from sources where source_url = 'https://xinje.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '无锡信捷电气股份有限公司', 'https://xinje.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '运动控制/工业机器人', '无锡信捷电气股份有限公司（运动控制/工业机器人，probe live 探活 15 岗）'
where not exists (select 1 from sources where source_url = 'https://xinje.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '孚能科技（赣州）股份有限公司', 'https://farasisenergy.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '动力/储能电池', '孚能科技（赣州）股份有限公司（动力/储能电池，probe live 探活 53 岗）'
where not exists (select 1 from sources where source_url = 'https://farasisenergy.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '孚能科技（赣州）股份有限公司', 'https://farasisenergy.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '动力/储能电池', '孚能科技（赣州）股份有限公司（动力/储能电池，probe live 探活 30 岗）'
where not exists (select 1 from sources where source_url = 'https://farasisenergy.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '厦门钨业股份有限公司', 'https://cxtc.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '锂电正极材料', '厦门钨业股份有限公司（锂电正极材料，probe live 探活 4 岗）'
where not exists (select 1 from sources where source_url = 'https://cxtc.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '阿道夫实业有限公司（阿道夫洗护）', 'https://adolph.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '个护/洗护', '阿道夫实业有限公司（阿道夫洗护）（个护/洗护，probe live 探活 2 岗）'
where not exists (select 1 from sources where source_url = 'https://adolph.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '劲仔食品集团股份有限公司', 'https://jinzaifood.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '休闲零食/小鱼仔', '劲仔食品集团股份有限公司（休闲零食/小鱼仔，probe live 探活 62 岗）'
where not exists (select 1 from sources where source_url = 'https://jinzaifood.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '劲仔食品集团股份有限公司', 'https://jinzaifood.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '休闲零食/小鱼仔', '劲仔食品集团股份有限公司（休闲零食/小鱼仔，probe live 探活 6 岗）'
where not exists (select 1 from sources where source_url = 'https://jinzaifood.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '思念食品有限公司', 'https://synear.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '预制菜/速冻食品', '思念食品有限公司（预制菜/速冻食品，probe live 探活 22 岗）'
where not exists (select 1 from sources where source_url = 'https://synear.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '思念食品有限公司', 'https://synear.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '预制菜/速冻食品', '思念食品有限公司（预制菜/速冻食品，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://synear.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广州八马茶业股份有限公司', 'https://bamatea.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '茶饮/茶叶零售', '广州八马茶业股份有限公司（茶饮/茶叶零售，probe live 探活 12 岗）'
where not exists (select 1 from sources where source_url = 'https://bamatea.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广州汇量科技（Mintegral/移动广告出海）', 'https://mobvista.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '出海广告/移动营销', '广州汇量科技（Mintegral/移动广告出海）（出海广告/移动营销，probe live 探活 25 岗）'
where not exists (select 1 from sources where source_url = 'https://mobvista.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海观安信息技术股份有限公司', 'https://guanan.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '安全 SaaS', '上海观安信息技术股份有限公司（安全 SaaS，probe live 探活 287 岗）'
where not exists (select 1 from sources where source_url = 'https://guanan.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海观安信息技术股份有限公司', 'https://guanan.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '安全 SaaS', '上海观安信息技术股份有限公司（安全 SaaS，probe live 探活 51 岗）'
where not exists (select 1 from sources where source_url = 'https://guanan.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '北京远光软件股份有限公司', 'https://ygsoft.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '财税/能源管理 SaaS', '北京远光软件股份有限公司（财税/能源管理 SaaS，probe live 探活 5 岗）'
where not exists (select 1 from sources where source_url = 'https://ygsoft.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广东伊之密精密机械股份有限公司', 'https://yizumi.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '珠三角·注塑机/压铸机', '广东伊之密精密机械股份有限公司（珠三角·注塑机/压铸机，probe live 探活 206 岗）'
where not exists (select 1 from sources where source_url = 'https://yizumi.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '阅文集团', 'https://yuewen.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '数字阅读/网络文学', '阅文集团（数字阅读/网络文学，probe live 探活 11 岗）'
where not exists (select 1 from sources where source_url = 'https://yuewen.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '诺诚健华医药科技有限公司', 'https://innocare.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '血液/免疫肿瘤创新药', '诺诚健华医药科技有限公司（血液/免疫肿瘤创新药，probe live 探活 87 岗）'
where not exists (select 1 from sources where source_url = 'https://innocare.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '易车控股有限公司', 'https://yiche.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '汽车互联网/电商', '易车控股有限公司（汽车互联网/电商，probe live 探活 5 岗）'
where not exists (select 1 from sources where source_url = 'https://yiche.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '易车控股有限公司', 'https://yiche.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '汽车互联网/电商', '易车控股有限公司（汽车互联网/电商，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://yiche.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海复宏汉霖生物技术股份有限公司', 'https://henlius.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '生物类似药/单克隆抗体', '上海复宏汉霖生物技术股份有限公司（生物类似药/单克隆抗体，probe live 探活 87 岗）'
where not exists (select 1 from sources where source_url = 'https://henlius.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海复宏汉霖生物技术股份有限公司', 'https://henlius.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '生物类似药/单克隆抗体', '上海复宏汉霖生物技术股份有限公司（生物类似药/单克隆抗体，probe live 探活 14 岗）'
where not exists (select 1 from sources where source_url = 'https://henlius.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广东培正学院控股有限公司旗下广州中望龙腾软件股份有限公司', 'https://app.mokahr.com/social-recruitment/zwcad/28355', 'official', 'moka', 'playwright', 'private', '工业软件/CAD/CAE', '广东培正学院控股有限公司旗下广州中望龙腾软件股份有限公司（工业软件/CAD/CAE，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/zwcad/28355');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '山东山大华天软件有限公司', 'https://app.mokahr.com/social-recruitment/hoteamsoft/148071', 'official', 'moka', 'playwright', 'private', '工业软件/CAPP/PDM/PLM', '山东山大华天软件有限公司（工业软件/CAPP/PDM/PLM，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/hoteamsoft/148071');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '杭州和利时自动化有限公司', 'https://app.mokahr.com/social-recruitment/hollysys/1903', 'official', 'moka', 'playwright', 'private', '工业自动化/DCS/PLC', '杭州和利时自动化有限公司（工业自动化/DCS/PLC，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/hollysys/1903');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳奥比中光科技集团股份有限公司', 'https://app.mokahr.com/social-recruitment/orbbec/44936', 'official', 'moka', 'playwright', 'private', '工业互联网/3D视觉/传感器', '深圳奥比中光科技集团股份有限公司（工业互联网/3D视觉/传感器，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/orbbec/44936');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广州万孚生物技术股份有限公司', 'https://app.mokahr.com/social-recruitment/wondfo/19912', 'official', 'moka', 'playwright', 'private', 'IVD体外诊断', '广州万孚生物技术股份有限公司（IVD体外诊断，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/wondfo/19912');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '杭州科百特过滤器材有限公司', 'https://app.mokahr.com/social-recruitment/cobetterfilter/141058', 'official', 'moka', 'playwright', 'private', '膜材料', '杭州科百特过滤器材有限公司（膜材料，probe live 探活 在华 38 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/cobetterfilter/141058');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海保隆汽车科技股份有限公司', 'https://app.mokahr.com/social-recruitment/baolong/45811', 'official', 'moka', 'playwright', 'private', '汽车电子/TPMS', '上海保隆汽车科技股份有限公司（汽车电子/TPMS，probe live 探活 在华 98 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/baolong/45811');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '浙江银轮机械股份有限公司', 'https://app.mokahr.com/social-recruitment/yinlun/128570', 'official', 'moka', 'playwright', 'private', '热管理/冷却系统', '浙江银轮机械股份有限公司（热管理/冷却系统，probe live 探活 50 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/yinlun/128570');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广州市耐世特汽车系统有限公司', 'https://app.mokahr.com/social-recruitment/nexteer/72403', 'official', 'moka', 'playwright', 'private', '线控底盘/转向系统', '广州市耐世特汽车系统有限公司（线控底盘/转向系统，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/nexteer/72403');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '杭州电魂网络科技股份有限公司', 'https://app.mokahr.com/social-recruitment/dianhun/55952', 'official', 'moka', 'playwright', 'private', '汽车后市场/数字化', '杭州电魂网络科技股份有限公司（汽车后市场/数字化，probe live 探活 10 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/dianhun/55952');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海擎朗智能科技有限公司', 'https://app.mokahr.com/social-recruitment/keenon/24672', 'official', 'moka', 'playwright', 'private', '服务机器人/配送机器人', '上海擎朗智能科技有限公司（服务机器人/配送机器人，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/keenon/24672');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海仙工智能科技有限公司', 'https://app.mokahr.com/social-recruitment/seer/41526', 'official', 'moka', 'playwright', 'private', 'AMR移动机器人/调度系统', '上海仙工智能科技有限公司（AMR移动机器人/调度系统，probe live 探活 56 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/seer/41526');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '菲尼克斯（南京）智能制造技术工程有限公司', 'https://app.mokahr.com/social-recruitment/phoenixcontact/99349', 'official', 'moka', 'playwright', 'private', '工业自动化/工业视觉', '菲尼克斯（南京）智能制造技术工程有限公司（工业自动化/工业视觉，probe live 探活 在华 95 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/phoenixcontact/99349');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '禾迈股份有限公司', 'https://app.mokahr.com/social-recruitment/hoymiles/70376', 'official', 'moka', 'playwright', 'private', '光伏微逆变器', '禾迈股份有限公司（光伏微逆变器，probe live 探活 在华 64 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/hoymiles/70376');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海艾推网络科技有限公司（ONES）', 'https://app.mokahr.com/social-recruitment/oneshr/58057', 'official', 'moka', 'playwright', 'private', '研发管理 SaaS', '上海艾推网络科技有限公司（ONES）（研发管理 SaaS，probe live 探活 11 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/oneshr/58057');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海法大大网络科技有限公司', 'https://app.mokahr.com/social-recruitment/fadada/6136', 'official', 'moka', 'playwright', 'private', '法务/电子合同 SaaS', '上海法大大网络科技有限公司（法务/电子合同 SaaS，probe live 探活 在华 13 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/fadada/6136');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '天玺（北京）文化科技有限公司（万代南梦宫）', 'https://app.mokahr.com/social-recruitment/bandainamcochina/44577', 'official', 'moka', 'playwright', 'private', '潮玩谷子/IP衍生-日系手办/周边', '天玺（北京）文化科技有限公司（万代南梦宫）（潮玩谷子/IP衍生-日系手办/周边，probe live 探活 在华 11 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/bandainamcochina/44577');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '乐信集团', 'https://app.mokahr.com/social-recruitment/lexin/94715', 'official', 'moka', 'playwright', 'private', '消费金融/金融科技', '乐信集团（消费金融/金融科技，probe live 探活 在华 54 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/lexin/94715');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '声网Agora', 'https://app.mokahr.com/social-recruitment/agora/6334', 'official', 'moka', 'playwright', 'private', 'RTC/实时音视频云', '声网Agora（RTC/实时音视频云，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/agora/6334');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '荣昌生物制药（烟台）股份有限公司', 'https://app.mokahr.com/social-recruitment/remegen/45549', 'official', 'moka', 'playwright', 'private', 'ADC抗体药物偶联/创新药', '荣昌生物制药（烟台）股份有限公司（ADC抗体药物偶联/创新药，probe live 探活 在华 98 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/remegen/45549');

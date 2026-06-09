-- 114 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华熙生物', 'https://bloomagebiotech.hotjob.cn/SU64de19ec6202cc6de345b915/pb/social.html', 'official', 'hotjob', 'http', 'private', '美妆', '华熙生物（美妆，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://bloomagebiotech.hotjob.cn/SU64de19ec6202cc6de345b915/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华熙生物', 'https://bloomagebiotech.hotjob.cn/SU64de19ec6202cc6de345b915/pb/school.html', 'official', 'hotjob', 'http', 'private', '美妆', '华熙生物（美妆，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://bloomagebiotech.hotjob.cn/SU64de19ec6202cc6de345b915/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华熙生物', 'https://bloomagebiotech.hotjob.cn/SU64de19ec6202cc6de345b915/pb/interns.html', 'official', 'hotjob', 'http', 'private', '美妆', '华熙生物（美妆，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://bloomagebiotech.hotjob.cn/SU64de19ec6202cc6de345b915/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '零一万物', 'https://01ai.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '人工智能', '零一万物（人工智能，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://01ai.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Soul', 'https://soulapp.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '互联网', 'Soul（互联网，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://soulapp.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '智谱AI', 'https://zhipu-ai.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '人工智能', '智谱AI（人工智能，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://zhipu-ai.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '沐瞳科技', 'https://moonton.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '游戏', '沐瞳科技（游戏，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://moonton.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '得物', 'https://poizon.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '互联网', '得物（互联网，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://poizon.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'XREAL', 'https://xreal.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '智能硬件', 'XREAL（智能硬件，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://xreal.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Momenta', 'https://momenta.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '自动驾驶', 'Momenta（自动驾驶，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://momenta.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '拓竹科技', 'https://bambulab.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '智能硬件', '拓竹科技（智能硬件，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://bambulab.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '欢乐互娱', 'https://huanle.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '游戏', '欢乐互娱（游戏，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://huanle.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '极致游戏', 'https://jzyxgames.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '游戏', '极致游戏（游戏，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://jzyxgames.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '智元机器人', 'https://agirobot.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '机器人', '智元机器人（机器人，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://agirobot.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宇通客车', 'https://yutong.hotjob.cn/wt/yutong/web/index', 'official', 'wt', 'http', 'private', '汽车', '宇通客车（汽车，probe live 探活 在华 19 岗）'
where not exists (select 1 from sources where source_url = 'https://yutong.hotjob.cn/wt/yutong/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '地平线', 'https://wecruit.hotjob.cn/SU64819a4f2f9d2433ba8b043a/pb/social.html', 'official', 'hotjob', 'http', 'private', '自动驾驶', '地平线（自动驾驶，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU64819a4f2f9d2433ba8b043a/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '地平线', 'https://wecruit.hotjob.cn/SU64819a4f2f9d2433ba8b043a/pb/school.html', 'official', 'hotjob', 'http', 'private', '自动驾驶', '地平线（自动驾驶，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU64819a4f2f9d2433ba8b043a/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '地平线', 'https://wecruit.hotjob.cn/SU64819a4f2f9d2433ba8b043a/pb/interns.html', 'official', 'hotjob', 'http', 'private', '自动驾驶', '地平线（自动驾驶，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU64819a4f2f9d2433ba8b043a/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '乐狗科技', 'https://app.mokahr.com/campus_apply/legougames/6163', 'official', 'moka', 'playwright', 'private', '游戏', '乐狗科技（游戏，probe live 探活 在华 9 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/legougames/6163');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '盛趣游戏', 'https://app.mokahr.com/campus_apply/shengqu/4078', 'official', 'moka', 'playwright', 'private', '游戏', '盛趣游戏（游戏，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/shengqu/4078');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '游卡', 'https://app.mokahr.com/campus_apply/yokagames/41940', 'official', 'moka', 'playwright', 'private', '游戏', '游卡（游戏，probe live 探活 在华 32 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/yokagames/41940');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '乐元素', 'https://app.mokahr.com/campus_apply/leyuansu/2357', 'official', 'moka', 'playwright', 'private', '游戏', '乐元素（游戏，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/leyuansu/2357');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '最右', 'https://app.mokahr.com/apply/xiaochuankeji/3519', 'official', 'moka', 'playwright', 'private', '互联网', '最右（互联网，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/xiaochuankeji/3519');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '月之暗面', 'https://app.mokahr.com/apply/moonshot/148506', 'official', 'moka', 'playwright', 'private', '人工智能', '月之暗面（人工智能，probe live 探活 在华 123 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/moonshot/148506');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Meshy', 'https://app.mokahr.com/apply/taichi/148086', 'official', 'moka', 'playwright', 'private', '人工智能', 'Meshy（人工智能，probe live 探活 在华 59 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/taichi/148086');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '小天才', 'https://app.mokahr.com/campus_apply/eebbk/37594', 'official', 'moka', 'playwright', 'private', '智能硬件', '小天才（智能硬件，probe live 探活 在华 23 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/eebbk/37594');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '高途', 'https://app.mokahr.com/campus-recruitment/bjhl/102145', 'official', 'moka', 'playwright', 'private', '教育', '高途（教育，probe live 探活 在华 92 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/bjhl/102145');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '好未来', 'https://app.mokahr.com/campus-recruitment/tal/146099', 'official', 'moka', 'playwright', 'private', '教育', '好未来（教育，probe live 探活 在华 390 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/tal/146099');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '瑞幸咖啡', 'https://app.mokahr.com/campus_apply/lkcoffee/45257', 'official', 'moka', 'playwright', 'private', '新消费', '瑞幸咖啡（新消费，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/lkcoffee/45257');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '古茗', 'https://app.mokahr.com/campus-recruitment/guming', 'official', 'moka', 'playwright', 'private', '新消费', '古茗（新消费，probe live 探活 在华 23 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/guming');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '雪球', 'https://app.mokahr.com/campus_apply/xueqiu/3590', 'official', 'moka', 'playwright', 'private', '互联网', '雪球（互联网，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/xueqiu/3590');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '搜狐', 'https://app.mokahr.com/campus_apply/sohu/5682', 'official', 'moka', 'playwright', 'private', '互联网', '搜狐（互联网，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/sohu/5682');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '搜狐畅游', 'https://app.mokahr.com/campus_apply/cyou-inc/42233', 'official', 'moka', 'playwright', 'private', '游戏', '搜狐畅游（游戏，probe live 探活 在华 64 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/cyou-inc/42233');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '巨人网络', 'https://app.mokahr.com/apply/ztgame/37485', 'official', 'moka', 'playwright', 'private', '游戏', '巨人网络（游戏，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/ztgame/37485');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '完美世界', 'https://app.mokahr.com/campus-recruitment/pwrd/140155', 'official', 'moka', 'playwright', 'private', '游戏', '完美世界（游戏，probe live 探活 在华 29 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/pwrd/140155');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '绿盟科技', 'https://app.mokahr.com/campus_apply/nsfocus/29118', 'official', 'moka', 'playwright', 'private', '网络安全', '绿盟科技（网络安全，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/nsfocus/29118');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '知乎', 'https://app.mokahr.com/campus_apply/zhihu/3818', 'official', 'moka', 'playwright', 'private', '互联网', '知乎（互联网，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/zhihu/3818');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '万物云', 'https://app.mokahr.com/campus-recruitment/vanke/147055', 'official', 'moka', 'playwright', 'private', '物业服务', '万物云（物业服务，probe live 探活 在华 100 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/vanke/147055');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '鸿星尔克', 'https://app.mokahr.com/campus-recruitment/erke/150889', 'official', 'moka', 'playwright', 'private', '服装', '鸿星尔克（服装，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/erke/150889');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'C咖', 'https://app.mokahr.com/campus-recruitment/tuiquan/67992', 'official', 'moka', 'playwright', 'private', '美妆', 'C咖（美妆，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/tuiquan/67992');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '数字马力', 'https://app.mokahr.com/campus-recruitment/digital-engine/144933', 'official', 'moka', 'playwright', 'private', '互联网', '数字马力（互联网，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/digital-engine/144933');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '强力巨彩', 'https://app.mokahr.com/campus-recruitment/qljc/146375', 'official', 'moka', 'playwright', 'private', '智能硬件', '强力巨彩（智能硬件，probe live 探活 在华 22 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/qljc/146375');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'HFC食品', 'https://app.mokahr.com/campus-recruitment/hfc-foods/102201', 'official', 'moka', 'playwright', 'private', '食品', 'HFC食品（食品，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/hfc-foods/102201');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '戴永红', 'https://app.mokahr.com/campus-recruitment/daiyonghong/145017', 'official', 'moka', 'playwright', 'private', '零售', '戴永红（零售，probe live 探活 在华 4 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/daiyonghong/145017');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '驭势科技', 'https://app.mokahr.com/campus_apply/yushi/3773', 'official', 'moka', 'playwright', 'private', '自动驾驶', '驭势科技（自动驾驶，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/yushi/3773');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '流利说', 'https://app.mokahr.com/campus_apply/liulishuo/2402', 'official', 'moka', 'playwright', 'private', '教育', '流利说（教育，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/liulishuo/2402');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华兴资本', 'https://app.mokahr.com/campus_apply/huaxing/6790', 'official', 'moka', 'playwright', 'private', '金融', '华兴资本（金融，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/huaxing/6790');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '丁香园', 'https://app.mokahr.com/campus_apply/dxy/1488', 'official', 'moka', 'playwright', 'private', '互联网医疗', '丁香园（互联网医疗，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/dxy/1488');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '轻松集团', 'https://app.mokahr.com/campus_apply/qsc/2817', 'official', 'moka', 'playwright', 'private', '互联网保险', '轻松集团（互联网保险，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/qsc/2817');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '基蛋生物', 'https://app.mokahr.com/campus-recruitment/getein/74361', 'official', 'moka', 'playwright', 'private', '医疗器械', '基蛋生物（医疗器械，probe live 探活 在华 26 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/getein/74361');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '途游游戏', 'https://app.mokahr.com/campus-recruitment/tuyoogame/146219', 'official', 'moka', 'playwright', 'private', '游戏', '途游游戏（游戏，probe live 探活 在华 83 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/tuyoogame/146219');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '无忧传媒', 'https://app.mokahr.com/campus_apply/joymedia/7674', 'official', 'moka', 'playwright', 'private', 'MCN', '无忧传媒（MCN，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/joymedia/7674');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '小赢科技', 'https://app.mokahr.com/campus-recruitment/xiaoying/148851', 'official', 'moka', 'playwright', 'private', '金融科技', '小赢科技（金融科技，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/xiaoying/148851');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '文远知行', 'https://app.mokahr.com/campus_apply/jingchi/2137', 'official', 'moka', 'playwright', 'private', '自动驾驶', '文远知行（自动驾驶，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/jingchi/2137');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '斗鱼', 'https://app.mokahr.com/campus_apply/douyu/21995', 'official', 'moka', 'playwright', 'private', '直播', '斗鱼（直播，probe live 探活 在华 4 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/douyu/21995');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东方财富', 'https://app.mokahr.com/campus-recruitment/eastmoney/92400', 'official', 'moka', 'playwright', 'private', '互联网金融', '东方财富（互联网金融，probe live 探活 在华 65 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/eastmoney/92400');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'MAIA ACTIVE', 'https://app.mokahr.com/apply/maia/21988', 'official', 'moka', 'playwright', 'private', '服装', 'MAIA ACTIVE（服装，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/maia/21988');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '安谋科技', 'https://app.mokahr.com/apply/armchina/885', 'official', 'moka', 'playwright', 'private', '半导体', '安谋科技（半导体，probe live 探活 在华 45 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/armchina/885');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '同盾科技', 'https://app.mokahr.com/apply/tongdun/29005', 'official', 'moka', 'playwright', 'private', '金融科技', '同盾科技（金融科技，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/tongdun/29005');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '芯驰科技', 'https://app.mokahr.com/apply/semidrive/42940', 'official', 'moka', 'playwright', 'private', '半导体', '芯驰科技（半导体，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/semidrive/42940');

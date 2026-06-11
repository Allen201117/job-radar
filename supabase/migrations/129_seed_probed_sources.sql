-- 129 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '万科企业', 'https://app.mokahr.com/social-recruitment/vanke/36266', 'official', 'moka', 'playwright', 'private', '地产', '万科企业（地产，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/vanke/36266');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '浙江吉利控股集团', 'https://app.mokahr.com/social-recruitment/geely/96123', 'official', 'moka', 'playwright', 'private', '汽车', '浙江吉利控股集团（汽车，probe live 探活 在华 1551 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/geely/96123');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '万向集团', 'https://app.mokahr.com/social-recruitment/wanxiang/142474', 'official', 'moka', 'playwright', 'private', '汽车零部件', '万向集团（汽车零部件，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/wanxiang/142474');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '正泰集团', 'https://app.mokahr.com/social-recruitment/chint/40744', 'official', 'moka', 'playwright', 'private', '电气', '正泰集团（电气，probe live 探活 294 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/chint/40744');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '牧原实业集团', 'https://app.mokahr.com/social-recruitment/muyuan/70115', 'official', 'moka', 'playwright', 'private', '养殖', '牧原实业集团（养殖，probe live 探活 在华 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/muyuan/70115');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '天合光能', 'https://app.mokahr.com/social-recruitment/trinasolar/98958', 'official', 'moka', 'playwright', 'private', '光伏', '天合光能（光伏，probe live 探活 67 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/trinasolar/98958');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '温氏食品集团', 'https://app.mokahr.com/social-recruitment/wens/92365', 'official', 'moka', 'playwright', 'private', '养殖', '温氏食品集团（养殖，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/wens/92365');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '汇通达网络', 'https://app.mokahr.com/social-recruitment/huitongda/3951', 'official', 'moka', 'playwright', 'private', '互联网', '汇通达网络（互联网，probe live 探活 11 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/huitongda/3951');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '阳光电源', 'https://app.mokahr.com/social-recruitment/sungrow/94415', 'official', 'moka', 'playwright', 'private', '光伏', '阳光电源（光伏，probe live 探活 在华 103 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/sungrow/94415');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '安踏体育用品集团', 'https://app.mokahr.com/social-recruitment/antahr/146041', 'official', 'moka', 'playwright', 'private', '服装', '安踏体育用品集团（服装，probe live 探活 在华 1040 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/antahr/146041');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '江苏满运软件科技', 'https://app.mokahr.com/social-recruitment/manbang/46269', 'official', 'moka', 'playwright', 'private', '互联网', '江苏满运软件科技（互联网，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/manbang/46269');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁波均胜电子', 'https://app.mokahr.com/social-recruitment/joyson/94310', 'official', 'moka', 'playwright', 'private', '汽车零部件', '宁波均胜电子（汽车零部件，probe live 探活 在华 265 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/joyson/94310');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '雅迪科技集团', 'https://app.mokahr.com/social-recruitment/yadea/26984', 'official', 'moka', 'playwright', 'private', '电动车', '雅迪科技集团（电动车，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/yadea/26984');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '申通快递', 'https://app.mokahr.com/social-recruitment/sto/42337', 'official', 'moka', 'playwright', 'private', '物流', '申通快递（物流，probe live 探活 146 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/sto/42337');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '森马集团', 'https://app.mokahr.com/social-recruitment/senma/95960', 'official', 'moka', 'playwright', 'private', '服装', '森马集团（服装，probe live 探活 101 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/senma/95960');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '浙江大华技术', 'https://app.mokahr.com/social-recruitment/dahua/55997', 'official', 'moka', 'playwright', 'private', '安防', '浙江大华技术（安防，probe live 探活 42 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/dahua/55997');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '舜宇集团', 'https://app.mokahr.com/social-recruitment/sunnyoptical/45601', 'official', 'moka', 'playwright', 'private', '光学', '舜宇集团（光学，probe live 探活 773 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/sunnyoptical/45601');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广东联塑科技实业', 'https://app.mokahr.com/social-recruitment/lesso/70302', 'official', 'moka', 'playwright', 'private', '新材料', '广东联塑科技实业（新材料，probe live 探活 在华 38 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/lesso/70302');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中微公司', 'https://app.mokahr.com/social-recruitment/amec/28371', 'official', 'moka', 'playwright', 'private', '半导体', '中微公司（半导体，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/amec/28371');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '百济神州', 'https://app.mokahr.com/social-recruitment/beigene/98934', 'official', 'moka', 'playwright', 'private', '生物医药', '百济神州（生物医药，probe live 探活 在华 336 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/beigene/98934');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '江苏恒瑞医药', 'https://app.mokahr.com/social-recruitment/hengrui/145996', 'official', 'moka', 'playwright', 'private', '医药', '江苏恒瑞医药（医药，probe live 探活 在华 654 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/hengrui/145996');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '药明生物', 'https://app.mokahr.com/social-recruitment/wuxibiologics/99960', 'official', 'moka', 'playwright', 'private', '医药外包', '药明生物（医药外包，probe live 探活 在华 648 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/wuxibiologics/99960');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '途虎养车', 'https://app.mokahr.com/social-recruitment/tuhu/6848', 'official', 'moka', 'playwright', 'private', '互联网', '途虎养车（互联网，probe live 探活 在华 162 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/tuhu/6848');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '金山办公', 'https://app.mokahr.com/social-recruitment/wps/3471', 'official', 'moka', 'playwright', 'private', '软件', '金山办公（软件，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/wps/3471');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广联达', 'https://app.mokahr.com/social-recruitment/glodon/1751', 'official', 'moka', 'playwright', 'private', '软件', '广联达（软件，probe live 探活 25 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/glodon/1751');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云从科技', 'https://app.mokahr.com/social-recruitment/cloudwalk/4871', 'official', 'moka', 'playwright', 'private', '人工智能', '云从科技（人工智能，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/cloudwalk/4871');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '第四范式', 'https://app.mokahr.com/social-recruitment/4paradigm/102013', 'official', 'moka', 'playwright', 'private', '人工智能', '第四范式（人工智能，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/4paradigm/102013');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海能达', 'https://app.mokahr.com/social-recruitment/hytera/27049', 'official', 'moka', 'playwright', 'private', '通信设备', '海能达（通信设备，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/hytera/27049');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深信服', 'https://app.mokahr.com/social-recruitment/sangfor/5367', 'official', 'moka', 'playwright', 'private', '网络安全', '深信服（网络安全，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/sangfor/5367');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '老板电器', 'https://app.mokahr.com/social-recruitment/robam/27897', 'official', 'moka', 'playwright', 'private', '家电', '老板电器（家电，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/robam/27897');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '九号公司', 'https://app.mokahr.com/social-recruitment/ninebot/45626', 'official', 'moka', 'playwright', 'private', '智能硬件', '九号公司（智能硬件，probe live 探活 在华 122 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/ninebot/45626');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '极米科技', 'https://app.mokahr.com/social-recruitment/xgimi/142344', 'official', 'moka', 'playwright', 'private', '智能硬件', '极米科技（智能硬件，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/xgimi/142344');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深天马', 'https://app.mokahr.com/social-recruitment/tianma/143383', 'official', 'moka', 'playwright', 'private', '显示面板', '深天马（显示面板，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/tianma/143383');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '众安保险', 'https://app.mokahr.com/social-recruitment/zhongan/102015', 'official', 'moka', 'playwright', 'private', '保险', '众安保险（保险，probe live 探活 在华 21 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/zhongan/102015');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '微医集团', 'https://app.mokahr.com/social-recruitment/wedoctor/41066', 'official', 'moka', 'playwright', 'private', '互联网医疗', '微医集团（互联网医疗，probe live 探活 492 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/wedoctor/41066');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '三只松鼠', 'https://app.mokahr.com/social-recruitment/3songshu/458', 'official', 'moka', 'playwright', 'private', '食品', '三只松鼠（食品，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/3songshu/458');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '九毛九', 'https://app.mokahr.com/social-recruitment/jiumaojiu/72282', 'official', 'moka', 'playwright', 'private', '餐饮', '九毛九（餐饮，probe live 探活 在华 26 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/jiumaojiu/72282');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '晨光文具', 'https://app.mokahr.com/social-recruitment/mg/142712', 'official', 'moka', 'playwright', 'private', '文具', '晨光文具（文具，probe live 探活 42 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/mg/142712');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '特步', 'https://app.mokahr.com/social-recruitment/xtep/148870', 'official', 'moka', 'playwright', 'private', '服装', '特步（服装，probe live 探活 在华 117 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/xtep/148870');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '江南布衣', 'https://app.mokahr.com/social-recruitment/jnby/53908', 'official', 'moka', 'playwright', 'private', '服装', '江南布衣（服装，probe live 探活 63 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/jnby/53908');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '徐工机械', 'https://app.mokahr.com/social-recruitment/xcmg/148090', 'official', 'moka', 'playwright', 'private', '工程机械', '徐工机械（工程机械，probe live 探活 在华 8 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/xcmg/148090');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中控技术', 'https://app.mokahr.com/social-recruitment/supcon/78261', 'official', 'moka', 'playwright', 'private', '工业软件', '中控技术（工业软件，probe live 探活 在华 123 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/supcon/78261');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '速腾聚创', 'https://app.mokahr.com/social-recruitment/robosense/77883', 'official', 'moka', 'playwright', 'private', '激光雷达', '速腾聚创（激光雷达，probe live 探活 150 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/robosense/77883');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '科华数据', 'https://app.mokahr.com/social-recruitment/kehua/116137', 'official', 'moka', 'playwright', 'private', '储能', '科华数据（储能，probe live 探活 在华 141 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/kehua/116137');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '当升科技', 'https://app.mokahr.com/social-recruitment/easpring/102151', 'official', 'moka', 'playwright', 'private', '锂电', '当升科技（锂电，probe live 探活 97 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/easpring/102151');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '添可', 'https://app.mokahr.com/social-recruitment/tineco/36091', 'official', 'moka', 'playwright', 'private', '智能硬件', '添可（智能硬件，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/tineco/36091');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '涂鸦智能', 'https://app.mokahr.com/social-recruitment/tuya/3236', 'official', 'moka', 'playwright', 'private', '物联网', '涂鸦智能（物联网，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/tuya/3236');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '锐捷网络', 'https://app.mokahr.com/social-recruitment/ruijie/26518', 'official', 'moka', 'playwright', 'private', '通信设备', '锐捷网络（通信设备，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/ruijie/26518');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '移远通信', 'https://app.mokahr.com/social-recruitment/quectel/24304', 'official', 'moka', 'playwright', 'private', '物联网', '移远通信（物联网，probe live 探活 在华 11 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/quectel/24304');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '光迅科技', 'https://app.mokahr.com/social-recruitment/accelink/139972', 'official', 'moka', 'playwright', 'private', '光通信', '光迅科技（光通信，probe live 探活 在华 9 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/accelink/139972');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '大族激光', 'https://app.mokahr.com/social-recruitment/hanslaser/46382', 'official', 'moka', 'playwright', 'private', '激光', '大族激光（激光，probe live 探活 45 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/hanslaser/46382');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '燧原科技', 'https://app.mokahr.com/social-recruitment/enflame/40891', 'official', 'moka', 'playwright', 'private', 'AI芯片', '燧原科技（AI芯片，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/enflame/40891');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '壁仞科技', 'https://app.mokahr.com/social-recruitment/biren/44726', 'official', 'moka', 'playwright', 'private', 'AI芯片', '壁仞科技（AI芯片，probe live 探活 在华 41 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/biren/44726');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '微创医疗', 'https://app.mokahr.com/social-recruitment/microport/46967', 'official', 'moka', 'playwright', 'private', '医疗器械', '微创医疗（医疗器械，probe live 探活 73 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/microport/46967');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '明源云', 'https://app.mokahr.com/social-recruitment/mingyuan/36251', 'official', 'moka', 'playwright', 'private', '软件', '明源云（软件，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/mingyuan/36251');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '沐曦集成电路', 'https://app.mokahr.com/social-recruitment/metax-tech/58147', 'official', 'moka', 'playwright', 'private', 'AI芯片', '沐曦集成电路（AI芯片，probe live 探活 在华 71 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/metax-tech/58147');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '全志科技股份有限公司', 'https://app.mokahr.com/social-recruitment/allwinnertech/67887', 'official', 'moka', 'playwright', 'private', '嵌入式/多媒体芯片设计', '全志科技股份有限公司（嵌入式/多媒体芯片设计，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/allwinnertech/67887');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华大九天科技股份有限公司', 'https://app.mokahr.com/social-recruitment/empyrean/118495', 'official', 'moka', 'playwright', 'private', 'EDA工具', '华大九天科技股份有限公司（EDA工具，probe live 探活 在华 34 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/empyrean/118495');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '安路科技（上海）有限公司', 'https://app.mokahr.com/social-recruitment/anlogic/46365', 'official', 'moka', 'playwright', 'private', 'FPGA芯片设计', '安路科技（上海）有限公司（FPGA芯片设计，probe live 探活 34 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/anlogic/46365');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广立微电子科技（杭州）有限公司', 'https://app.mokahr.com/social-recruitment/semitronix/140042', 'official', 'moka', 'playwright', 'private', 'EDA/良率分析工具', '广立微电子科技（杭州）有限公司（EDA/良率分析工具，probe live 探活 在华 25 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/semitronix/140042');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '天数智芯（上海）半导体有限公司', 'https://app.mokahr.com/social-recruitment/iluvatar/98705', 'official', 'moka', 'playwright', 'private', 'AI GPU芯片设计', '天数智芯（上海）半导体有限公司（AI GPU芯片设计，probe live 探活 在华 77 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/iluvatar/98705');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '药明合联生物技术有限公司', 'https://app.mokahr.com/social-recruitment/wuxixdc/164235', 'official', 'moka', 'playwright', 'private', 'CXO/ADC偶联药物CDMO', '药明合联生物技术有限公司（CXO/ADC偶联药物CDMO，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/wuxixdc/164235');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '康龙化成（北京）新药技术股份有限公司', 'https://app.mokahr.com/social-recruitment/pharmaron/44351', 'official', 'moka', 'playwright', 'private', 'CXO/新药研发服务', '康龙化成（北京）新药技术股份有限公司（CXO/新药研发服务，probe live 探活 129 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/pharmaron/44351');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云顶新耀医疗科技有限公司', 'https://app.mokahr.com/social-recruitment/everestmedicines/150886', 'official', 'moka', 'playwright', 'private', '创新药/许可引进', '云顶新耀医疗科技有限公司（创新药/许可引进，probe live 探活 在华 109 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/everestmedicines/150886');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '人福医药集团股份公司', 'https://app.mokahr.com/social-recruitment/humanwell/148229', 'official', 'moka', 'playwright', 'private', '医药制造/麻醉生殖', '人福医药集团股份公司（医药制造/麻醉生殖，probe live 探活 在华 25 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/humanwell/148229');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '国药集团化学试剂有限公司（国药控股）', 'https://app.mokahr.com/social-recruitment/sinopharm/56224', 'official', 'moka', 'playwright', 'private', '医药流通/疫苗', '国药集团化学试剂有限公司（国药控股）（医药流通/疫苗，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/sinopharm/56224');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '南京诺唯赞生物科技股份有限公司', 'https://app.mokahr.com/social-recruitment/vazyme/7812', 'official', 'moka', 'playwright', 'private', '生命科学工具/分子诊断', '南京诺唯赞生物科技股份有限公司（生命科学工具/分子诊断，probe live 探活 在华 17 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/vazyme/7812');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '嘉会国际医院', 'https://app.mokahr.com/social-recruitment/jiahui/2126', 'official', 'moka', 'playwright', 'private', '医疗服务', '嘉会国际医院（医疗服务，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/jiahui/2126');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '麦当劳（中国）有限公司', 'https://app.mokahr.com/social-recruitment/mcdchina/4610', 'official', 'moka', 'playwright', 'private', '餐饮连锁/快餐', '麦当劳（中国）有限公司（餐饮连锁/快餐，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/mcdchina/4610');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '顾家家居股份有限公司', 'https://app.mokahr.com/social-recruitment/kuka/98960', 'official', 'moka', 'playwright', 'private', '家居家纺', '顾家家居股份有限公司（家居家纺，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/kuka/98960');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '欧派家居集团股份有限公司', 'https://app.mokahr.com/social-recruitment/oppein/78239', 'official', 'moka', 'playwright', 'private', '家居家纺', '欧派家居集团股份有限公司（家居家纺，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/oppein/78239');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '喜临门家具股份有限公司', 'https://app.mokahr.com/social-recruitment/sleemon/102128', 'official', 'moka', 'playwright', 'private', '家居家纺', '喜临门家具股份有限公司（家居家纺，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/sleemon/102128');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '浙江南都电源动力股份有限公司', 'https://app.mokahr.com/social-recruitment/narada/36367', 'official', 'moka', 'playwright', 'private', '储能电池', '浙江南都电源动力股份有限公司（储能电池，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/narada/36367');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '岚图汽车科技有限公司', 'https://app.mokahr.com/social-recruitment/voyah/146292', 'official', 'moka', 'playwright', 'private', '汽车整车/新能源汽车', '岚图汽车科技有限公司（汽车整车/新能源汽车，probe live 探活 在华 901 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/voyah/146292');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '佛吉亚（中国）投资有限公司', 'https://app.mokahr.com/social-recruitment/faurecia/146092', 'official', 'moka', 'playwright', 'private', '汽车零部件/内饰', '佛吉亚（中国）投资有限公司（汽车零部件/内饰，probe live 探活 在华 72 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/faurecia/146092');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '元戎启行科技有限公司', 'https://app.mokahr.com/social-recruitment/deeproute/143885', 'official', 'moka', 'playwright', 'private', '智能驾驶/自动驾驶', '元戎启行科技有限公司（智能驾驶/自动驾驶，probe live 探活 92 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/deeproute/143885');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '福瑞泰克智能系统有限公司', 'https://app.mokahr.com/social-recruitment/freetech/42354', 'official', 'moka', 'playwright', 'private', '智能驾驶/ADAS', '福瑞泰克智能系统有限公司（智能驾驶/ADAS，probe live 探活 在华 63 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/freetech/42354');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '北京微步在线科技有限公司', 'https://app.mokahr.com/social-recruitment/threatbook/27229', 'official', 'moka', 'playwright', 'private', '网络安全/威胁情报', '北京微步在线科技有限公司（网络安全/威胁情报，probe live 探活 在华 11 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/threatbook/27229');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中兴通讯股份有限公司', 'https://app.mokahr.com/social-recruitment/zte/47588', 'official', 'moka', 'playwright', 'private', '通信设备/云计算', '中兴通讯股份有限公司（通信设备/云计算，probe live 探活 在华 94 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/zte/47588');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海星环信息科技有限公司', 'https://app.mokahr.com/social-recruitment/transwarp/140922', 'official', 'moka', 'playwright', 'private', '大数据/数据库', '上海星环信息科技有限公司（大数据/数据库，probe live 探活 在华 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/transwarp/140922');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '北京观远数据有限公司', 'https://app.mokahr.com/social-recruitment/guandata/36965', 'official', 'moka', 'playwright', 'private', 'BI/数据分析SaaS', '北京观远数据有限公司（BI/数据分析SaaS，probe live 探活 在华 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/guandata/36965');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海鹰瞳医疗科技集团股份有限公司', 'https://app.mokahr.com/social-recruitment/zulong/25157', 'official', 'moka', 'playwright', 'private', '游戏', '上海鹰瞳医疗科技集团股份有限公司（游戏，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/zulong/25157');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '北京微播视界科技有限公司', 'https://app.mokahr.com/social-recruitment/weiboyi/28976', 'official', 'moka', 'playwright', 'private', 'MCN/营销', '北京微播视界科技有限公司（MCN/营销，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/weiboyi/28976');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '太古地产有限公司', 'https://app.mokahr.com/social-recruitment/swireproperties/126011', 'official', 'moka', 'playwright', 'private', '商业地产', '太古地产有限公司（商业地产，probe live 探活 在华 51 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/swireproperties/126011');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '国泰君安证券股份有限公司', 'https://app.mokahr.com/social-recruitment/gtjas/45104', 'official', 'moka', 'playwright', 'private', '综合证券', '国泰君安证券股份有限公司（综合证券，probe live 探活 5 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/gtjas/45104');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '国双科技（北京）有限公司', 'https://app.mokahr.com/social-recruitment/gridsum/74006', 'official', 'moka', 'playwright', 'private', '教育大数据', '国双科技（北京）有限公司（教育大数据，probe live 探活 14 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/gridsum/74006');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳市雷赛智能控制股份有限公司', 'https://app.mokahr.com/social-recruitment/leisai/115938', 'official', 'moka', 'playwright', 'private', '运动控制/工业自动化', '深圳市雷赛智能控制股份有限公司（运动控制/工业自动化，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/leisai/115938');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '道达尔能源化工（中国）有限公司', 'https://app.mokahr.com/social-recruitment/totalenergies/100441', 'official', 'moka', 'playwright', 'private', '石化/特种材料', '道达尔能源化工（中国）有限公司（石化/特种材料，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/totalenergies/100441');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '荷美尔食品（中国）有限公司', 'https://app.mokahr.com/social-recruitment/hormel/35962', 'official', 'moka', 'playwright', 'private', '肉类食品加工', '荷美尔食品（中国）有限公司（肉类食品加工，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/hormel/35962');

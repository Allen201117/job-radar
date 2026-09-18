-- 273_backfill_industry_group_post_265_seeds.sql
--
-- 背景：迁移 265（2026-09-17 18:06 UTC）是一次性 CASE 回填，把当时 sources.industry 的 433 种自由
-- 写法归一成 industry_group；迁移 271 处理的是 industry 本身为 NULL 的 142 条。两者都覆盖不到
-- **265 跑完之后由 seed 迁移新插入、且 seed 里没有内联 industry_group 的行**。
-- live 全量核实（2026-09-18，Supabase sources 直连）：industry 有值 & industry_group 为 NULL 的行共
-- 48 条（enabled 46 + disabled 2），created_at 全部在 2026-09-17 18:32 / 19:39 / 23:33
-- （268~270 一带的 seed 与其后两条）。ownership 也同样是 NULL（265 第 6 步同样没覆盖到它们），
-- 且 live 核实「ownership 为 NULL」的行恰好就是这 48 条（其余 0 条）。
--
-- ⚠️ 这批的成因不只是「新写法」：48 行里 22 行的 industry（证券、医药、锂电、光伏、地产/建筑、游戏、汽车零部件、化工、制造/工业、消费/零售、机器人、IVD体外诊断、综合证券）
-- 早就在 lib/industry-taxonomy.json 里，照样是 NULL——因为 JSON 只在 265 那一次被展开成 SQL，
-- 之后插入的行没有任何东西替它们查表。迁移 270 / 272 起 seed 已改为内联写 industry_group / ownership，
-- 这是新 seed 必须沿用的写法；本迁移只清 268~269 一带漏掉的存量。
--
-- 方法：
-- ① 逐行按 id 回填（不按公司名，避免「京东 vs 京东方」式误伤），每行注释写明 industry → group 与依据；
--    group 取值 = 更新后的 lib/industry-taxonomy.json（_version 2026-09-18-v2）对该 industry 的映射，
--    17 种新写法的先例逐条见下方分段注释；
-- ② 兜底 CASE：把 v2 JSON 全量 450 条 mapping 展开（与 265 同一生成方式，不要手改），只作用于
--    「industry 有值且 industry_group 仍为 NULL」的行——接住本迁移落地前又被 seed 进来、industry
--    写法已收录的行。**映射不到的行保持 NULL、不落 'other'**：NULL 才会在普查里露出来提醒人补表，
--    'other' 是「有标签但不属于 11 个行业」的定论（见 crawler/industry_taxonomy.py 顶部注释）。
-- ③ ownership：沿用 265 第 6 步的机械规则（segment 是 soe/private/foreign 就照抄，否则 unknown），
--    只补 ownership 为 NULL 的行，不做任何名称启发式。
--
-- 刻意留 NULL 的 2 行：天康生物 (743ccece-65f0-43e7-8b70-cb9440843b39) industry=生物制药·农牧；天康生物 (72aca9d1-15e2-4ea4-a754-84815e59a29c) industry=生物制药·农牧。
--   理由：两段分属不同组（生物制药→医疗/医药，农牧饲料/养殖→消费/零售）；天康生物营收以饲料+生猪养殖为主、兽用疫苗为创业主业，无单一主导 → 同 271 对横店集团的处理，留 NULL 待创始人定。
--
-- 影响面（live，2026-09-18）：本迁移回填 industry_group 46 行（enabled 44 + disabled 2）、
-- ownership 48 行。这 46 条 enabled 源在香港 jobs 库里挂着 1,737 个 active 校招/实习岗（校招 1,634 + 实习 103，
-- 按 source_id 精确统计），回填后其中 1,731 个归进某个 industry_group，天康生物的 6 个随 NULL 继续不计入任何行业。

set local statement_timeout = '1800s';

-- ============================================================
-- ① 逐行按 id 回填 industry_group
-- ============================================================

-- industry='IVD体外诊断' → '医疗/医药'：265 已收录的写法，行是 265 之后插入的
-- 广州万孚生物技术股份有限公司 (cdbfe261-a302-44b7-abec-5f21dac65f23) [disabled]
update sources set industry_group = '医疗/医药' where id = 'cdbfe261-a302-44b7-abec-5f21dac65f23' and industry_group is null;

-- industry='光伏' → '制造/工业'：265 已收录的写法，行是 265 之后插入的
-- 创维光伏 (d0d2e3c5-9355-460f-98b0-c7d1b05e1712)
update sources set industry_group = '制造/工业' where id = 'd0d2e3c5-9355-460f-98b0-c7d1b05e1712' and industry_group is null;

-- industry='制造/工业' → '制造/工业'：265 已收录的写法，行是 265 之后插入的
-- 松下 (30fd116e-7797-4aaa-9a1f-6d252318ca1b)
update sources set industry_group = '制造/工业' where id = '30fd116e-7797-4aaa-9a1f-6d252318ca1b' and industry_group is null;

-- industry='化工' → '能源/化工'：265 已收录的写法，行是 265 之后插入的
-- 新疆天业集团 (b625d24a-6587-4ae8-b93f-2d1e31a4c441)
update sources set industry_group = '能源/化工' where id = 'b625d24a-6587-4ae8-b93f-2d1e31a4c441' and industry_group is null;

-- industry='医药' → '医疗/医药'：265 已收录的写法，行是 265 之后插入的
-- 京新药业 (8005e821-9f32-440e-b264-e79a6efeb308)
update sources set industry_group = '医疗/医药' where id = '8005e821-9f32-440e-b264-e79a6efeb308' and industry_group is null;
-- 信立泰药业 (77a82cfb-7916-454d-85b7-bb51a71f7224)
update sources set industry_group = '医疗/医药' where id = '77a82cfb-7916-454d-85b7-bb51a71f7224' and industry_group is null;
-- 信立泰药业 (2a11da5c-3b69-4952-9ffb-a1c119bf0c47)
update sources set industry_group = '医疗/医药' where id = '2a11da5c-3b69-4952-9ffb-a1c119bf0c47' and industry_group is null;
-- 哈药集团 (39e42ef9-86ea-4c57-b47d-901382f81e1d)
update sources set industry_group = '医疗/医药' where id = '39e42ef9-86ea-4c57-b47d-901382f81e1d' and industry_group is null;
-- 海正药业 (9896e4d4-09b8-4c1b-b265-973ebf0d65a9)
update sources set industry_group = '医疗/医药' where id = '9896e4d4-09b8-4c1b-b265-973ebf0d65a9' and industry_group is null;
-- 迪康药业 (0d65a1bb-883f-4d44-97ff-82f4c29f221f)
update sources set industry_group = '医疗/医药' where id = '0d65a1bb-883f-4d44-97ff-82f4c29f221f' and industry_group is null;

-- industry='地产/建筑' → '地产/建筑'：265 已收录的写法，行是 265 之后插入的
-- 华润置地 (93af880b-5e05-4053-9a5e-6700e9597de2)
update sources set industry_group = '地产/建筑' where id = '93af880b-5e05-4053-9a5e-6700e9597de2' and industry_group is null;

-- industry='机器人' → '制造/工业'：265 已收录的写法，行是 265 之后插入的
-- 越疆科技 (ba06b215-a086-4d85-85af-233dfc2efa52)
update sources set industry_group = '制造/工业' where id = 'ba06b215-a086-4d85-85af-233dfc2efa52' and industry_group is null;

-- industry='汽车零部件' → '汽车/出行'：265 已收录的写法，行是 265 之后插入的
-- 延锋 (10389273-642a-4495-9a3e-c4ddb002a7f6)
update sources set industry_group = '汽车/出行' where id = '10389273-642a-4495-9a3e-c4ddb002a7f6' and industry_group is null;
-- 延锋 (843f1954-b67e-4e29-8238-57836b548562)
update sources set industry_group = '汽车/出行' where id = '843f1954-b67e-4e29-8238-57836b548562' and industry_group is null;

-- industry='消费/零售' → '消费/零售'：265 已收录的写法，行是 265 之后插入的
-- 爱慕股份 (b36768ce-abc5-497d-9053-d249202af908)
update sources set industry_group = '消费/零售' where id = 'b36768ce-abc5-497d-9053-d249202af908' and industry_group is null;

-- industry='游戏' → '互联网/科技'：265 已收录的写法，行是 265 之后插入的
-- 完美世界 校招 (5569bc76-4ed0-4a14-a7eb-a19979d5f3cf)
update sources set industry_group = '互联网/科技' where id = '5569bc76-4ed0-4a14-a7eb-a19979d5f3cf' and industry_group is null;

-- industry='综合证券' → '金融'：265 已收录的写法，行是 265 之后插入的
-- 国泰君安证券股份有限公司 (d2570384-7bab-4695-b848-b411576dc59e) [disabled]
update sources set industry_group = '金融' where id = 'd2570384-7bab-4695-b848-b411576dc59e' and industry_group is null;

-- industry='证券' → '金融'：265 已收录的写法，行是 265 之后插入的
-- 中信建投证券 (a24dc855-740a-4d23-ab09-e6d4180ee761)
update sources set industry_group = '金融' where id = 'a24dc855-740a-4d23-ab09-e6d4180ee761' and industry_group is null;
-- 中泰证券 (ed9a8ba9-714b-4aa6-8997-fbf7d92ce04d)
update sources set industry_group = '金融' where id = 'ed9a8ba9-714b-4aa6-8997-fbf7d92ce04d' and industry_group is null;
-- 中泰证券 (d482ec0d-77c7-4c4e-8337-5bf4d1cd1170)
update sources set industry_group = '金融' where id = 'd482ec0d-77c7-4c4e-8337-5bf4d1cd1170' and industry_group is null;
-- 国金证券 (9beab86f-b5b7-435c-9fb3-d38c8b43268f)
update sources set industry_group = '金融' where id = '9beab86f-b5b7-435c-9fb3-d38c8b43268f' and industry_group is null;

-- industry='锂电' → '制造/工业'：265 已收录的写法，行是 265 之后插入的
-- 亿纬锂能 校招 (3346fe9d-ca96-402b-9a7f-52de24937c0f)
update sources set industry_group = '制造/工业' where id = '3346fe9d-ca96-402b-9a7f-52de24937c0f' and industry_group is null;

-- industry='乳制品' → '消费/零售'：先例 乳业·消费 / 食品·乳业 → 消费/零售
-- 山东得益乳业 (0fd61526-d972-4914-8c44-f39e481b9089)
update sources set industry_group = '消费/零售' where id = '0fd61526-d972-4914-8c44-f39e481b9089' and industry_group is null;
-- 山东得益乳业 (1816141a-8a68-4f07-9fd0-829be62e48f7)
update sources set industry_group = '消费/零售' where id = '1816141a-8a68-4f07-9fd0-829be62e48f7' and industry_group is null;

-- industry='办公用品·B2B' → '消费/零售'：先例 文具 → 消费/零售（齐心集团=办公文具制造 + B2B 办公采购）
-- 齐心集团 (ee1eba5a-76b9-4835-b452-eac2f9d14db9)
update sources set industry_group = '消费/零售' where id = 'ee1eba5a-76b9-4835-b452-eac2f9d14db9' and industry_group is null;

-- industry='商用车' → '汽车/出行'：先例 汽车整车/合资 / 汽车制造 → 汽车/出行
-- 陕汽控股 (ba19aafb-6fe4-41b2-ac0f-ca53e39ad694)
update sources set industry_group = '汽车/出行' where id = 'ba19aafb-6fe4-41b2-ac0f-ca53e39ad694' and industry_group is null;

-- industry='客车' → '汽车/出行'：先例 汽车整车/合资 / 汽车制造 → 汽车/出行
-- 宇通集团 (d3cdfbed-0272-4b34-80ad-7cc4770196eb)
update sources set industry_group = '汽车/出行' where id = 'd3cdfbed-0272-4b34-80ad-7cc4770196eb' and industry_group is null;

-- industry='工业机器人·电梯控制' → '制造/工业'：先例 工业机器人 / 工业·电梯 → 制造/工业
-- 新时达 (f946e101-3e55-4223-8817-ae381a2e7383)
update sources set industry_group = '制造/工业' where id = 'f946e101-3e55-4223-8817-ae381a2e7383' and industry_group is null;
-- 新时达 (90563f7e-dd09-4436-aa4b-9e39bdf47777)
update sources set industry_group = '制造/工业' where id = '90563f7e-dd09-4436-aa4b-9e39bdf47777' and industry_group is null;

-- industry='房产经纪' → '地产/建筑'：先例 房产经纪/居住服务 → 地产/建筑（字面一致）
-- 北京麦田 (ea97c871-62be-4fea-94bd-cd1b705e5741)
update sources set industry_group = '地产/建筑' where id = 'ea97c871-62be-4fea-94bd-cd1b705e5741' and industry_group is null;

-- industry='消费品·零售' → '消费/零售'：先例 消费零售 / 快消零售 → 消费/零售
-- 全棉时代 (f52bf3e0-4112-4a73-bc26-39c8ba5981e0)
update sources set industry_group = '消费/零售' where id = 'f52bf3e0-4112-4a73-bc26-39c8ba5981e0' and industry_group is null;

-- industry='激光控制系统' → '制造/工业'：柏楚电子=激光切割控制系统软硬件；先例 激光 / 激光设备 / 工业软件 → 制造/工业
-- 柏楚电子 (86f742ed-7079-48bf-a663-733bbff95f3b)
update sources set industry_group = '制造/工业' where id = '86f742ed-7079-48bf-a663-733bbff95f3b' and industry_group is null;

-- industry='电力保护与控制' → '能源/化工'：南瑞继保=继电保护/直流输电/电网自动化；先例 输变电设备/电力变压器/HVDC、电力、能源电力 → 能源/化工
-- 南瑞继保 (cf47d7a6-ccd9-4c43-8012-43c232485e9c)
update sources set industry_group = '能源/化工' where id = 'cf47d7a6-ccd9-4c43-8012-43c232485e9c' and industry_group is null;

-- industry='电力电子' → '制造/工业'：盛弘电气主营储能变流器/充电桩/电能质量设备；先例 储能 / 光伏逆变器 / 热管理/车载电源 → 制造/工业
-- 盛弘电气 (37d4c7bd-bec6-444b-8bd5-2aab1c420b01)
update sources set industry_group = '制造/工业' where id = '37d4c7bd-bec6-444b-8bd5-2aab1c420b01' and industry_group is null;
-- 盛弘电气 (6c358a03-9997-43aa-a5da-f6fd1769c329)
update sources set industry_group = '制造/工业' where id = '6c358a03-9997-43aa-a5da-f6fd1769c329' and industry_group is null;

-- industry='电子测量仪器' → '制造/工业'：先例 电子测量 → 制造/工业（字面一致）
-- 艾诺仪器 (a0e8d7ca-09ed-404e-83bd-98fc05ad1dfa)
update sources set industry_group = '制造/工业' where id = 'a0e8d7ca-09ed-404e-83bd-98fc05ad1dfa' and industry_group is null;

-- industry='红外芯片' → '制造/工业'：先例 AI芯片 / 存储芯片 / 视频监控芯片 → 制造/工业
-- 睿创微纳 (90ba343d-828b-4c7d-ba17-a06fced3ed5e)
update sources set industry_group = '制造/工业' where id = '90ba343d-828b-4c7d-ba17-a06fced3ed5e' and industry_group is null;

-- industry='网络通信设备' → '制造/工业'：先例 通信设备 / ICT·通信设备 → 制造/工业（不归互联网/科技——那是通信运营商/互联网·通信的口径）
-- 星网锐捷 (9c7eb983-ed1b-4a70-854d-47035028d074)
update sources set industry_group = '制造/工业' where id = '9c7eb983-ed1b-4a70-854d-47035028d074' and industry_group is null;

-- industry='财富管理' → '金融'：先例 基金·资管 / 金融·资产管理 / 量化投资 → 金融
-- 诺亚控股 (30bdee57-2afe-4ea7-afb0-36916b0201f8)
update sources set industry_group = '金融' where id = '30bdee57-2afe-4ea7-afb0-36916b0201f8' and industry_group is null;
-- 诺亚控股 (52037dad-0bcb-4e95-b5b7-8c3d8710ee2c)
update sources set industry_group = '金融' where id = '52037dad-0bcb-4e95-b5b7-8c3d8710ee2c' and industry_group is null;

-- industry='连锁便利店' → '消费/零售'：先例 零售 / 快消零售 / 酒店连锁 → 消费/零售
-- 美宜佳 (6ff18faf-5634-41da-bc1b-74b2af72b78d)
update sources set industry_group = '消费/零售' where id = '6ff18faf-5634-41da-bc1b-74b2af72b78d' and industry_group is null;
-- 美宜佳 (445aa618-94a3-4f12-9e48-fc35e6867544)
update sources set industry_group = '消费/零售' where id = '445aa618-94a3-4f12-9e48-fc35e6867544' and industry_group is null;

-- industry='酒类·快消' → '消费/零售'：先例 消费·酒类 / 啤酒 / 快消零售 → 消费/零售
-- 劲牌 (0f86cffe-fb9d-412c-bc10-ae9a861ebd79)
update sources set industry_group = '消费/零售' where id = '0f86cffe-fb9d-412c-bc10-ae9a861ebd79' and industry_group is null;

-- industry='锂电池' → '制造/工业'：先例 锂电 / 储能电池 / 动力/储能电池 → 制造/工业（_boundaryNotes：电池归制造）
-- 新能安 (fa517b34-2ed0-46c6-9911-f9efeeb2b588)
update sources set industry_group = '制造/工业' where id = 'fa517b34-2ed0-46c6-9911-f9efeeb2b588' and industry_group is null;
-- 新能安 (4c9292ca-e4c5-42be-b056-96b3f30b1a4c)
update sources set industry_group = '制造/工业' where id = '4c9292ca-e4c5-42be-b056-96b3f30b1a4c' and industry_group is null;
-- 海四达 (12d0c722-9328-42a4-b7a9-ee3c1b42f6b8)
update sources set industry_group = '制造/工业' where id = '12d0c722-9328-42a4-b7a9-ee3c1b42f6b8' and industry_group is null;

-- industry='生物制药·农牧'：刻意不回填（两段分属不同组（生物制药→医疗/医药，农牧饲料/养殖→消费/零售）；天康生物营收以饲料+生猪养殖为主、兽用疫苗为创业主业，无单一主导 → 同 271 对横店集团的处理，留 NULL 待创始人定）
-- 天康生物 (743ccece-65f0-43e7-8b70-cb9440843b39)：保持 NULL
-- 天康生物 (72aca9d1-15e2-4ea4-a754-84815e59a29c)：保持 NULL

-- ============================================================
-- ② 兜底 CASE：v2 JSON 全量 450 条（自动生成，与 lib/industry-taxonomy.json 字节级一致；
--    tests/industry-taxonomy.test.js 断言本段 ⊆ JSON mapping）。映射不到 → 保持 NULL。
-- ============================================================
update sources
set industry_group = case industry
    when '3D打印' then '制造/工业'
    when 'ADC抗体药物偶联/创新药' then '医疗/医药'
    when 'AI' then '互联网/科技'
    when 'AI GPU芯片设计' then '制造/工业'
    when 'AIGC' then '互联网/科技'
    when 'AI·3D' then '互联网/科技'
    when 'AI·3D生成' then '互联网/科技'
    when 'AI·语音' then '互联网/科技'
    when 'AI医疗' then '医疗/医药'
    when 'AI大模型' then '互联网/科技'
    when 'AI应用' then '互联网/科技'
    when 'AI芯片' then '制造/工业'
    when 'AI芯片·具身智能' then '制造/工业'
    when 'AMR移动机器人/调度系统' then '制造/工业'
    when 'BI/数据分析SaaS' then '互联网/科技'
    when 'CXO' then '医疗/医药'
    when 'CXO/ADC偶联药物CDMO' then '医疗/医药'
    when 'CXO/新药研发外包' then '医疗/医药'
    when 'CXO/新药研发服务' then '医疗/医药'
    when 'EDA/良率分析工具' then '制造/工业'
    when 'EDA工具' then '制造/工业'
    when 'EDA软件' then '制造/工业'
    when 'FPGA芯片设计' then '制造/工业'
    when 'HR SaaS' then '互联网/科技'
    when 'ICT·通信设备' then '制造/工业'
    when 'IVD体外诊断' then '医疗/医药'
    when 'LED显示' then '制造/工业'
    when 'MCN' then '传媒/文娱'
    when 'MCN/营销' then '传媒/文娱'
    when 'MCU/模拟混合信号芯片' then '制造/工业'
    when 'RTC/实时音视频云' then '互联网/科技'
    when 'discover' then 'other'
    when '专用车/石油装备' then '汽车/出行'
    when '个护/洗护' then '消费/零售'
    when '中药' then '医疗/医药'
    when '主题公园/景区' then '传媒/文娱'
    when '乳业·消费' then '消费/零售'
    when '乳制品' then '消费/零售'
    when '云计算' then '互联网/科技'
    when '互联网' then '互联网/科技'
    when '互联网/科技' then '互联网/科技'
    when '互联网·云' then '互联网/科技'
    when '互联网·内容' then '互联网/科技'
    when '互联网·内容社区' then '互联网/科技'
    when '互联网·出行' then '汽车/出行'
    when '互联网·媒体' then '传媒/文娱'
    when '互联网·安全' then '互联网/科技'
    when '互联网·智能物联' then '互联网/科技'
    when '互联网·智能终端' then '制造/工业'
    when '互联网·游戏' then '互联网/科技'
    when '互联网·电商' then '互联网/科技'
    when '互联网·社区电商' then '互联网/科技'
    when '互联网·通信' then '互联网/科技'
    when '互联网保险' then '金融'
    when '互联网券商' then '互联网/科技'
    when '互联网医疗' then '医疗/医药'
    when '互联网科技' then '互联网/科技'
    when '互联网金融' then '金融'
    when '五金电工·消费' then '制造/工业'
    when '人工智能' then '互联网/科技'
    when '人工智能/AI应用' then '互联网/科技'
    when '人工智能/机器视觉' then '制造/工业'
    when '人形机器人' then '制造/工业'
    when '企业IT' then '制造/工业'
    when '企业服务' then '互联网/科技'
    when '企业服务/SaaS' then '互联网/科技'
    when '企业软件' then '互联网/科技'
    when '企业软件/ERP实施' then '互联网/科技'
    when '企业软件/IT服务' then '制造/工业'
    when '休闲零食' then '消费/零售'
    when '休闲零食/小鱼仔' then '消费/零售'
    when '传媒/文娱' then '传媒/文娱'
    when '伴随诊断/肿瘤基因检测' then '医疗/医药'
    when '保险' then '金融'
    when '保险科技' then '金融'
    when '信创·服务器' then '互联网/科技'
    when '信息技术' then '互联网/科技'
    when '储能' then '制造/工业'
    when '储能·消费电子' then '制造/工业'
    when '储能电池' then '制造/工业'
    when '光伏' then '制造/工业'
    when '光伏·储能' then '制造/工业'
    when '光伏·农牧' then '制造/工业'
    when '光伏·新能源' then '制造/工业'
    when '光伏微逆变器' then '制造/工业'
    when '光伏组件' then '制造/工业'
    when '光伏逆变器' then '制造/工业'
    when '光刻设备' then '制造/工业'
    when '光学' then '制造/工业'
    when '光通信' then '制造/工业'
    when '公募基金' then '金融'
    when '具身智能' then '制造/工业'
    when '养殖' then '消费/零售'
    when '内容平台' then '互联网/科技'
    when '军工·央企' then '制造/工业'
    when '农业/食品/养殖' then '消费/零售'
    when '农牧饲料/养殖' then '消费/零售'
    when '出海广告/移动营销' then '传媒/文娱'
    when '出行' then '汽车/出行'
    when '创投' then '金融'
    when '创新药' then '医疗/医药'
    when '创新药/肝病肿瘤' then '医疗/医药'
    when '创新药/许可引进' then '医疗/医药'
    when '制造/工业' then '制造/工业'
    when '制造·注塑机' then '制造/工业'
    when '办公用品·B2B' then '消费/零售'
    when '动力/储能电池' then '制造/工业'
    when '动力电池' then '制造/工业'
    when '化工' then '能源/化工'
    when '化工·央企' then '能源/化工'
    when '化工·气体' then '能源/化工'
    when '医检' then '医疗/医药'
    when '医疗' then '医疗/医药'
    when '医疗/医药' then '医疗/医药'
    when '医疗AI' then '医疗/医药'
    when '医疗·健康科技' then '医疗/医药'
    when '医疗健康' then '医疗/医药'
    when '医疗器械' then '医疗/医药'
    when '医疗器械·影像设备' then '医疗/医药'
    when '医疗大数据' then '医疗/医药'
    when '医疗影像' then '医疗/医药'
    when '医疗服务' then '医疗/医药'
    when '医疗设备' then '医疗/医药'
    when '医药' then '医疗/医药'
    when '医药·CRO' then '医疗/医药'
    when '医药·医疗' then '医疗/医药'
    when '医药·生物' then '医疗/医药'
    when '医药健康' then '医疗/医药'
    when '医药制造' then '医疗/医药'
    when '医药制造/麻醉生殖' then '医疗/医药'
    when '医药医疗' then '医疗/医药'
    when '医药商业流通/批发分销' then '医疗/医药'
    when '医药外包' then '医疗/医药'
    when '医药流通/疫苗' then '医疗/医药'
    when '半导体' then '制造/工业'
    when '半导体·射频' then '制造/工业'
    when '半导体材料' then '制造/工业'
    when '半导体设备' then '制造/工业'
    when '协同办公' then '互联网/科技'
    when '口腔' then '医疗/医药'
    when '口腔护理' then '医疗/医药'
    when '商业地产' then '地产/建筑'
    when '商用车' then '汽车/出行'
    when '啤酒' then '消费/零售'
    when '四足机器人/人形机器人' then '制造/工业'
    when '在线旅游' then '互联网/科技'
    when '在线票务' then '传媒/文娱'
    when '在线视频' then '互联网/科技'
    when '地产' then '地产/建筑'
    when '地产/住宅开发' then '地产/建筑'
    when '地产/建筑' then '地产/建筑'
    when '地图出行' then '汽车/出行'
    when '城商行' then '金融'
    when '基因' then '医疗/医药'
    when '基金' then '金融'
    when '基金·资管' then '金融'
    when '大宗商品供应链' then '物流/供应链'
    when '大数据/数据库' then '互联网/科技'
    when '媒体平台' then '传媒/文娱'
    when '存储芯片' then '制造/工业'
    when '存储芯片/DRAM' then '制造/工业'
    when '安全 SaaS' then '互联网/科技'
    when '安防' then '互联网/科技'
    when '安防·AIoT' then '互联网/科技'
    when '定制家居/建材' then '制造/工业'
    when '定制家居/软件' then '消费/零售'
    when '客车' then '汽车/出行'
    when '家居家纺' then '消费/零售'
    when '家居建材零售' then '制造/工业'
    when '家电' then '制造/工业'
    when '导航定位' then '制造/工业'
    when '嵌入式/多媒体芯片设计' then '制造/工业'
    when '工业/燃气分销' then '能源/化工'
    when '工业/雾化科技' then '制造/工业'
    when '工业·暖通' then '制造/工业'
    when '工业·楼宇' then '制造/工业'
    when '工业·电梯' then '制造/工业'
    when '工业·航空' then '制造/工业'
    when '工业互联网/3D视觉/传感器' then '制造/工业'
    when '工业机器人' then '制造/工业'
    when '工业机器人·电梯控制' then '制造/工业'
    when '工业自动化' then '制造/工业'
    when '工业自动化/DCS/PLC' then '制造/工业'
    when '工业自动化/变频器' then '制造/工业'
    when '工业自动化/工业视觉' then '制造/工业'
    when '工业软件' then '制造/工业'
    when '工业软件/CAD/CAE' then '制造/工业'
    when '工业软件/CAPP/PDM/PLM' then '制造/工业'
    when '工业驱动/伺服系统' then '制造/工业'
    when '工程机械' then '制造/工业'
    when '建材' then '制造/工业'
    when '建材/工业材料' then '制造/工业'
    when '建筑/工业涂料' then '地产/建筑'
    when '建筑地产' then '地产/建筑'
    when '建筑工程·央企' then '地产/建筑'
    when '建筑软件' then '地产/建筑'
    when '彩票科技' then '传媒/文娱'
    when '快消零售' then '消费/零售'
    when '房产经纪' then '地产/建筑'
    when '房产经纪/居住服务' then '地产/建筑'
    when '房地产' then '地产/建筑'
    when '房地产开发' then '地产/建筑'
    when '手机/智能终端' then '制造/工业'
    when '摩托车' then '汽车/出行'
    when '支付' then '金融'
    when '教育' then '教育'
    when '教育·AI' then '教育'
    when '教育大数据' then '教育'
    when '教育科技' then '教育'
    when '数字银行/金融科技' then '金融'
    when '数字阅读/网络文学' then '互联网/科技'
    when '文具' then '消费/零售'
    when '文娱' then '传媒/文娱'
    when '新材料' then '制造/工业'
    when '新消费' then '消费/零售'
    when '新能源' then '能源/化工'
    when '新能源·电池' then '制造/工业'
    when '新能源·风电' then '制造/工业'
    when '新能源汽车/制造' then '汽车/出行'
    when '新能源连接器' then '能源/化工'
    when '新茶饮' then '消费/零售'
    when '方便食品' then '消费/零售'
    when '方便食品/饮料' then '消费/零售'
    when '旅游' then '消费/零售'
    when '无人机' then '制造/工业'
    when '无人机·智能硬件' then '制造/工业'
    when '日化' then '消费/零售'
    when '日化/个护' then '消费/零售'
    when '日用品' then '消费/零售'
    when '时尚男装' then '消费/零售'
    when '显示面板' then '制造/工业'
    when '显示面板·半导体' then '制造/工业'
    when '智能制造' then '制造/工业'
    when '智能座舱' then '汽车/出行'
    when '智能影像' then '制造/工业'
    when '智能硬件' then '制造/工业'
    when '智能硬件/可穿戴' then '制造/工业'
    when '智能装备' then '制造/工业'
    when '智能财税' then '互联网/科技'
    when '智能驾驶' then '汽车/出行'
    when '智能驾驶/ADAS' then '汽车/出行'
    when '智能驾驶/自动驾驶' then '汽车/出行'
    when '有色金属' then '能源/化工'
    when '服务机器人/配送机器人' then '制造/工业'
    when '服装' then '消费/零售'
    when '本地生活' then '互联网/科技'
    when '本地生活/互联网' then '互联网/科技'
    when '机器人' then '制造/工业'
    when '机器视觉' then '制造/工业'
    when '材料·央企' then '制造/工业'
    when '核工业·能源' then '能源/化工'
    when '核能' then '能源/化工'
    when '检测设备' then '制造/工业'
    when '氟化工/氯碱' then '能源/化工'
    when '水泥' then '制造/工业'
    when '汽车' then '汽车/出行'
    when '汽车/出行' then '汽车/出行'
    when '汽车·内容' then '汽车/出行'
    when '汽车·制造' then '汽车/出行'
    when '汽车·新能源' then '汽车/出行'
    when '汽车·智能电动' then '汽车/出行'
    when '汽车互联网/电商' then '汽车/出行'
    when '汽车制造' then '汽车/出行'
    when '汽车后市场/数字化' then '汽车/出行'
    when '汽车整车/合资' then '汽车/出行'
    when '汽车整车/新能源汽车' then '汽车/出行'
    when '汽车电子/TPMS' then '汽车/出行'
    when '汽车零部件' then '汽车/出行'
    when '汽车零部件/内饰' then '汽车/出行'
    when '法务/电子合同 SaaS' then '互联网/科技'
    when '涂料/建筑涂料' then '地产/建筑'
    when '消费' then '消费/零售'
    when '消费/零售' then '消费/零售'
    when '消费/零食饮料' then '消费/零售'
    when '消费·服饰' then '消费/零售'
    when '消费·纺织' then '消费/零售'
    when '消费·运动' then '消费/零售'
    when '消费·运动服饰' then '消费/零售'
    when '消费·运动零售' then '消费/零售'
    when '消费·酒类' then '消费/零售'
    when '消费·零食' then '消费/零售'
    when '消费·食品' then '消费/零售'
    when '消费·饮料' then '消费/零售'
    when '消费健康' then '消费/零售'
    when '消费品·零售' then '消费/零售'
    when '消费电子' then '制造/工业'
    when '消费电子/PC' then '制造/工业'
    when '消费电子·手机' then '制造/工业'
    when '消费电子·教育电子' then '制造/工业'
    when '消费电子·显示' then '制造/工业'
    when '消费金融' then '金融'
    when '消费金融/金融科技' then '金融'
    when '消费零售' then '消费/零售'
    when '游戏' then '互联网/科技'
    when '游戏/互联网' then '互联网/科技'
    when '游戏·元宇宙' then '互联网/科技'
    when '游戏发行' then '互联网/科技'
    when '潮玩' then '消费/零售'
    when '潮玩谷子/IP衍生-日系手办/周边' then '消费/零售'
    when '激光' then '制造/工业'
    when '激光控制系统' then '制造/工业'
    when '激光设备' then '制造/工业'
    when '激光雷达' then '汽车/出行'
    when '激光雷达/ToF传感器' then '汽车/出行'
    when '热管理/冷却系统' then '制造/工业'
    when '热管理/车载电源' then '制造/工业'
    when '照明' then '制造/工业'
    when '物业服务' then '地产/建筑'
    when '物业管理/代建' then '地产/建筑'
    when '物流' then '物流/供应链'
    when '物流/供应链' then '物流/供应链'
    when '物流·央企' then '物流/供应链'
    when '物流·航运' then '物流/供应链'
    when '物流末端' then '物流/供应链'
    when '物流机器人' then '物流/供应链'
    when '物流科技' then '物流/供应链'
    when '物联网' then '互联网/科技'
    when '物联网模组' then '互联网/科技'
    when '环境检测/第三方检测' then '制造/工业'
    when '珠三角·注塑机/压铸机' then '制造/工业'
    when '珠宝' then '消费/零售'
    when '生命科学' then '医疗/医药'
    when '生命科学·诊断' then '医疗/医药'
    when '生命科学工具/分子诊断' then '医疗/医药'
    when '生活服务' then '互联网/科技'
    when '生物制品' then '医疗/医药'
    when '生物制药' then '医疗/医药'
    when '生物医药' then '医疗/医药'
    when '生物类似药/单克隆抗体' then '医疗/医药'
    when '电信IT/数字化' then '制造/工业'
    when '电信·央企' then '互联网/科技'
    when '电信设备' then '制造/工业'
    when '电力' then '能源/化工'
    when '电力保护与控制' then '能源/化工'
    when '电力电子' then '制造/工业'
    when '电动车' then '汽车/出行'
    when '电商' then '互联网/科技'
    when '电商/互联网' then '互联网/科技'
    when '电商/生活服务' then '互联网/科技'
    when '电子制造' then '制造/工业'
    when '电子测量' then '制造/工业'
    when '电子测量仪器' then '制造/工业'
    when '电工' then '制造/工业'
    when '电气' then '制造/工业'
    when '电气/液压' then '制造/工业'
    when '电池' then '制造/工业'
    when '男装/休闲服装' then '消费/零售'
    when '直播' then '互联网/科技'
    when '直播·社交' then '互联网/科技'
    when '眼科·医疗' then '医疗/医药'
    when '知名私企' then 'other'
    when '短视频/互联网' then '互联网/科技'
    when '石化/特种材料' then '能源/化工'
    when '矿业' then '能源/化工'
    when '矿业-金矿/铜矿' then '能源/化工'
    when '研发管理 SaaS' then '互联网/科技'
    when '硬件·IT' then '制造/工业'
    when '科技' then '互联网/科技'
    when '科技·军工' then '制造/工业'
    when '粮油' then '消费/零售'
    when '精密制造' then '制造/工业'
    when '红外芯片' then '制造/工业'
    when '线控底盘/转向系统' then '汽车/出行'
    when '综合' then 'other'
    when '综合·地产·国资' then '地产/建筑'
    when '综合·央企' then 'other'
    when '综合·实业·国资' then 'other'
    when '综合证券' then '金融'
    when '网络安全' then '互联网/科技'
    when '网络安全/威胁情报' then '互联网/科技'
    when '网络设备' then '制造/工业'
    when '网络通信设备' then '制造/工业'
    when '美妆' then '消费/零售'
    when '美妆个护' then '消费/零售'
    when '职业培训' then '教育'
    when '肉类食品加工' then '消费/零售'
    when '能源' then '能源/化工'
    when '能源/化工' then '能源/化工'
    when '能源·核电·央企' then '能源/化工'
    when '能源电力' then '能源/化工'
    when '膜材料' then '制造/工业'
    when '自动驾驶' then '汽车/出行'
    when '船舶/海洋工程' then '制造/工业'
    when '芳纶/高性能纤维' then '制造/工业'
    when '茶饮/茶叶零售' then '消费/零售'
    when '营销传播' then '传媒/文娱'
    when '血液/免疫肿瘤创新药' then '医疗/医药'
    when '装备' then '制造/工业'
    when '装备制造' then '制造/工业'
    when '装备重工' then '制造/工业'
    when '视频监控芯片' then '制造/工业'
    when '视频社区/互联网' then '互联网/科技'
    when '证券' then '金融'
    when '财富管理' then '金融'
    when '财税/能源管理 SaaS' then '互联网/科技'
    when '财税SaaS' then '互联网/科技'
    when '跨境电商' then '互联网/科技'
    when '跨境电商物流' then '物流/供应链'
    when '轨道交通' then '制造/工业'
    when '轨道交通装备/信号' then '制造/工业'
    when '轮胎/橡胶' then '制造/工业'
    when '软件' then '互联网/科技'
    when '软件·云' then '互联网/科技'
    when '输变电设备/电力变压器/HVDC' then '能源/化工'
    when '运动健身-家用健身器械' then '消费/零售'
    when '运动健身-精品健身工作室' then '消费/零售'
    when '运动控制/工业机器人' then '制造/工业'
    when '运动控制/工业自动化' then '制造/工业'
    when '运动服饰' then '消费/零售'
    when '连锁便利店' then '消费/零售'
    when '连锁药店/零售药店' then '医疗/医药'
    when '通信' then '互联网/科技'
    when '通信·央企子公司' then '互联网/科技'
    when '通信·科技' then '互联网/科技'
    when '通信设备' then '制造/工业'
    when '通信设备/云计算' then '制造/工业'
    when '通信运营商' then '互联网/科技'
    when '酒店连锁' then '消费/零售'
    when '酒类·快消' then '消费/零售'
    when '量化投资' then '金融'
    when '金融' then '金融'
    when '金融·保险' then '金融'
    when '金融·保险经纪' then '金融'
    when '金融·支付' then '金融'
    when '金融·资产管理' then '金融'
    when '金融·资管' then '金融'
    when '金融科技' then '金融'
    when '金融科技/互联网' then '金融'
    when '金融科技·券商' then '金融'
    when '钢铁' then '能源/化工'
    when '银行' then '金融'
    when '银行金融' then '金融'
    when '锂电' then '制造/工业'
    when '锂电正极材料' then '制造/工业'
    when '锂电池' then '制造/工业'
    when '锂电装备' then '制造/工业'
    when '锂电负极材料' then '制造/工业'
    when '长视频/影视' then '传媒/文娱'
    when '零售' then '消费/零售'
    when '零售科技' then '消费/零售'
    when '音乐娱乐/互联网' then '传媒/文娱'
    when '音频平台' then '互联网/科技'
    when '预制菜/速冻食品' then '消费/零售'
    when '食品' then '消费/零售'
    when '食品·乳业' then '消费/零售'
    when '食品·饮料' then '消费/零售'
    when '食品饮料' then '消费/零售'
    when '餐饮' then '消费/零售'
    when '餐饮连锁/快餐' then '消费/零售'
    when '高端女装' then '消费/零售'
    else null
  end
where industry is not null and industry_group is null;

-- ============================================================
-- ③ ownership：265 第 6 步的同一条机械规则，只补 NULL 行
-- ============================================================
update sources
set ownership = case
    when segment in ('soe', 'private', 'foreign') then segment
    else 'unknown'
  end
where ownership is null;

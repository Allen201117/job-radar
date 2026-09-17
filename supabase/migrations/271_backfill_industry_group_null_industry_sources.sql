-- 271_backfill_industry_group_null_industry_sources.sql
--
-- 背景：迁移 265 只回填了 sources.industry「有值」的行（433 种自由写法 → industry_group）。
-- industry 本身就是 NULL 的行（从未打过行业标签）在 265 里被刻意跳过、保持 NULL——这批行
-- 里有校招大户：live 全量核实（2026-09-18，见下方"影响面"）enabled=true 且 industry is null
-- 的源共 142 条，其中包含字节跳动/腾讯/百度/小米/蔚来/小鹏汽车/中国人寿等，合计撑着
-- 20,948 个"校招+实习"在招岗（远超立项时估计的 6,139——那是更早、更粗的普查快照，以本次
-- 全量分页 live 结果为准）。这批源没有 industry_group，会让"按行业看校招覆盖"这个新功能
-- 在最重要的一批公司上直接读到空。
--
-- 方法：逐条按 id（不按公司名，避免"京东 vs 京东方"式误伤）人工判定 industry_group，
-- 依据优先级：① lib/must-apply-list.json 已归好行业的公司（清单名是库里 company 名的子串，
-- 与 crawler/must_apply.resolve_owner 同一方向规则）；② 公司名/主营业务含明确行业词；
-- ③ 确知常识（含本次 live 搜索核验的条目，注释里标注"live 搜索核验"）。拿不准的一律不写、
-- 保持 NULL——本迁移只有 1 家如此（横店集团：磁性材料/医药/电机/照明/影视/期货六大产融
-- 平台并列，无单一行业占绝对主导，见下方对应 UPDATE 语句上方注释）。
--
-- ⚠️ 范围边界：live 复核时发现另有 45 条 enabled 源是 industry 有值、但 industry_group
-- 仍为 NULL——这些行全部是迁移 265 跑完之后（2026-09-17 18:06 UTC 之后）由后续 seed 迁移
-- （268~270 一带）新插入的，带着尚未收录进 lib/industry-taxonomy.json 的新 industry 自由写法
-- （如"财富管理""红外芯片""网络通信设备""客车"等），265 的一次性 CASE 语句自然覆盖不到。
-- 这是一个会随每次新 seed 迁移持续复发的分类账缺口，与本迁移"清 142 条 industry 全空的行"
-- 是两类不同成因、处置不同（这批需要先扩 lib/industry-taxonomy.json 的映射表，不是本迁移
-- 该做的人工判断），不在本次范围内，已用 spawn_task 报给创始人另开任务处理，此处仅存档
-- 事实：不动这 45 条。
--
-- ownership 说明：本迁移不改 ownership 列。142 条目标行的 ownership 已由迁移 265 第 6 步
-- （segment 有值照抄、否则记 unknown）全量回填完毕；live 核实这 142 条里没有任何一条是
-- "ownership=unknown 且公司名含中国/国家/集团(央企)/省等央国企暗示词"的组合（NULL 桶里
-- 唯二的境内"集团"名是横店集团/爱慕集团，前者本迁移不落 industry_group、后者 ownership
-- 已是 private），故无需新增 soe 升级，无遗漏。

set local statement_timeout = '1800s';

-- 3M (3843f0d8-1cfa-478f-b166-7bfcbd12e7fb): must_apply 清单'3M'子串命中，多元化工业制造集团
update sources set industry_group = '制造/工业' where id = '3843f0d8-1cfa-478f-b166-7bfcbd12e7fb' and industry_group is null;
-- Adyen (c86d4fce-26d5-45b0-965f-1bdda89b02f4): 荷兰上市全球支付处理平台，taxonomy 口径"支付/金融科技"→金融
update sources set industry_group = '金融' where id = 'c86d4fce-26d5-45b0-965f-1bdda89b02f4' and industry_group is null;
-- Affirm (79d97f0e-4daf-4073-a0d7-d3798c671b05): 美国 BNPL(先买后付)消费信贷金融科技公司
update sources set industry_group = '金融' where id = '79d97f0e-4daf-4073-a0d7-d3798c671b05' and industry_group is null;
-- Agoda (468f4655-a17c-4f25-9b1b-85c6c8a99bd7): 在线旅游预订平台(Booking Holdings 旗下)，taxonomy 口径"在线旅游"→互联网/科技
update sources set industry_group = '互联网/科技' where id = '468f4655-a17c-4f25-9b1b-85c6c8a99bd7' and industry_group is null;
-- Airtable (dc6ff93f-e886-40c1-ac98-aef674bbf391): 无代码数据库/协同 SaaS
update sources set industry_group = '互联网/科技' where id = 'dc6ff93f-e886-40c1-ac98-aef674bbf391' and industry_group is null;
-- Akuna Capital (7c882b16-9842-4232-8456-a023556d6c11): 期权做市/量化交易公司
update sources set industry_group = '金融' where id = '7c882b16-9842-4232-8456-a023556d6c11' and industry_group is null;
-- Anduril (b3e80f45-e6fb-46ce-8684-6f9923436aad): 国防自主系统硬件制造商(无人机/哨兵塔/自主水下航行器)，taxonomy 口径"军工"→制造/工业
update sources set industry_group = '制造/工业' where id = 'b3e80f45-e6fb-46ce-8684-6f9923436aad' and industry_group is null;
-- Animoca Brands (49e2c707-ec29-4ae8-9efc-1a1422a626b3): Web3游戏/数字娱乐投资与开发公司，taxonomy 口径"游戏"→互联网/科技
update sources set industry_group = '互联网/科技' where id = '49e2c707-ec29-4ae8-9efc-1a1422a626b3' and industry_group is null;
-- Anthropic (8b6268fd-a5a5-478d-869c-d2b151b1cafd): AI 基础模型研发公司(Claude)
update sources set industry_group = '互联网/科技' where id = '8b6268fd-a5a5-478d-869c-d2b151b1cafd' and industry_group is null;
-- Apple (0060a6b8-077d-40a3-b02e-ac129984242c): 消费电子硬件为主营收(iPhone/Mac/iPad约75%营收)，taxonomy 口径"手机/智能终端""消费电子"→制造/工业
update sources set industry_group = '制造/工业' where id = '0060a6b8-077d-40a3-b02e-ac129984242c' and industry_group is null;
-- Asana (721967d7-cd6b-4e8b-b2cf-6a40c09fbf97): 项目协同管理 SaaS
update sources set industry_group = '互联网/科技' where id = '721967d7-cd6b-4e8b-b2cf-6a40c09fbf97' and industry_group is null;
-- Autodesk 欧特克 (44318297-9c83-4104-ac20-296891b73719): 工业设计/CAD/CAE 软件公司(AutoCAD/Revit)，taxonomy 口径"工业软件/CAD/CAE"→制造/工业(遵循项目既有口径，非笼统归互联网/科技)
update sources set industry_group = '制造/工业' where id = '44318297-9c83-4104-ac20-296891b73719' and industry_group is null;
-- Baseten (369b6935-d1b8-4f1d-af58-0941a0884a9d): AI 模型推理托管平台
update sources set industry_group = '互联网/科技' where id = '369b6935-d1b8-4f1d-af58-0941a0884a9d' and industry_group is null;
-- Bosch 博世 (7e44068f-437e-4ceb-9d70-a99563a98820): must_apply 清单'博世'子串命中（清单口径按汽车零部件龙头收录）
update sources set industry_group = '汽车/出行' where id = '7e44068f-437e-4ceb-9d70-a99563a98820' and industry_group is null;
-- Brex (11e92e58-51ca-47ae-b37f-469a6825a362): 企业信用卡/费用管理金融科技公司
update sources set industry_group = '金融' where id = '11e92e58-51ca-47ae-b37f-469a6825a362' and industry_group is null;
-- Checkr (13513b31-635d-4eef-ab9c-aea64be7e8b7): 背景调查/HR 科技 SaaS，taxonomy 口径"HR SaaS"→互联网/科技
update sources set industry_group = '互联网/科技' where id = '13513b31-635d-4eef-ab9c-aea64be7e8b7' and industry_group is null;
-- Chime (2e3b0b93-c2b2-4dfc-b4be-4afa1d0f618f): 美国互联网银行(neobank)
update sources set industry_group = '金融' where id = '2e3b0b93-c2b2-4dfc-b4be-4afa1d0f618f' and industry_group is null;
-- Citi 花旗 (25e0826d-af47-4abd-bcad-e815ff76b63b): 花旗集团，全球性银行
update sources set industry_group = '金融' where id = '25e0826d-af47-4abd-bcad-e815ff76b63b' and industry_group is null;
-- Cloudflare (d61a9ddf-052f-41d2-a724-08886a6a953d): 全球 CDN/云安全基础设施公司
update sources set industry_group = '互联网/科技' where id = 'd61a9ddf-052f-41d2-a724-08886a6a953d' and industry_group is null;
-- Cockroach Labs (c9dd089a-2ad4-4b03-8413-980f4294ebc4): 分布式数据库软件公司
update sources set industry_group = '互联网/科技' where id = 'c9dd089a-2ad4-4b03-8413-980f4294ebc4' and industry_group is null;
-- Cohere (8c50b05e-4dc3-49c4-b8c8-66dcf3859afa): 企业级大模型/AI 公司
update sources set industry_group = '互联网/科技' where id = '8c50b05e-4dc3-49c4-b8c8-66dcf3859afa' and industry_group is null;
-- Coinbase (be0a6233-cb7c-4626-bca7-1e70a832f36b): 美国上市加密货币交易所
update sources set industry_group = '金融' where id = 'be0a6233-cb7c-4626-bca7-1e70a832f36b' and industry_group is null;
-- Databricks (bb15cb99-6133-49a0-aef0-0e39717ff27c): 数据+AI 平台公司
update sources set industry_group = '互联网/科技' where id = 'bb15cb99-6133-49a0-aef0-0e39717ff27c' and industry_group is null;
-- Datadog (5ee494df-4bb5-4eab-8d94-9541fdf0266e): 可观测性/监控 SaaS
update sources set industry_group = '互联网/科技' where id = '5ee494df-4bb5-4eab-8d94-9541fdf0266e' and industry_group is null;
-- Decagon (f790b816-d4f8-4dbc-b44a-941233533d61): AI 客服 Agent 初创公司
update sources set industry_group = '互联网/科技' where id = 'f790b816-d4f8-4dbc-b44a-941233533d61' and industry_group is null;
-- Discord (23267f3e-e011-4366-afd2-0518155d4ddc): 社交/社区聊天平台，taxonomy 口径"直播·社交/游戏·元宇宙"类均→互联网/科技
update sources set industry_group = '互联网/科技' where id = '23267f3e-e011-4366-afd2-0518155d4ddc' and industry_group is null;
-- Dropbox (81a2f9b0-54bc-49a8-a104-61b4a64ec94d): 云存储 SaaS
update sources set industry_group = '互联网/科技' where id = '81a2f9b0-54bc-49a8-a104-61b4a64ec94d' and industry_group is null;
-- DRW (0ff4a71f-0892-4ec8-9d1e-6b1808c83e13): 芝加哥自营量化交易公司
update sources set industry_group = '金融' where id = '0ff4a71f-0892-4ec8-9d1e-6b1808c83e13' and industry_group is null;
-- ElevenLabs (29657165-84ef-4a2f-a814-7407c25420a5): AI 语音生成公司
update sources set industry_group = '互联网/科技' where id = '29657165-84ef-4a2f-a814-7407c25420a5' and industry_group is null;
-- Faire (7674b0e5-eda7-4fd1-b98b-deefd62be50d): B2B 批发电商平台，taxonomy 口径"电商"→互联网/科技
update sources set industry_group = '互联网/科技' where id = '7674b0e5-eda7-4fd1-b98b-deefd62be50d' and industry_group is null;
-- Figma (b5a9e0f0-a953-4e73-aa27-f0d85098387c): 设计协作软件 SaaS
update sources set industry_group = '互联网/科技' where id = 'b5a9e0f0-a953-4e73-aa27-f0d85098387c' and industry_group is null;
-- Fireworks AI (5ba843de-e020-4f34-a244-26d2b321f1ef): AI 模型推理平台
update sources set industry_group = '互联网/科技' where id = '5ba843de-e020-4f34-a244-26d2b321f1ef' and industry_group is null;
-- Flow Traders (62864abd-f0ed-43c1-b2c3-7efa48db32fc): ETF 做市商
update sources set industry_group = '金融' where id = '62864abd-f0ed-43c1-b2c3-7efa48db32fc' and industry_group is null;
-- Gemini (2175ad11-92c2-4ca8-b2b5-a63bdc3bd193): Winklevoss 兄弟创立的加密货币交易所(与 Google Gemini 大模型同名但非同一公司；greenhouse ATS 与该交易所公开招聘渠道一致)
update sources set industry_group = '金融' where id = '2175ad11-92c2-4ca8-b2b5-a63bdc3bd193' and industry_group is null;
-- GitLab (dd46675d-c9b6-421e-895e-481a0314eedd): DevOps 软件公司
update sources set industry_group = '互联网/科技' where id = 'dd46675d-c9b6-421e-895e-481a0314eedd' and industry_group is null;
-- Grafana Labs (1dc068dc-7716-40cf-b3c7-dd19b692c91c): 可观测性/监控开源+SaaS 公司
update sources set industry_group = '互联网/科技' where id = '1dc068dc-7716-40cf-b3c7-dd19b692c91c' and industry_group is null;
-- Gusto (4eb95b76-9677-4884-9464-fd45646b97a7): 薪酬/HR SaaS，taxonomy 口径"HR SaaS"→互联网/科技
update sources set industry_group = '互联网/科技' where id = '4eb95b76-9677-4884-9464-fd45646b97a7' and industry_group is null;
-- Harvey (b2017d5c-828b-46a0-ba73-2f3b4eacbdbc): 法律 AI 初创公司，taxonomy 口径"法务/电子合同 SaaS"→互联网/科技
update sources set industry_group = '互联网/科技' where id = 'b2017d5c-828b-46a0-ba73-2f3b4eacbdbc' and industry_group is null;
-- IMC Trading (40205c19-428a-411e-8876-4b3d7740268f): 做市/量化交易公司
update sources set industry_group = '金融' where id = '40205c19-428a-411e-8876-4b3d7740268f' and industry_group is null;
-- Instacart (a173ea75-4a94-49b1-813b-34ff775d4068): 生鲜即时配送电商平台，taxonomy 口径"电商/生活服务"→互联网/科技
update sources set industry_group = '互联网/科技' where id = 'a173ea75-4a94-49b1-813b-34ff775d4068' and industry_group is null;
-- Jane Street (460e229f-96d3-42ac-bb18-694cba212306): 量化自营交易/做市公司
update sources set industry_group = '金融' where id = '460e229f-96d3-42ac-bb18-694cba212306' and industry_group is null;
-- Jump Trading (8859a6c8-beb5-4b29-a70f-f4705241fac0): 量化自营交易公司
update sources set industry_group = '金融' where id = '8859a6c8-beb5-4b29-a70f-f4705241fac0' and industry_group is null;
-- LangChain (28cb5bd4-8ca6-42df-9863-c15f2acccce5): AI/大模型应用开发框架公司
update sources set industry_group = '互联网/科技' where id = '28cb5bd4-8ca6-42df-9863-c15f2acccce5' and industry_group is null;
-- Linear (cd62f805-73df-462f-bd78-0108f98b79e0): 研发项目管理/协作软件 SaaS
update sources set industry_group = '互联网/科技' where id = 'cd62f805-73df-462f-bd78-0108f98b79e0' and industry_group is null;
-- Lyft (16365f31-1d30-4fe7-aa74-84a141c7f601): 网约车平台，taxonomy 口径"出行"→汽车/出行
update sources set industry_group = '汽车/出行' where id = '16365f31-1d30-4fe7-aa74-84a141c7f601' and industry_group is null;
-- Marqeta (68cc7bfc-813e-4373-8778-e9293dc9a00b): 发卡/卡组织基础设施金融科技公司
update sources set industry_group = '金融' where id = '68cc7bfc-813e-4373-8778-e9293dc9a00b' and industry_group is null;
-- Mastercard 万事达 (c3b016c7-8766-49a6-adf4-d0d6ecfb8b5f): 全球银行卡清算网络
update sources set industry_group = '金融' where id = 'c3b016c7-8766-49a6-adf4-d0d6ecfb8b5f' and industry_group is null;
-- Mercor (839a29ec-ce28-446e-87e5-a5544b9f5c6c): AI 招聘/用工匹配平台
update sources set industry_group = '互联网/科技' where id = '839a29ec-ce28-446e-87e5-a5544b9f5c6c' and industry_group is null;
-- Mercury (e6217204-bc40-4aff-96b4-dd3af27dd6bf): 面向初创企业的互联网银行(neobank)
update sources set industry_group = '金融' where id = 'e6217204-bc40-4aff-96b4-dd3af27dd6bf' and industry_group is null;
-- Momenta (081f4308-cab8-42bc-b589-71dbd4026be3): 自动驾驶技术公司
update sources set industry_group = '汽车/出行' where id = '081f4308-cab8-42bc-b589-71dbd4026be3' and industry_group is null;
-- MongoDB (29ca0684-f128-4540-9390-93cd21a9f17c): 数据库软件公司
update sources set industry_group = '互联网/科技' where id = '29ca0684-f128-4540-9390-93cd21a9f17c' and industry_group is null;
-- Mozilla (846a5e03-2514-4c63-a469-8fe5d4398b36): 开源浏览器/软件基金会(Firefox)
update sources set industry_group = '互联网/科技' where id = '846a5e03-2514-4c63-a469-8fe5d4398b36' and industry_group is null;
-- MSD 默沙东 (4f5554b6-2300-4936-b506-a60780fbe244): must_apply 清单'默沙东'子串命中
update sources set industry_group = '医疗/医药' where id = '4f5554b6-2300-4936-b506-a60780fbe244' and industry_group is null;
-- Nubank (f6e50731-ed59-4ae4-8cf1-d46c8ed3eaa5): 巴西最大互联网银行(neobank)
update sources set industry_group = '金融' where id = 'f6e50731-ed59-4ae4-8cf1-d46c8ed3eaa5' and industry_group is null;
-- NVIDIA (54a24eea-582b-42d0-bd02-64ad55a36a50): GPU/AI 芯片设计公司，taxonomy 口径"AI芯片/半导体"→制造/工业
update sources set industry_group = '制造/工业' where id = '54a24eea-582b-42d0-bd02-64ad55a36a50' and industry_group is null;
-- OKX 欧易 (7867b378-b311-449f-b9a5-0ed01d8ac1d0): 加密货币交易所
update sources set industry_group = '金融' where id = '7867b378-b311-449f-b9a5-0ed01d8ac1d0' and industry_group is null;
-- On 昂跑 (31b936cb-dd4d-4fe3-9eb1-a62f99435691): 瑞士运动鞋服品牌，taxonomy 口径"运动服饰"→消费/零售
update sources set industry_group = '消费/零售' where id = '31b936cb-dd4d-4fe3-9eb1-a62f99435691' and industry_group is null;
-- Peloton (1fcf7be4-d308-40bc-aef9-f51bf00ce93c): 家用健身器械+订阅内容公司，taxonomy 口径"运动健身-家用健身器械"→消费/零售
update sources set industry_group = '消费/零售' where id = '1fcf7be4-d308-40bc-aef9-f51bf00ce93c' and industry_group is null;
-- Perplexity (a96476a1-0cde-4349-9402-6a2108a02bc4): AI 搜索引擎公司
update sources set industry_group = '互联网/科技' where id = 'a96476a1-0cde-4349-9402-6a2108a02bc4' and industry_group is null;
-- Pfizer 辉瑞 (ef31fad1-23a5-44d9-af60-6a1607e86a43): must_apply 清单'辉瑞'子串命中
update sources set industry_group = '医疗/医药' where id = 'ef31fad1-23a5-44d9-af60-6a1607e86a43' and industry_group is null;
-- Pinterest (71cf6f35-f3cc-4b39-98ba-fc7df978fa0a): 图片社交/内容发现平台，taxonomy 口径"内容平台"→互联网/科技
update sources set industry_group = '互联网/科技' where id = '71cf6f35-f3cc-4b39-98ba-fc7df978fa0a' and industry_group is null;
-- Point72 (41ad7e05-608a-4694-b0df-50a98e5d57ef): 对冲基金
update sources set industry_group = '金融' where id = '41ad7e05-608a-4694-b0df-50a98e5d57ef' and industry_group is null;
-- Postman (e4e09f6f-2342-4919-be0c-480849310100): API 开发者工具 SaaS
update sources set industry_group = '互联网/科技' where id = 'e4e09f6f-2342-4919-be0c-480849310100' and industry_group is null;
-- Reddit (16418247-0ec0-44ec-8a19-a1eb09ac8fb1): 社交内容社区平台
update sources set industry_group = '互联网/科技' where id = '16418247-0ec0-44ec-8a19-a1eb09ac8fb1' and industry_group is null;
-- Replit (d7460db3-c5f1-4655-8a4e-da8dfe9056a6): 云端编程/AI 编程平台
update sources set industry_group = '互联网/科技' where id = 'd7460db3-c5f1-4655-8a4e-da8dfe9056a6' and industry_group is null;
-- Robinhood (67dbb55b-ae86-4c9c-9fd7-3886a9c15ef5): 美国上市证券交易 App
update sources set industry_group = '金融' where id = '67dbb55b-ae86-4c9c-9fd7-3886a9c15ef5' and industry_group is null;
-- Roblox (3be0ee0d-bf89-42f6-aa7e-00c31ffdb9e4): 游戏创作发行平台，taxonomy 口径"游戏"→互联网/科技
update sources set industry_group = '互联网/科技' where id = '3be0ee0d-bf89-42f6-aa7e-00c31ffdb9e4' and industry_group is null;
-- Samsara (c65ebec8-4268-4205-9037-4588a3eb4de9): 车队/物联网设备云管理 SaaS(纽交所代码 IOT)，taxonomy 口径"物联网"→互联网/科技
update sources set industry_group = '互联网/科技' where id = 'c65ebec8-4268-4205-9037-4588a3eb4de9' and industry_group is null;
-- Scale AI (23f39e42-86da-4c40-b6a3-e3d8bbdb80ae): AI 数据标注/基础设施公司
update sources set industry_group = '互联网/科技' where id = '23f39e42-86da-4c40-b6a3-e3d8bbdb80ae' and industry_group is null;
-- Siemens (6e0ee91f-bbcb-4230-a348-186358713bbd): 工业自动化/电气化跨国集团
update sources set industry_group = '制造/工业' where id = '6e0ee91f-bbcb-4230-a348-186358713bbd' and industry_group is null;
-- Sierra (cf44dd50-b033-4263-a0c7-bce90c689411): AI 客服 Agent 初创公司(Bret Taylor 创立)
update sources set industry_group = '互联网/科技' where id = 'cf44dd50-b033-4263-a0c7-bce90c689411' and industry_group is null;
-- Squarepoint (21ecc856-f2a7-45a5-ab56-e753f9ecaaa2): 量化对冲基金
update sources set industry_group = '金融' where id = '21ecc856-f2a7-45a5-ab56-e753f9ecaaa2' and industry_group is null;
-- Squarespace (3c245ac7-3ae0-4c11-93f0-dd69c41517d6): 建站/电商 SaaS
update sources set industry_group = '互联网/科技' where id = '3c245ac7-3ae0-4c11-93f0-dd69c41517d6' and industry_group is null;
-- Stripe (3cda46aa-acab-4c20-9bdd-a063e555c0c9): 全球支付基础设施公司，taxonomy 口径"支付"→金融
update sources set industry_group = '金融' where id = '3cda46aa-acab-4c20-9bdd-a063e555c0c9' and industry_group is null;
-- Supabase (26e0174e-04d7-4a57-870a-f4e603b237ef): 开源后端即服务(BaaS)平台
update sources set industry_group = '互联网/科技' where id = '26e0174e-04d7-4a57-870a-f4e603b237ef' and industry_group is null;
-- Sweetgreen (3d430ffa-2875-45d7-b6a2-1b99422ad567): 美国连锁快餐(沙拉)品牌，taxonomy 口径"餐饮连锁/快餐"→消费/零售
update sources set industry_group = '消费/零售' where id = '3d430ffa-2875-45d7-b6a2-1b99422ad567' and industry_group is null;
-- Temporal (3e06f080-947e-4032-a69b-cf39f9894df4): 工作流编排软件公司
update sources set industry_group = '互联网/科技' where id = '3e06f080-947e-4032-a69b-cf39f9894df4' and industry_group is null;
-- Twilio (f8a556d5-c4d3-4a81-bd21-e3ac0f6380d0): 通信 API 云平台
update sources set industry_group = '互联网/科技' where id = 'f8a556d5-c4d3-4a81-bd21-e3ac0f6380d0' and industry_group is null;
-- Udemy (61c062b9-5d9c-437c-9908-df49d5f3085c): 在线课程学习平台，taxonomy 口径"教育科技"→教育
update sources set industry_group = '教育' where id = '61c062b9-5d9c-437c-9908-df49d5f3085c' and industry_group is null;
-- Vanta (88df678a-b390-4726-b9ea-d7ca1ca85fbd): 安全合规 SaaS，taxonomy 口径"安全 SaaS"→互联网/科技
update sources set industry_group = '互联网/科技' where id = '88df678a-b390-4726-b9ea-d7ca1ca85fbd' and industry_group is null;
-- VAST (ffa681aa-27b5-4567-9d7d-1e5426d175b4): live 搜索核验，3D 大模型/世界模型 AI 公司(核心团队源于清华)，taxonomy 口径"AI·3D生成"→互联网/科技
update sources set industry_group = '互联网/科技' where id = 'ffa681aa-27b5-4567-9d7d-1e5426d175b4' and industry_group is null;
-- Vercel (93289888-fcfc-417e-b203-5973cc113419): 前端云部署平台
update sources set industry_group = '互联网/科技' where id = '93289888-fcfc-417e-b203-5973cc113419' and industry_group is null;
-- Verkada (56255898-6b13-4c80-bd08-68493ebbf206): 云端安防摄像头+软件公司，taxonomy 口径"安防·AIoT"→互联网/科技
update sources set industry_group = '互联网/科技' where id = '56255898-6b13-4c80-bd08-68493ebbf206' and industry_group is null;
-- Webflow (a66e7278-caba-4def-b99a-acda40451571): 无代码建站 SaaS
update sources set industry_group = '互联网/科技' where id = 'a66e7278-caba-4def-b99a-acda40451571' and industry_group is null;
-- WorldQuant (a70b7575-a69b-4f42-99b1-e8219cb74c6b): 量化对冲基金
update sources set industry_group = '金融' where id = 'a70b7575-a69b-4f42-99b1-e8219cb74c6b' and industry_group is null;
-- XREAL (87b113c7-0ec2-4614-ae6a-c3263697878b): AR 眼镜智能硬件制造商，taxonomy 口径"智能硬件"→制造/工业
update sources set industry_group = '制造/工业' where id = '87b113c7-0ec2-4614-ae6a-c3263697878b' and industry_group is null;
-- Zscaler (77fba3eb-de8b-4969-b863-e54eb5b2bdf3): 云安全公司，taxonomy 口径"网络安全"→互联网/科技
update sources set industry_group = '互联网/科技' where id = '77fba3eb-de8b-4969-b863-e54eb5b2bdf3' and industry_group is null;
-- 三一集团 (05fcfebd-e99a-46d1-98b8-3612f50c046b): must_apply 清单'三一重工'(pattern='三一')子串命中
update sources set industry_group = '制造/工业' where id = '05fcfebd-e99a-46d1-98b8-3612f50c046b' and industry_group is null;
-- 中国人寿 (ab6efe84-810c-474f-88e3-47f343b41757): must_apply 清单'中国人寿'子串命中
update sources set industry_group = '金融' where id = 'ab6efe84-810c-474f-88e3-47f343b41757' and industry_group is null;
-- 中科创达 (85d5627b-4a8a-4657-b6ce-dda5d8950b42): 智能终端操作系统/嵌入式软件技术公司(300474.SZ，A股"计算机应用"分类)
update sources set industry_group = '互联网/科技' where id = '85d5627b-4a8a-4657-b6ce-dda5d8950b42' and industry_group is null;
-- 亚信安全 (cc3d1af3-9ed3-479e-9939-7854f4d88b3e): live 搜索核验，网络安全软件公司(688225.SH科创板，中国网络安全软件市占率第一)
update sources set industry_group = '互联网/科技' where id = 'cc3d1af3-9ed3-479e-9939-7854f4d88b3e' and industry_group is null;
-- 京东 (df99f051-c80f-4e5c-a332-4a0fe32a1473): must_apply 清单'京东'子串命中（京东方/京东科技/京东物流因清单名更长非子串,不会误命中）
update sources set industry_group = '互联网/科技' where id = 'df99f051-c80f-4e5c-a332-4a0fe32a1473' and industry_group is null;
-- 北京蓝色光标数据科技 (e90aa307-b2d7-4df6-8252-887004534619): must_apply 清单'蓝色光标'子串命中
update sources set industry_group = '传媒/文娱' where id = 'e90aa307-b2d7-4df6-8252-887004534619' and industry_group is null;
-- 卡特彼勒 Caterpillar (694b1427-cf27-4ac2-adb3-4d54a8bca778): must_apply 清单'卡特彼勒'子串命中
update sources set industry_group = '制造/工业' where id = '694b1427-cf27-4ac2-adb3-4d54a8bca778' and industry_group is null;
-- 可口可乐 Coca-Cola (40141218-c8fe-49ef-9ff6-4786d4c6760c): must_apply 清单'可口可乐'子串命中
update sources set industry_group = '消费/零售' where id = '40141218-c8fe-49ef-9ff6-4786d4c6760c' and industry_group is null;
-- 后摩智能 Houmo (1f30a02c-56a5-48b4-98e2-40af1f3ce22f): 存算一体 AI 芯片设计公司，taxonomy 口径"AI芯片"→制造/工业
update sources set industry_group = '制造/工业' where id = '1f30a02c-56a5-48b4-98e2-40af1f3ce22f' and industry_group is null;
-- 多邻国 Duolingo (bcae4a9f-3ed5-4d54-b1a0-b162128fe70f): must_apply 清单'多邻国'子串命中
update sources set industry_group = '教育' where id = 'bcae4a9f-3ed5-4d54-b1a0-b162128fe70f' and industry_group is null;
-- 字节跳动 (1a5414e3-8b2b-41c2-8f1c-2a3afa74a6e4): must_apply 清单'字节跳动'(pattern='字节')子串命中
update sources set industry_group = '互联网/科技' where id = '1a5414e3-8b2b-41c2-8f1c-2a3afa74a6e4' and industry_group is null;
-- 字节跳动 校招 (8d132688-6c1f-46c5-b7df-99a8a49d82fd): must_apply 清单'字节跳动'(pattern='字节')子串命中
update sources set industry_group = '互联网/科技' where id = '8d132688-6c1f-46c5-b7df-99a8a49d82fd' and industry_group is null;
-- 宏利金融 Manulife (156943ac-5e9d-4147-9cc5-e68cad371f94): 加拿大保险/资管集团
update sources set industry_group = '金融' where id = '156943ac-5e9d-4147-9cc5-e68cad371f94' and industry_group is null;
-- 小米 (32132114-068a-4e91-a9ef-07b41e0a35b6): must_apply 清单'小米'子串命中
update sources set industry_group = '互联网/科技' where id = '32132114-068a-4e91-a9ef-07b41e0a35b6' and industry_group is null;
-- 小鹏汽车 (641d0f72-a099-461c-884e-ba2a371eaa86): must_apply 清单'小鹏汽车'(pattern='小鹏')子串命中
update sources set industry_group = '汽车/出行' where id = '641d0f72-a099-461c-884e-ba2a371eaa86' and industry_group is null;
-- 小鹏汽车 校招 (88a32866-f2e5-42b0-9413-fe9d1edccbcb): must_apply 清单'小鹏汽车'(pattern='小鹏')子串命中
update sources set industry_group = '汽车/出行' where id = '88a32866-f2e5-42b0-9413-fe9d1edccbcb' and industry_group is null;
-- 币安 Binance (61f62365-9974-4898-a135-b4d9ecc69a81): 全球最大加密货币交易所
update sources set industry_group = '金融' where id = '61f62365-9974-4898-a135-b4d9ecc69a81' and industry_group is null;
-- 库洛游戏 Kuro (6e84a784-f0f3-4358-a0af-a2fdffb2ea92): 手游研发公司(《鸣潮》《战双帕弥什》)，taxonomy 口径"游戏"→互联网/科技
update sources set industry_group = '互联网/科技' where id = '6e84a784-f0f3-4358-a0af-a2fdffb2ea92' and industry_group is null;
-- 应用材料 Applied Materials (a1b5d0e0-4e31-4953-acce-1f37f3515d99): 半导体设备制造商，taxonomy 口径"半导体设备"→制造/工业
update sources set industry_group = '制造/工业' where id = 'a1b5d0e0-4e31-4953-acce-1f37f3515d99' and industry_group is null;
-- 思科 Cisco (7753ad28-9f9f-4314-87af-baef2e211744): 网络通信设备制造商，taxonomy 口径"网络设备/通信设备"→制造/工业
update sources set industry_group = '制造/工业' where id = '7753ad28-9f9f-4314-87af-baef2e211744' and industry_group is null;
-- 懂车帝 Dcar (a0b6e262-b731-447b-9ab3-a3dee4f7eb63): 字节跳动旗下汽车内容+交易平台，taxonomy 口径"汽车·内容"→汽车/出行
update sources set industry_group = '汽车/出行' where id = 'a0b6e262-b731-447b-9ab3-a3dee4f7eb63' and industry_group is null;
-- 拓竹科技 (c5688575-ece8-438f-b614-5dc65fa29c54): 3D 打印机制造商(Bambu Lab)，taxonomy 口径"3D打印"→制造/工业
update sources set industry_group = '制造/工业' where id = 'c5688575-ece8-438f-b614-5dc65fa29c54' and industry_group is null;
-- 拳头游戏 Riot Games (4785938f-9efb-46a0-9754-6b997deff7f0): 游戏研发公司(《英雄联盟》)
update sources set industry_group = '互联网/科技' where id = '4785938f-9efb-46a0-9754-6b997deff7f0' and industry_group is null;
-- 摩根士丹利 Morgan Stanley (6d245f76-92a3-4771-bdfe-a62d681f8de7): 全球性投资银行
update sources set industry_group = '金融' where id = '6d245f76-92a3-4771-bdfe-a62d681f8de7' and industry_group is null;
-- 杜邦 DuPont (b734c555-ec48-404e-a394-d936ff2ee1fd): 化工/材料科学公司，taxonomy 口径"化工"→能源/化工
update sources set industry_group = '能源/化工' where id = 'b734c555-ec48-404e-a394-d936ff2ee1fd' and industry_group is null;
-- 极致游戏 (c381f480-246d-4645-a7a6-a7554fadffab): live 搜索核验，厦门网络游戏研发运营公司(837011新三板)
update sources set industry_group = '互联网/科技' where id = 'c381f480-246d-4645-a7a6-a7554fadffab' and industry_group is null;
-- 横店集团 (81a97f00-5189-4e31-bc60-1b77045b2624): 不更新，保持 NULL。live 搜索核验：磁性材料(横店东磁)/医药(普洛药业)/
--   电机(英洛华)/照明(得邦照明)/影视文化(横店影视)/金融(南华期货)六大产融平台并列经营，
--   无单一行业占绝对主导，拿不准不猜（无 UPDATE 语句）。
-- 欢乐互娱 (4618e8e2-6cf2-47f1-9497-9e70bfd88808): live 搜索核验，上海手游研发发行公司(MMORPG为主)
update sources set industry_group = '互联网/科技' where id = '4618e8e2-6cf2-47f1-9497-9e70bfd88808' and industry_group is null;
-- 沐瞳科技 (90238196-de75-452b-8357-77594e658600): 手游研发公司(《无尽对决》Mobile Legends，字节跳动旗下)
update sources set industry_group = '互联网/科技' where id = '90238196-de75-452b-8357-77594e658600' and industry_group is null;
-- 海亮集团 (fd89a13f-c7f8-4098-a054-520265143ad4): live 搜索核验，集团 2023 年报总营收 1,788 亿元中铜加工 487 亿+
--   金属贸易 1,265 亿=98%，教育业务未单列于三大板块营收——按主营业务(有色金属加工与贸易)
--   归类，taxonomy 口径"有色金属"→能源/化工
update sources set industry_group = '能源/化工' where id = 'fd89a13f-c7f8-4098-a054-520265143ad4' and industry_group is null;
-- 海尔 (c15a409d-2ebb-42a9-90bc-3443dee5eee8): must_apply 清单'海尔'子串命中
update sources set industry_group = '制造/工业' where id = 'c15a409d-2ebb-42a9-90bc-3443dee5eee8' and industry_group is null;
-- 潍柴集团 (990b4266-994d-4dde-b0fe-df44436cc765): must_apply 清单'潍柴'子串命中
update sources set industry_group = '制造/工业' where id = '990b4266-994d-4dde-b0fe-df44436cc765' and industry_group is null;
-- 爱奇艺股份有限公司 (7c09664b-fb19-426e-8b1c-d4cde9c71072): must_apply 清单'爱奇艺'子串命中
update sources set industry_group = '传媒/文娱' where id = '7c09664b-fb19-426e-8b1c-d4cde9c71072' and industry_group is null;
-- 爱奇艺股份有限公司 实习 (cb4c73d4-a149-4221-968a-98eb178fa7b0): must_apply 清单'爱奇艺'子串命中
update sources set industry_group = '传媒/文娱' where id = 'cb4c73d4-a149-4221-968a-98eb178fa7b0' and industry_group is null;
-- 爱彼迎 Airbnb (c1a55342-4d39-4f52-ac7c-e6c1574d9deb): 民宿预订平台，taxonomy 口径"在线旅游"→互联网/科技
update sources set industry_group = '互联网/科技' where id = 'c1a55342-4d39-4f52-ac7c-e6c1574d9deb' and industry_group is null;
-- 爱慕集团 (53c357ca-9ef1-477e-ab7e-fd0cdf14118e): 中国内衣/女装品牌(爱慕内衣)，taxonomy 口径"服装/高端女装"→消费/零售
update sources set industry_group = '消费/零售' where id = '53c357ca-9ef1-477e-ab7e-fd0cdf14118e' and industry_group is null;
-- 百度 (fe23949c-e028-4936-b12f-c8c98bb520b7): must_apply 清单'百度'子串命中
update sources set industry_group = '互联网/科技' where id = 'fe23949c-e028-4936-b12f-c8c98bb520b7' and industry_group is null;
-- 科磊 KLA (90327687-2224-4b84-b537-fd34f1f95f2b): 半导体检测/过程控制设备制造商，taxonomy 口径"半导体设备"→制造/工业
update sources set industry_group = '制造/工业' where id = '90327687-2224-4b84-b537-fd34f1f95f2b' and industry_group is null;
-- 罗氏 Roche (acf002f0-7420-496c-867c-37126bb9c34d): must_apply 清单'罗氏'子串命中
update sources set industry_group = '医疗/医药' where id = 'acf002f0-7420-496c-867c-37126bb9c34d' and industry_group is null;
-- 美光 Micron (be51a473-88f9-4641-8db6-6b30eedea4d1): 存储芯片(DRAM/NAND)制造商，taxonomy 口径"存储芯片"→制造/工业
update sources set industry_group = '制造/工业' where id = 'be51a473-88f9-4641-8db6-6b30eedea4d1' and industry_group is null;
-- 美敦力 Medtronic (7dab5853-ab9b-4dc7-b94b-0f18b44e097f): 全球医疗器械公司
update sources set industry_group = '医疗/医药' where id = '7dab5853-ab9b-4dc7-b94b-0f18b44e097f' and industry_group is null;
-- 脉脉 (c8069411-d6a7-49b3-97b3-593c79707f8e): 中国职场社交平台
update sources set industry_group = '互联网/科技' where id = 'c8069411-d6a7-49b3-97b3-593c79707f8e' and industry_group is null;
-- 腾讯 (0cdb21ca-6a37-401d-9e09-5f2ba093d6ac): must_apply 清单'腾讯'子串命中（'腾讯音乐'清单名更长非子串,不会误命中）
update sources set industry_group = '互联网/科技' where id = '0cdb21ca-6a37-401d-9e09-5f2ba093d6ac' and industry_group is null;
-- 莉莉丝游戏 Lilith (71104011-5242-46b4-9707-beb8d68cc277): 手游研发公司(《万国觉醒》《剑与远征》)
update sources set industry_group = '互联网/科技' where id = '71104011-5242-46b4-9707-beb8d68cc277' and industry_group is null;
-- 葛兰素史克 GSK (294c69a2-23c0-491b-b7f4-91ed709a8c40): 全球制药公司
update sources set industry_group = '医疗/医药' where id = '294c69a2-23c0-491b-b7f4-91ed709a8c40' and industry_group is null;
-- 蔚来 (391dae97-04fc-4bd4-b78f-853b7eb621d8): must_apply 清单'蔚来'子串命中
update sources set industry_group = '汽车/出行' where id = '391dae97-04fc-4bd4-b78f-853b7eb621d8' and industry_group is null;
-- 诺华 Novartis (41d6137a-4c76-42da-8579-53420513ef6c): must_apply 清单'诺华'子串命中
update sources set industry_group = '医疗/医药' where id = '41d6137a-4c76-42da-8579-53420513ef6c' and industry_group is null;
-- 赛诺菲 Sanofi (e7ad9852-56a5-4105-866f-d18b7360da4d): must_apply 清单'赛诺菲'子串命中
update sources set industry_group = '医疗/医药' where id = 'e7ad9852-56a5-4105-866f-d18b7360da4d' and industry_group is null;
-- 轻舟智航科技有限公司 (0a6d374f-1e3d-48e7-a845-c3b23b38aa56): 自动驾驶技术公司(QCraft)
update sources set industry_group = '汽车/出行' where id = '0a6d374f-1e3d-48e7-a845-c3b23b38aa56' and industry_group is null;
-- 通用汽车 GM (a6e70322-1434-4c79-8a5e-bbbcabf06206): 美国整车制造商
update sources set industry_group = '汽车/出行' where id = 'a6e70322-1434-4c79-8a5e-bbbcabf06206' and industry_group is null;
-- 锐明技术 (ed941d1a-ee4a-4692-8945-dd553721960a): live 搜索核验，AIoT 商用车视频监控/安全解决方案公司(002970.SZ)，
--   taxonomy 口径"安防·AIoT"→互联网/科技，与 Verkada 同口径
update sources set industry_group = '互联网/科技' where id = 'ed941d1a-ee4a-4692-8945-dd553721960a' and industry_group is null;
-- 阿斯利康 AstraZeneca (5f7c9918-42ba-4fcd-895d-eb405116e291): must_apply 清单'阿斯利康'子串命中
update sources set industry_group = '医疗/医药' where id = '5f7c9918-42ba-4fcd-895d-eb405116e291' and industry_group is null;
-- 雅培 Abbott (72ba71c9-87ad-4b69-a8e6-87d013764f13): 医疗器械/诊断/营养品公司
update sources set industry_group = '医疗/医药' where id = '72ba71c9-87ad-4b69-a8e6-87d013764f13' and industry_group is null;
-- 霸王茶姬（北京）餐饮管理有限公司 (29d912df-d595-4abe-bb3a-98bdf1e6d33f): must_apply 清单'霸王茶姬'子串命中
update sources set industry_group = '消费/零售' where id = '29d912df-d595-4abe-bb3a-98bdf1e6d33f' and industry_group is null;
-- 面壁智能 (d0fad101-112b-44b5-a614-1047bc0cdd20): 大模型/AI 公司(清华系，MiniCPM 端侧小模型，"AI 六小龙"之一)
update sources set industry_group = '互联网/科技' where id = 'd0fad101-112b-44b5-a614-1047bc0cdd20' and industry_group is null;

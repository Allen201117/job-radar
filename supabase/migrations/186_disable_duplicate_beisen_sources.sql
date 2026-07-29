-- 186: 禁用北森重复源（同一租户被建了 campus + social 两个源，实际抓的是同一份岗位）
--
-- 背景（2026-07-28 live 查实）：
--   北森 340 个 enabled 源只落在 197 个租户上——134 个租户各有 2-3 个源，形如
--   https://{tenant}.zhiye.com/campus 与 .../social。但 BeisenAdapter._httpx_fetch 发的
--   GetJobAdPageList 请求带 `Category: []`（= 不按招聘类别过滤，2026-06-29 为防 list-absence
--   误杀活岗而刻意改成取全部），**URL 路径根本不参与筛选** → campus 源和 social 源抓回来的是
--   同一份全量岗位集。live 验证三家租户 /campus 与 /social 的 Count 完全一致
--   （asymchem 389=389、inovance 433=433、yiche 10=10）→ 禁用其中一个不会少抓任何岗。
--
-- 为什么必须治（不只是浪费一半抓取预算）：
--   两个源抓同一份列表时，某条 jd_url 归**先插入**的那个 source_id 所有；另一个源的历史行
--   就此搁浅，last_seen_at 再也不更新（实测卡了 5-30 天不等，共 ~9300 个假 active 岗）。
--   更糟的是它让缺席探活（jobs_db.sweep_absent_jobs）永久失效：每个源自己那份行有一大半
--   「缺席」（其实是被同租户另一个源接管了），占比越过 50% 安全闸 → 整源跳过 → 死岗永远下不了架。
--   合并到单源后行归属统一，缺席探活自己就能把真下架的岗清掉，无需在此手工改 jobs 状态。
--
-- 做法：每个租户保留「3 天内刷新岗最多」的那个源（并列取 active 多的，仍并列取 id 小的），
--   其余 disable。**只 disable 不删行**（把 enabled 改回 true 即可回滚）；这些源名下的 jobs
--   一行不动，交给缺席探活按正常节奏下架，避免误杀——ccccltd 等大租户官网真实在招 2614 条
--   > 单次抓取上限，其搁浅行里混着真岗，绝不能在这里一刀切标 expired。
--
-- 安全闸：下面的 exists 子句保证「该租户至少还留着另一个 enabled 源」才禁用，
--   即便本迁移应用时线上数据已漂移（例如保留的那个源被人手工禁掉了），也绝不会把某个租户抓空。

update public.sources s set enabled = false
where s.id in (
  '5cd8e60a-7cec-4c7a-9b18-c309716a14a6',  -- KK集团 | https://kkguan.zhiye.com/social | 挂 0 岗
  '3acf8729-23dc-4fd9-9537-076046a44ffb',  -- e签宝 | https://esign.zhiye.com/social | 挂 0 岗
  'f90862d3-7e5e-4e85-81af-bc1dd3e72804',  -- 三生制药 | https://3sbio.zhiye.com/social | 挂 201 岗
  '9c211c75-d22f-4337-ad36-4a32544b04ea',  -- 上汽通用汽车有限公司 | https://sgm.zhiye.com/campus | 挂 19 岗
  '418b1a9f-2e31-4bd0-bcfb-dfc4ae340539',  -- 上海医药集团股份有限公司 | https://sph.zhiye.com/social | 挂 148 岗
  '21ad7e80-c734-44c9-b537-55935e2f9430',  -- 上海复宏汉霖生物技术股份有限公司 | https://henlius.zhiye.com/social | 挂 87 岗
  '05034bb4-f001-4ab2-9355-eda16d2957db',  -- 上海观安信息技术股份有限公司 | https://guanan.zhiye.com/social | 挂 286 岗
  '55fa88b2-0222-4b40-a7bb-dd671870bbf1',  -- 东方日升新能源 | https://risen.zhiye.com/campus | 挂 16 岗
  '55a0d801-10c2-493b-90aa-dca479c69b7a',  -- 东软医疗 | https://neusoftmedical.zhiye.com/campus | 挂 0 岗
  '0c9e073a-8abf-4ea1-9d45-dc640e11ae89',  -- 东鹏 | https://dongpeng.zhiye.com/social/jobs | 挂 0 岗
  '573f41e3-6130-43ee-b498-41b47c06078d',  -- 中国交建 | https://ccccltd.zhiye.com/social | 挂 478 岗
  '5b4e8e8e-070c-4112-81a5-e72d9a41c564',  -- 中国人民保险 | https://picc.zhiye.com/social | 挂 83 岗
  '0bce1471-c5e3-41b5-bca7-b0bd0a602828',  -- 中国外运 校招 | https://sinotrans.zhiye.com/campus | 挂 0 岗
  '6a7cd927-527d-4c69-a254-7271dc0e77a3',  -- 中国旺旺控股有限公司 | https://wantwant.zhiye.com/social | 挂 132 岗
  '05008cb7-ce6f-410a-a039-b584993d097b',  -- 中国燃气控股有限公司 | https://chinagasholdings.zhiye.com/social | 挂 42 岗
  'c8be359a-46a0-4164-84c0-749dc00a0adc',  -- 中国银河证券股份有限公司 | https://chinastock.zhiye.com/campus | 挂 66 岗
  '5ce08cdf-b666-4c11-9cbb-429f9982785c',  -- 中核集团 CNNC | https://cnnc.zhiye.com/social/jobs | 挂 4 岗
  '073beacc-cd4e-4183-a4d6-7fcaac0cd719',  -- 中环半导体 | https://tjsemi.zhiye.com/campus | 挂 0 岗
  '70cee59d-292f-411b-9823-33fa76d2554d',  -- 中金公司 | https://cicc.zhiye.com/campus | 挂 3 岗
  'abae269b-6180-4d1e-9c03-b21f14262855',  -- 云知声 | https://unisound.zhiye.com/campus | 挂 0 岗
  '16159cdd-d89f-42b5-9ab0-26038e89c441',  -- 以岭药业 | https://yiling.zhiye.com/social | 挂 0 岗
  'a56836fa-e870-4bae-a740-6c3426b4b2f1',  -- 传音控股 Transsion | https://transsion.zhiye.com/social/jobs | 挂 0 岗
  'dbca9845-0ce3-4f4b-ba3e-9acff85b1c0b',  -- 信达生物 | https://innoventbio.zhiye.com/campus | 挂 85 岗
  '095c9106-e0c4-4cfc-b35c-f0013e2b6489',  -- 健之佳健康连锁集团股份有限公司 | https://jianzhijia.zhiye.com/social | 挂 7 岗
  '1ad20aee-e3f7-48a2-8628-818a87a05ba5',  -- 公牛集团 GONGNIU | https://gongniu.zhiye.com/social/jobs | 挂 0 岗
  '8a1c1d4d-bdbd-4044-9181-afd8d08ba869',  -- 内外NEIWAI | https://neiwai.zhiye.com/social | 挂 0 岗
  '9aeaaa69-eb44-4a92-a3a5-0ddafc797089',  -- 凯莱英 | https://asymchem.zhiye.com/social | 挂 332 岗
  '19d9042b-4f26-49e9-a601-54ceffa9c443',  -- 创想三维科技股份有限公司 | https://creality.zhiye.com/social | 挂 52 岗
  '0c243bec-e224-4c0b-a257-65cafa03d3a0',  -- 劲仔食品集团股份有限公司 | https://jinzaifood.zhiye.com/social | 挂 61 岗
  '1c989e97-8f75-4ac5-9820-ce840473b178',  -- 北京天融信科技股份有限公司 | https://topsec.zhiye.com/campus | 挂 8 岗
  '0bc5f859-520e-4146-aed1-e65957166e5b',  -- 北醒（北京）光子科技有限公司 | https://benewake.zhiye.com/social | 挂 13 岗
  '69160d24-d1b2-4c85-a62d-af6894a6a372',  -- 医渡科技 | https://yiducloud.zhiye.com/social | 挂 0 岗
  'ad49bf35-eb74-46f5-bf3a-7f25c378f215',  -- 华大基因 | https://genomics.zhiye.com/campus | 挂 103 岗
  '3e3de953-7389-45c7-ace5-a7c5b47b927f',  -- 华峰集团 | https://huafeng.zhiye.com/social | 挂 54 岗
  '7fc21ccc-109d-432f-a3f9-b26b62f10853',  -- 华海清科 | https://hwatsing.zhiye.com/social | 挂 1 岗
  '171f329f-4f5d-4a47-8499-a71ebb03863f',  -- 卓胜微 Maxscend | https://maxscend.zhiye.com/social/jobs | 挂 0 岗
  '290f6a14-0dc8-45e3-9929-1399b9d8d294',  -- 卡斯柯信号有限公司 | https://casco.zhiye.com/social | 挂 37 岗
  '466d30b9-000d-4c26-9307-33b90be75397',  -- 厦门象屿股份有限公司 | https://xiangyu.zhiye.com/campus | 挂 73 岗
  '0ad31a2d-7ec1-4be8-a845-45f4bd614e5d',  -- 名创优品 | https://miniso.zhiye.com/social | 挂 0 岗
  'c3f2385b-650a-4d1c-9e19-a6740f012f79',  -- 名创优品 MINISO | https://miniso.zhiye.com/social/jobs | 挂 0 岗
  '91dd441a-438f-40ad-94b7-70e6bc3f55ce',  -- 启德教育 | https://eic.zhiye.com/social | 挂 15 岗
  '28b428f1-228e-4e67-96de-a4cff96c71d9',  -- 启明星辰信息技术集团股份有限公司 | https://venustech.zhiye.com/social | 挂 32 岗
  'e2378b0a-bfc8-4f76-81cb-fd260843d57b',  -- 哈啰 | https://hellobike.zhiye.com/social | 挂 2 岗
  '6675f933-91d8-4863-9cba-00d0d385afb7',  -- 喜茶 | https://heytea.zhiye.com/campus | 挂 80 岗
  '0f861fda-b539-456d-a7ce-865a0fcc3e2e',  -- 国信证券 | https://guosen.zhiye.com/social | 挂 0 岗
  '98afc0cd-d17e-45ec-8d69-3114b88de333',  -- 国轩高科 | https://gotion.zhiye.com/campus | 挂 67 岗
  '1d00cfd9-1abd-46cd-b99d-f6b4fc164e30',  -- 国轩高科 | https://gotion.zhiye.com/social/jobs | 挂 0 岗
  '0395ca2d-3bee-47a7-9e3f-4eca6604af65',  -- 复星医药 | https://fosunpharma.zhiye.com/campus | 挂 14 岗
  '0e87acc7-3188-460a-b851-fd9e8094e5bc',  -- 大润发（北京）商业有限公司（欧尚、大润发） | https://rt-mart.zhiye.com/social | 挂 18 岗
  'bbd35ded-1082-4935-99fc-bff9261f0bf7',  -- 奇瑞汽车 CHERY | https://chery.zhiye.com/social/jobs | 挂 1 岗
  'b5e6d10f-a50c-475a-bb27-1dd72721a335',  -- 孚能科技（赣州）股份有限公司 | https://farasisenergy.zhiye.com/social | 挂 56 岗
  '4a75fd56-c820-4a79-92ee-78d00b0e9aa5',  -- 宁波合盛集团 | https://hoshine.zhiye.com/campus | 挂 28 岗
  'e333333a-9a77-4044-b4ca-0361252a7a3f',  -- 宁波申洲针织 | https://shenzhou.zhiye.com/campus | 挂 1 岗
  'aa5f8cc6-68e1-44e9-ac53-ec5a762f61cb',  -- 宇树科技（杭州）有限公司 | https://unitree.zhiye.com/campus | 挂 34 岗
  '8167affa-d8d4-4b28-810d-9a870601be05',  -- 安集科技 | https://anjimicro.zhiye.com/social | 挂 3 岗
  '3f500c2b-88d2-418c-9db3-af258a318f44',  -- 宗申产业集团 | https://zongshen.zhiye.com/campus | 挂 5 岗
  '195d2b69-50c5-42ef-a619-e5f5bb73d154',  -- 容百科技 | https://ronbay.zhiye.com/social | 挂 31 岗
  '3a381ab2-f13a-47f9-8017-05e9d11e8302',  -- 山东玲珑轮胎股份有限公司 | https://linglong.zhiye.com/campus | 挂 25 岗
  '150809d3-cf1c-471a-9b24-7ea3422e77f0',  -- 山石网科通信技术股份有限公司 | https://hillstonenet.zhiye.com/social | 挂 23 岗
  '58ad41fd-0ccf-424c-8a70-15780cc9103b',  -- 巨化集团有限公司 | https://juhua.zhiye.com/social | 挂 51 岗
  '5ffd1193-2734-406e-b405-a67804a8b2c9',  -- 广和通 | https://fibocom.zhiye.com/campus | 挂 84 岗
  '8963a700-5632-4f6f-b599-505ab130b3cd',  -- 德力西集团 | https://delixi.zhiye.com/social | 挂 26 岗
  '1c0f7f7b-4f58-461c-a524-5b303e6a4a5f',  -- 德方纳米 | https://dynanonic.zhiye.com/social | 挂 0 岗
  '33e8760c-60d2-4d26-863c-f5b55c7dd428',  -- 思必驰 | https://aispeech.zhiye.com/campus | 挂 0 岗
  '9c261d12-8b93-4ad8-a756-ff77239e5c5f',  -- 思念食品有限公司 | https://synear.zhiye.com/social | 挂 22 岗
  'c9a7ea94-13ac-4811-9da3-194bae90362e',  -- 慕思健康睡眠股份有限公司 | https://derucci.zhiye.com/campus | 挂 4 岗
  '1fdc52ef-b613-4676-a5d6-6e6981404cbe',  -- 我爱我家 | https://5i5j.zhiye.com/social | 挂 5 岗
  '0a61fa2a-2f97-49d0-99a4-9aea40922be2',  -- 扬子江药业集团 | https://yangzijiang.zhiye.com/social | 挂 301 岗
  '003c9cb4-1fc8-477e-a86c-463025485d54',  -- 扬翔股份有限公司 | https://yangxiang.zhiye.com/campus | 挂 20 岗
  'ba2b9532-cd04-4d5f-aa6b-d652284c01ce',  -- 招商局集团 | https://cmhk.zhiye.com/campus | 挂 12 岗
  '0fc45ab5-4d26-42fb-9449-ebbdab76869b',  -- 招商局集团 | https://cmhk.zhiye.com/social | 挂 14 岗
  'a4004e32-16b8-42e3-9601-67b288bb99a4',  -- 招商蛇口 | https://cmsk1979.zhiye.com/campus | 挂 0 岗
  '0f1049ae-0e19-41bf-ab0f-8591a76821af',  -- 振石控股集团 | https://zhenshigroup.zhiye.com/campus | 挂 15 岗
  '4597fbc5-7598-413b-aa19-2c74ab7ba696',  -- 摩尔线程 | https://mthreads.zhiye.com/campus | 挂 67 岗
  '3edb70bd-98a2-46d5-89b3-413985730e61',  -- 新产业生物医学工程股份有限公司 | https://snibe.zhiye.com/campus | 挂 17 岗
  'b7d7c5fe-92d5-484c-8a19-cf773527d9d6',  -- 新华三信息技术 | https://h3c.zhiye.com/social | 挂 291 岗
  '6c2359cf-0095-4613-aa25-c4cc01cf5b5e',  -- 新奥集团 | https://enn.zhiye.com/campus | 挂 2 岗
  '255bd50d-a0b6-43c8-b89b-444e8b58f507',  -- 新易盛 | https://eoptolink.zhiye.com/campus | 挂 58 岗
  '76d5eab8-8f3a-49e9-9c7c-26b138fbd72a',  -- 无锡信捷电气股份有限公司 | https://xinje.zhiye.com/campus | 挂 15 岗
  'd5955f89-4752-4776-9dc2-6142b9b7609c',  -- 日立能源（中国）有限公司 | https://hitachienergy.zhiye.com/social | 挂 349 岗
  '292b0612-752b-4182-9e7d-ac6a4d22d6ac',  -- 时代天使生物科技有限公司 | https://angelalign.zhiye.com/campus | 挂 4 岗
  '032338d7-a17a-46bb-8125-4952cb9873a0',  -- 易车控股有限公司 | https://yiche.zhiye.com/social | 挂 6 岗
  '3f9eaf8d-73de-4003-8221-9b08e18e1d89',  -- 昭衍新药 | https://joinnlab.zhiye.com/social | 挂 0 岗
  '74c612a3-9e53-47d5-b60e-37ad97ef23d0',  -- 晶丰明源 | https://bpsemi.zhiye.com/campus | 挂 135 岗
  '3a13336f-f474-4b34-a46f-442ed574b590',  -- 曙光信息产业 | https://sugon.zhiye.com/social | 挂 13 岗
  '14be72f5-22b3-41b6-8bab-cf64d79696f9',  -- 有赞 | https://youzan.zhiye.com/campus | 挂 0 岗
  '205cbc2f-5439-436a-8f43-be254f8749b1',  -- 来伊份股份有限公司 | https://laiyifen.zhiye.com/campus | 挂 16 岗
  'a4ff8ca1-1294-4618-abc9-d458f79dfb56',  -- 核桃编程 | https://hetao101.zhiye.com/social | 挂 0 岗
  '27fd1388-a16c-4eb9-aceb-007737d29742',  -- 欣旺达 | https://sunwoda.zhiye.com/social/jobs | 挂 0 岗
  '731a4e2a-f602-4208-a002-6d5e8c5d0f18',  -- 欣旺达电子 | https://sunwoda.zhiye.com/campus | 挂 16 岗
  'e18c4888-b4b5-43ce-ba9b-3790313c987c',  -- 正大天晴药业集团股份有限公司 | https://cttq.zhiye.com/social | 挂 807 岗
  '7bdada55-1a66-4b55-9eaf-787acbd43b88',  -- 正大集团（中国）有限公司 | https://cpgroup.zhiye.com/campus | 挂 381 岗
  '8ef5a015-0916-45c4-a769-b9c4f2344d3d',  -- 永辉超市 | https://yhchaoshi.zhiye.com/campus | 挂 5 岗
  '4149279a-327d-4815-bdcc-078c7ca24234',  -- 汇川技术 | https://inovance.zhiye.com/campus | 挂 2 岗
  '4c7ac642-88b2-4ea7-86e7-c35ac295909d',  -- 河南双汇投资发展 | https://shuanghui.zhiye.com/campus | 挂 9 岗
  '36bcece2-815d-496c-8aa1-74d23f4f3b77',  -- 泡泡玛特 POP MART | https://popmart.zhiye.com/social/jobs | 挂 1 岗
  '3540afa5-1885-425f-a506-4cd20c34e33e',  -- 海天集团 校招 | https://haitian.zhiye.com/campus | 挂 0 岗
  '562a82c7-0255-4851-9808-d750446ebdf2',  -- 海目星 | https://hymson.zhiye.com/campus | 挂 1 岗
  '87df3c41-12f0-4d23-8148-459612f86643',  -- 深圳传音控股 | https://transsion.zhiye.com/social | 挂 165 岗
  '417d93d2-5d07-410f-ba1b-35d866f91958',  -- 深圳市东阳光实业发展 | https://hec.zhiye.com/social | 挂 46 岗
  '9a2ad996-e715-4672-92d5-93a560365236',  -- 深圳市普渡科技有限公司 | https://pudutech.zhiye.com/social | 挂 151 岗
  '38291b80-631f-4b56-87fd-d24f50ce8091',  -- 深圳市汇川技术 | https://inovance.zhiye.com/social | 挂 540 岗
  '384fd7e0-646d-43d7-86ca-44b78545c6db',  -- 深圳市纵腾集团有限公司 | https://zongteng.zhiye.com/campus | 挂 7 岗
  '444df356-3d96-4b58-92f6-df36d291fd6a',  -- 深圳市英威腾电气股份有限公司 | https://invt.zhiye.com/campus | 挂 275 岗
  '94ae66ca-3445-43da-886e-892828ee3398',  -- 深圳有方科技股份有限公司 | https://neoway.zhiye.com/social | 挂 95 岗
  '03f93843-7554-4ff2-8986-daa372e21569',  -- 漱玉平民大药房连锁股份有限公司 | https://sypm.zhiye.com/campus | 挂 0 岗
  '0c2b91e6-eb08-47ed-be7b-33b7dc4e16ab',  -- 白象食品股份有限公司 | https://baixiangfood.zhiye.com/campus | 挂 103 岗
  'a0121a9d-e0ad-4582-a2bb-e229ac76d483',  -- 益禾堂餐饮管理有限公司 | https://yihetang.zhiye.com/social | 挂 17 岗
  '8ce04dc1-dff8-4e21-beb7-a0348dbd5c87',  -- 盐津铺子食品股份有限公司 | https://yanjinpuzi.zhiye.com/campus | 挂 17 岗
  '35001c51-3fa3-49b0-b9d0-81e734eb2f86',  -- 睿智医药科技有限公司 | https://chempartner.zhiye.com/campus | 挂 41 岗
  '2b2690e2-e5e2-4d69-aada-c765613cafb0',  -- 石头科技 | https://roborock.zhiye.com/campus | 挂 54 岗
  '693f61b9-61d9-40ae-aa4d-96575b29c8ab',  -- 神州数码集团 | https://digitalchina.zhiye.com/campus | 挂 153 岗
  '7fd3115a-cf6e-41c0-8a76-1f270ab5d727',  -- 神策数据 | https://sensorsdata.zhiye.com/campus | 挂 1 岗
  '1b9bdf89-1427-45a0-929d-644b66df6de1',  -- 科伦药业 | https://kelun.zhiye.com/social | 挂 2 岗
  '3038bd9e-2e1d-4e16-b9dc-e029522c773e',  -- 科大讯飞 | https://iflytek.zhiye.com/social/jobs | 挂 33 岗
  '816ec439-6b7f-47b8-9ede-1347043c8677',  -- 米其林（中国）投资有限公司 | https://michelin.zhiye.com/campus | 挂 0 岗
  '7aac0a62-907c-478b-b979-8bf7f3a621f7',  -- 纳思达 | https://ninestar.zhiye.com/campus | 挂 49 岗
  '6928063e-16ba-46b8-922c-734bf3ef4c8e',  -- 良品铺子 | https://lppz.zhiye.com/social | 挂 0 岗
  '21cbfad4-f3cd-4859-93fe-0d9551904c0b',  -- 芯海科技（深圳）股份有限公司 | https://chipsea.zhiye.com/social | 挂 49 岗
  '1795c585-4d38-41b6-91e7-583072052b88',  -- 苏州东山精密制造 | https://dsbj.zhiye.com/campus | 挂 0 岗
  '5f86c026-6e7c-43cd-a815-286d66e044b1',  -- 苏州瑞可达连接系统股份有限公司 | https://recodeal.zhiye.com/campus | 挂 11 岗
  '0622ffe9-1740-4a63-8180-7d5f199acfef',  -- 蒙牛 | https://mengniu.zhiye.com/campus | 挂 0 岗
  'c089e4ae-7efb-4cf8-a7a0-1e7b3b4926b7',  -- 蒙牛 | https://mengniu.zhiye.com/social | 挂 9 岗
  '06ba30a2-6eb3-4089-b384-78b79ba13b5b',  -- 蜂巢能源 | https://svolt.zhiye.com/campus | 挂 0 岗
  '85273c9e-262c-420c-b704-09c3c4556304',  -- 蜂巢能源 | https://svolt.zhiye.com/social | 挂 21 岗
  '77fa77b7-fe13-4243-9486-31c0ce47cab3',  -- 豪迈科技 | https://himile.zhiye.com/campus | 挂 130 岗
  '547f7a69-4d7c-4caf-8eca-ed872d8cf163',  -- 贝壳找房 | https://ke.zhiye.com/campus | 挂 5 岗
  'fbe45bb7-8f28-40fc-9a98-c4b841e45966',  -- 货拉拉 Lalamove | https://huolala.zhiye.com/social | 挂 0 岗
  '172dfb80-6b5f-4618-ad9e-85f38e203ea9',  -- 赛轮集团股份有限公司 | https://sailuntire.zhiye.com/social | 挂 45 岗
  'aafb8a3c-c4d2-42ee-a1bb-59fde8eba59a',  -- 转转 | https://zhuanzhuan.zhiye.com/social | 挂 0 岗
  '695a0c8b-abbd-4a73-9d2e-05187417cbc2',  -- 迈瑞医疗 | https://mindray.zhiye.com/social | 挂 77 岗
  '5d693d41-3cf0-4f67-9680-31e40c479e8f',  -- 追觅科技 | https://dreame.zhiye.com/social | 挂 0 岗
  '21dc62ef-b20b-4ac4-86d9-073a2cd2b9c5',  -- 通威股份 | https://tongwei.zhiye.com/social | 挂 0 岗
  'a8bdab5c-19ab-4eb8-b677-1b5f84265cf3',  -- 通用技术集团 | https://genertec.zhiye.com/campus | 挂 272 岗
  '2abb60a6-3c57-415c-a499-c99b2dc0ba32',  -- 金发科技 | https://kingfa.zhiye.com/social | 挂 25 岗
  '36a5ed93-c11f-462c-b08f-46e92e049cad',  -- 金域医学 | https://kingmed.zhiye.com/social | 挂 45 岗
  '2c4240f9-32b3-4d1e-8fbe-37a467a3b434',  -- 长安汽车 | https://changan.zhiye.com/campus | 挂 4 岗
  '1cc81a9f-7a40-43db-bbd1-bd7c11a2519f',  -- 长安汽车 | https://changan.zhiye.com/social | 挂 30 岗
  'a457943c-36d6-4689-81c5-384e99566b49',  -- 长江存储 | https://ymtc.zhiye.com/campus | 挂 8 岗
  'b0fd9bbe-cd79-448e-86ac-b5a8d8894c98',  -- 长鑫存储技术有限公司 | https://cxmt.zhiye.com/social | 挂 1175 岗
  '16280c79-cc0a-41af-a6c0-84fa24c0335c',  -- 零跑汽车 | https://leapmotor.zhiye.com/social/jobs | 挂 66 岗
  '1f2d8a9c-b2a8-47c1-a789-ddd15bf6d852',  -- 青蛙王子（中国）日化有限公司 | https://qwwz.zhiye.com/campus | 挂 4 岗
  '95c9cdae-2c6a-4e75-b597-544094a94b35'   -- 黑芝麻智能 | https://bsthr.zhiye.com/social | 挂 0 岗
)
  and s.enabled
  and exists (
    select 1 from public.sources k
    where k.enabled
      and k.id <> s.id
      and k.adapter_name = 'beisen'
      and substring(k.source_url from '^[a-zA-Z]+://([^/]+)')
        = substring(s.source_url from '^[a-zA-Z]+://([^/]+)')
  );

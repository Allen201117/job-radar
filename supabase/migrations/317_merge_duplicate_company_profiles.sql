-- 317 合并洞察库里的重复公司画像（创始人 2026-10-11 同意）
--
-- ❌ 现象：同一家公司在 company_profiles 里有 2~5 个画像（知乎 / 知乎 Zhihu、云尖信息 / 云尖信息 校招、
--    腾讯音乐 / 腾讯音乐 TME…）。说法挂在一个没有岗位的画像上、岗位挂在另一个没有说法的画像上，
--    17 家公司在洞察库里一张带说法的卡都出不来，16 家出了两三张卡；重复画像还各自排队花搜索额度。
-- ✅ 根因：建画像的入口只按正名去重（upsert on conflict company），同一家公司的源叫「X」「X 校招」「X 英文名」
--    就各建一个。入口已在同一次提交里改成先认别名（crawler/company_profile_resolve.py、lib/insight-profile-store.ts）。
-- 📄 清单与判据：docs/reviews/2026-10-11-insight-duplicate-profiles.md（全库 1,511 个画像两两比对，629 对逐对判完）。
--
-- 本迁移做四件事，全在一个事务里（scripts/db-migrate.sh 用 psql -1 跑），任何一步断言不过就整体回滚：
--   ① 136 组确属同一家的画像合成一个：179 个画像名下的主体 / 洞察 / 校招周期改挂到留下的那个，
--      名字登记成它的别名，然后删掉这 179 个画像；
--   ② 15 个国聘「子公司（集团）」写法的 0 岗残留画像直接删（同一家子公司另有一个有岗的画像；
--      这些残留的括号是当初挂错的集团，不登记成别名）；
--   ③ 4 个撞到别家公司的别名去掉（两边不是同一家，不合并）；
--   ④ 动之前把涉及的行整份留底到 archive 模式（不对外暴露），回滚只能靠它。
--
-- ⚠️ insight_subjects / insight_items 对 company_profiles 都是 on delete cascade：必须先改挂、后删画像，
--    顺序反了说法会跟着画像一起没。
-- ⚠️ 主体的去留在库里现算（不冻结主体 id）：bu_extract 每晚会增删业务线主体，冻结的清单过一晚就对不上。
--    画像这一层是冻结的（下面三张清单），画像不存在或改了名就回滚。
-- 真库回滚演练的行数记在报告 §8。

set local lock_timeout = '10s';
set local statement_timeout = '300s';

create temp table _merge (
  loser_id uuid primary key,
  loser_company text not null,
  keep_id uuid not null,
  keep_company text not null
) on commit drop;
insert into _merge (loser_id, loser_company, keep_id, keep_company) values
  ('ce964026-eb5e-4b63-8627-80e4f3cc8908', 'AB InBev', 'c257b103-6945-4f74-82a2-c923e43de492', 'Anheuser-Busch InBev 百威'),
  ('9a4e8e6f-a869-4ba4-81ea-348174d25067', '苹果中国', '931b2456-e733-422e-92c7-6cefcc52e9bb', 'Apple'),
  ('a1bc8741-b876-4809-af69-250fba343000', '百特 Baxter', 'a6011738-ec0d-467e-a26c-5c2cd4e9c4d7', 'Baxter 百特'),
  ('27315cbc-5598-47c7-b10f-9e0c996f3bc0', '拜耳 Bayer', '1e9a804d-9db9-4112-957b-a3e8471b3e2f', 'Bayer'),
  ('ce64a4d2-59b6-4cad-a10c-ddf0f57847cf', 'DBS', '0b58f61a-fb88-4fb8-b9d6-23a4b878b62f', 'DBS Bank 星展银行'),
  ('b314d09b-501a-44ce-8e04-b623774b0fca', 'JLL', '0df3a7c7-7d52-4b3a-997c-ec65dd3e643f', 'JLL 仲量联行 Jones Lang LaSalle'),
  ('7a403db9-8bff-4224-8e10-df0d0d3304c1', 'Mars', '7ef4f7c0-90b7-4ad4-af73-de7c06d02605', 'Mars, Inc. 玛氏'),
  ('53d7c853-4ade-4b54-93a0-b88f29900adc', '微软中国', 'f1f56955-8cd4-4f0f-b5b3-623be35db0ea', 'Microsoft 微软'),
  ('8e6bda48-ef4c-44dd-8f26-696f4650bb9f', 'TCL 实习', 'fa815d4e-bb1f-484a-ad32-7f141c8bef9e', 'TCL'),
  ('88ea3cd8-7882-4acc-9ec7-49ad6446e39f', 'TCL 校招', 'fa815d4e-bb1f-484a-ad32-7f141c8bef9e', 'TCL'),
  ('400f382a-5e46-4acb-a3e3-ff808faa0359', '万科 Vanke', '7f2fb546-39bf-4fe4-a583-75b7b906723f', '万科'),
  ('968e5cee-b4aa-4c03-93c7-dae07f8f525c', '万科企业', '7f2fb546-39bf-4fe4-a583-75b7b906723f', '万科'),
  ('498c2053-278a-4d18-91d2-f900ee549f48', '万科企业 校招', '7f2fb546-39bf-4fe4-a583-75b7b906723f', '万科'),
  ('9a3bfc77-51f5-40e1-a419-cc685e98ba84', '万达控股集团', 'dffe6e38-2c8e-431a-b9fb-1441396e47fc', '万达集团'),
  ('56a31028-cc42-4601-a083-a958b29ffafa', '三只松鼠 Three Squirrels', '81a4721f-c303-4b90-9083-1baa8bda6ffb', '三只松鼠'),
  ('b19791e6-0214-41d7-b696-3ea3508a988b', '苏州东山精密制造', 'd9b23d87-20ca-4d87-bd25-c2e770f1a617', '东山精密'),
  ('3a7dd2dc-dece-4ca5-9d15-aa5f053278b7', '东风汽车 DFMC', 'a89c8f3d-1c4c-4581-8786-9fbf9a833018', '东风汽车'),
  ('440fd9f1-c7b2-435c-97c0-407e1d1ab721', '东风汽车 DFMC 实习', 'a89c8f3d-1c4c-4581-8786-9fbf9a833018', '东风汽车'),
  ('c28e5936-9610-4b5f-ab2f-bd09092e6b7f', '东风汽车 DFMC 校招', 'a89c8f3d-1c4c-4581-8786-9fbf9a833018', '东风汽车'),
  ('22a48afd-fc2e-4dfa-9e87-b95b204b27bd', '中兴通讯股份有限公司', 'dcf75e21-2e0c-4e3d-99fd-f94676b3528b', '中兴通讯'),
  ('549b624b-42eb-4955-ab05-6f40822e680c', '中国中化 ChemChina 实习', '86035ff0-1ee3-41c7-b571-5f6f7b97dec7', '中国中化 ChemChina'),
  ('d8799e71-bf47-4751-8c16-099c926eea1c', '中国中化 ChemChina 校招', '86035ff0-1ee3-41c7-b571-5f6f7b97dec7', '中国中化 ChemChina'),
  ('42dbeef8-44fe-4a19-a90e-3216a0a075a7', '中国交建 校招', '08009b4e-e7e7-4633-9360-fa3d50fc0c6f', '中国交建'),
  ('76f3dd23-bc3e-40ab-ac6b-2b3b0299cbd9', '中国人保', '7e87b8f5-47de-4827-bb4e-5b5282cb34bf', '中国人民保险'),
  ('b4c08226-6e9b-41f5-b5cc-01d60097ce61', '中国人民保险 校招', '7e87b8f5-47de-4827-bb4e-5b5282cb34bf', '中国人民保险'),
  ('effb0814-a410-4db5-8899-77200b4d38e3', '中国外运 校招', '0f9c1455-9cee-482a-afa1-59f2c689cdbb', '中国外运'),
  ('96101ffe-ee7b-4f30-bb0f-91135575db24', '中外运', '0f9c1455-9cee-482a-afa1-59f2c689cdbb', '中国外运'),
  ('dcfc0abc-c752-4a5e-8b07-603a3c7d0abc', '太平洋保险', '095a7838-5744-4a3e-858a-10c8a3ae62ce', '中国太平洋保险'),
  ('1122b50c-7f72-41e4-b744-78a0063ad791', '中国物流集团 校招', '6fcb8372-d794-498d-ac6a-bb9dd86c5af8', '中国物流集团'),
  ('c0e45699-aedd-4d5a-aef6-4b57812f5756', '中国电信国际 校招', 'db48ed47-d5d5-4201-b8bf-858937e52a41', '中国电信国际'),
  ('82374305-58c9-40b1-a158-8af93c9c364b', '中微公司 AMEC', 'dfd16ccf-5d8d-41d9-90b0-a640b37792b0', '中微公司'),
  ('bedf05ae-b908-46d9-b0dc-a600296cd7f4', '中核集团 CNNC', 'e710767d-86a5-4c39-ab43-9050744b44cc', '中核集团'),
  ('e58a45a2-8cd6-4f04-85a2-861c3d53d2ea', '中通', 'ddb096a0-d171-45dd-815d-63dafa08b9e0', '中通快递'),
  ('a6365565-2cb8-42b5-b4ea-b20153c06a5f', '云南白药 YNBY', 'f52b592c-33f4-479c-84ea-9f9f6f0ea027', '云南白药'),
  ('e34df220-5746-4a2b-bdd6-41fe352f4ecc', '云南白药 YNBY 实习', 'f52b592c-33f4-479c-84ea-9f9f6f0ea027', '云南白药'),
  ('612e0e5b-0b67-475c-b118-125cfd4e091d', '云南白药 YNBY 校招', 'f52b592c-33f4-479c-84ea-9f9f6f0ea027', '云南白药'),
  ('f1d312a5-e7c5-4bf7-9a62-3dcda4156b85', '云尖信息 实习', 'ea71102a-a6dc-453c-adb1-5fe44b2bfd0d', '云尖信息'),
  ('7ca45b9f-ab05-43d8-babd-0edffac971f4', '云尖信息 校招', 'ea71102a-a6dc-453c-adb1-5fe44b2bfd0d', '云尖信息'),
  ('3a20a4f6-d272-4137-8a5b-9af35fe72778', '京东集团', '207d8c53-4c84-435a-ba4e-21544295ba4b', '京东'),
  ('27ea009c-7494-4d63-981d-cc4810518596', '京东方 BOE', '0e2e7cf5-4b79-4743-950b-ed4eceedff27', '京东方'),
  ('d3d682e9-2fad-4b71-be0b-4f4c19634991', '亿纬锂能 校招', '1163951b-323f-4fea-b9cf-04a1626f6068', '亿纬锂能'),
  ('feceebe2-9106-40d6-9fba-cccc60bf6d87', '伊利股份', '970e6294-812c-41c0-9488-f0bb1f15d3ad', '伊利'),
  ('7135dfae-33fc-4677-bcef-993c16696016', '作业帮 Zuoyebang', 'e593823a-c095-45b7-8948-76ec5149ceea', '作业帮'),
  ('817c068c-7115-45f2-84dd-a42a018b7353', '先声药业 Simcere 实习', 'a37a0784-884c-4932-a568-cf6d42b8b22c', '先声药业 Simcere'),
  ('7c51aa74-a813-4256-959f-1699130e9a67', '先声药业 Simcere 校招', 'a37a0784-884c-4932-a568-cf6d42b8b22c', '先声药业 Simcere'),
  ('63b7d6b5-13f1-48db-85c1-6a0c2bbecd1c', '光启技术 校招', '791048a7-90ad-472c-9201-a2650919cdf7', '光启技术'),
  ('94c5ab2b-f696-4505-bf3c-f942415b8030', '公牛集团 GONGNIU', '9243ea39-14e1-47ea-8202-6b6c32b4062e', '公牛集团'),
  ('9eb7e2c4-db33-4e32-95a8-a7ab1e82e423', '华夏银行 HXB 校招', 'ab3aae57-7b4e-4889-9c85-9d439a78a98e', '华夏银行 HXB'),
  ('8950523e-5e07-46c8-816f-533829685a61', '华润三九 999', '0a9c520f-4492-4984-a859-a4fa743251ce', '华润三九'),
  ('26f6a8f7-7eb0-4152-a959-e17974e0245b', '华润三九 999 实习', '0a9c520f-4492-4984-a859-a4fa743251ce', '华润三九'),
  ('6e1adddc-107f-4c25-a4e0-6fdc3a0752bf', '华润三九 999 校招', '0a9c520f-4492-4984-a859-a4fa743251ce', '华润三九'),
  ('cf678f5d-90ac-4131-a28d-4cd9c2facc43', '华润三九医药股份有限公司', '0a9c520f-4492-4984-a859-a4fa743251ce', '华润三九'),
  ('72b65672-dec6-4d3e-b99d-433979e92a63', '华润电力 CR Power 校招', 'da906adc-ed5c-4bee-9ccd-04a6e52eb16b', '华润电力 CR Power'),
  ('784cbb91-5308-45ba-b450-9b7123fbd8d5', '卓胜微 Maxscend', 'b3152e4a-e6fe-4d89-9cbd-8238c7ee3997', '卓胜微'),
  ('77acb406-7394-461b-99a1-51ec1e78c516', '卡夫亨氏（中国）食品有限公司', 'dae1b0da-6e76-4c11-9610-87b652080544', '卡夫亨氏 Kraft Heinz'),
  ('9aef5a3c-5cd4-495c-88d4-a1cdc7cdd7b9', '河南双汇投资发展', '17c33955-6c39-4d1d-9c35-1c14cb200705', '双汇'),
  ('68ab4a45-e944-4c4e-b3b0-e3511fcace71', '同盾科技 Tongdun', '67e71511-6ad8-4546-8581-b075eb583f99', '同盾科技'),
  ('ca3c3085-6804-47df-a80c-5ecd3ffb7991', '名创优品 MINISO', '3e2ca74e-28ec-4d0c-9872-77df49f10b1a', '名创优品'),
  ('31618499-4c75-42c7-b4e8-dab6846e9194', '和睦家医疗 实习', 'ea7723ea-b4f9-47f0-8a66-7498907687d1', '和睦家医疗'),
  ('ea53a109-b5dc-4cdf-af24-2f7e40f8ecc1', '和睦家医疗 校招', 'ea7723ea-b4f9-47f0-8a66-7498907687d1', '和睦家医疗'),
  ('d4114c70-f851-45d6-8cd8-fc7b87cb55b9', '哔哩哔哩 bilibili', '49b71a24-16ea-4bb9-ac07-d14c221093b1', '哔哩哔哩'),
  ('34e52467-a26a-40d2-ab17-60d48b3480c3', '商汤科技 SenseTime', '4ff56adb-33db-4755-bd03-406732b5e71d', '商汤'),
  ('2697b488-5697-4141-b2a5-4fb35f05059a', '国投证券 SDIC 实习', '63c436f4-a904-4762-aaf4-f045f57bca7a', '国投证券 SDIC'),
  ('81af8633-1d10-4bfa-89b9-e8a1031e2376', '国投证券 SDIC 校招', '63c436f4-a904-4762-aaf4-f045f57bca7a', '国投证券 SDIC'),
  ('90ac145a-f616-4029-9d57-9301093477ff', '国投证券股份有限公司（国投集团）', '63c436f4-a904-4762-aaf4-f045f57bca7a', '国投证券 SDIC'),
  ('36739cee-7ec7-4b1c-a03e-6150982f894b', '地平线 Horizon Robotics', '918334e9-1094-4413-b4e6-68fcdfc54d1f', '地平线'),
  ('dacfc71a-5d7d-40bd-aa07-af91ce77f261', '地平线 Horizon Robotics 实习', '918334e9-1094-4413-b4e6-68fcdfc54d1f', '地平线'),
  ('481c2490-506b-4abc-935d-404bb0ee7af8', '地平线 Horizon Robotics 校招', '918334e9-1094-4413-b4e6-68fcdfc54d1f', '地平线'),
  ('719a0712-86c2-404c-b959-9eaeae9f07e3', 'Shell', 'fc09cc26-8928-477c-9b34-9ceaa0476755', '壳牌'),
  ('cea4c8f9-5ba4-4a5c-9276-2d6a470eebf9', '复星医药 Fosun Pharma', '0d9729e3-d4c6-4bc4-90ff-bfb037d06110', '复星医药'),
  ('93637124-2810-4165-a2e9-595034e17f8b', 'Duolingo', '36fd875a-28ec-48a6-9d8e-b3a5625977ce', '多邻国'),
  ('7ad910ce-6ec2-45a5-bdab-021eb2c5a3d9', '多邻国 Duolingo', '36fd875a-28ec-48a6-9d8e-b3a5625977ce', '多邻国'),
  ('4970986a-0b33-420b-9f94-926b33d45829', '浙江大华技术', 'a143605c-b799-4413-b86c-614fa72d6753', '大华股份 Dahua'),
  ('85767744-bbe8-4511-99ba-bd31d5c87b71', '大疆创新', '67b66876-0b93-4180-817d-9b2867bd0cf2', '大疆'),
  ('f8f8b307-19b6-4f1b-9eda-d8877d1cabf8', '天合光能 Trina', 'd6b7cf96-5077-4d22-84c0-d9f9fabcd042', '天合光能'),
  ('2ffee0fd-2e16-4ccd-b652-30ca1185e206', '奇安信 QiAnXin', '30dfd818-d87f-4de9-b806-0ac1f71ab8cd', '奇安信'),
  ('5779954a-9984-49b8-8586-3a1ef3399a6c', '奇瑞汽车 CHERY', 'e3a53711-822f-4d58-bccc-d8024bc1caa0', '奇瑞汽车'),
  ('37d28a32-98a2-4bd5-9837-21944a5b19af', '好未来（学而思）', '6f3a7626-c19b-48f7-bb66-495fdb413645', '好未来'),
  ('8a04c1e9-bd2c-488a-88eb-d3dcebeed9c3', '抖音', 'edea18ff-f183-4d7b-a3b2-205f3ae9bbfa', '字节跳动'),
  ('7ec749a0-7736-4163-9854-5bcdc7e3da83', '宁德新能源 ATL', '1d8af311-9cf2-4270-b5d8-f961f08cb752', '宁德新能源'),
  ('28a91181-e8d1-436b-9524-8d9bd2e79418', '宁德新能源 ATL 实习', '1d8af311-9cf2-4270-b5d8-f961f08cb752', '宁德新能源'),
  ('d732a884-a78c-434b-9d17-46c37d687448', '宁德新能源 ATL 校招', '1d8af311-9cf2-4270-b5d8-f961f08cb752', '宁德新能源'),
  ('e10acd14-cae3-4cb9-949b-431a99dde30c', '宁德时代 CATL', '3551f336-0d8a-42c2-8b66-9dbdd9c62669', '宁德时代'),
  ('ca18c0d9-1495-40df-ae7e-8fb9ee821620', '安踏 ANTA', '28c8544f-5d5f-4c91-a10a-68cae8fd09b6', '安踏体育用品集团'),
  ('7912073f-bc7e-471c-9303-33e7bd0b237f', '完美世界 Perfect World', 'f2215a39-6f83-4ab5-bf20-10c0ae05ebd2', '完美世界'),
  ('6d31cd73-af4f-4ca3-a02b-d82265fde155', '完美世界 校招', 'f2215a39-6f83-4ab5-bf20-10c0ae05ebd2', '完美世界'),
  ('91800de0-25cf-42e4-a2fb-5139a927686b', '小马智行 Pony.ai', '7189e261-be02-4aec-86b9-98701e264b28', '小马智行'),
  ('ddb9b859-3884-4397-8321-ec4aa27eddfc', '岚图汽车科技有限公司', '47de8065-7239-4663-b350-f2c844b6d495', '岚图汽车'),
  ('31d55744-261c-4df3-afe0-b6d1dc58cd6c', '巨人网络 Giant', 'd0a1867c-9c3e-4a8a-8a18-03b3674c4b2f', '巨人网络'),
  ('bfae4fd0-5a71-4834-8c2d-4c4d07110ae6', '广发证券 GF', 'dc50b76b-80dd-42fa-ac1c-4b72e5494b52', '广发证券'),
  ('27339b49-9f9e-4f65-888a-40bf9271dee2', '广发证券 GF 实习', 'dc50b76b-80dd-42fa-ac1c-4b72e5494b52', '广发证券'),
  ('7cf18832-88da-4418-9402-13e82f67db73', '广发证券 GF 校招', 'dc50b76b-80dd-42fa-ac1c-4b72e5494b52', '广发证券'),
  ('849fcc24-d866-429b-9e09-3aec5a0fa4ec', '广联达 Glodon', '3a8683f8-da09-4a56-82e0-31adf48271b3', '广联达'),
  ('599df3e9-ee22-40ea-b716-80bac86ee3d1', '广西柳工 LiuGong 校招', '06cbdc3f-f3b0-4dac-bca8-de1165576ccc', '广西柳工 LiuGong'),
  ('71396c46-28ef-4ca8-a90b-fdd475d93b5f', '度小满金融科技（北京）有限公司', 'c5b7e888-a3b4-49ee-a920-282ed87129c4', '度小满'),
  ('10dd9e93-a9b0-4217-98cc-222433a66872', '开源证券 Kysec 实习', 'bbb83164-7720-4667-980d-56ad10f72d24', '开源证券 Kysec'),
  ('b31750aa-0827-4e57-9859-6b68b0708dab', '开源证券 Kysec 校招', 'bbb83164-7720-4667-980d-56ad10f72d24', '开源证券 Kysec'),
  ('d62cda2f-6acf-4999-92ff-1f346d57e14d', '得物 POIZON', '3bb668e0-fc10-439b-9212-0532ed4715e6', '得物'),
  ('c713a8c7-376a-4fe1-b56a-d8195f0d1f29', '微众银行 WeBank', '532cf9ab-d044-481c-b887-7beb2c4b9c0c', '微众银行'),
  ('8e88b063-1cae-4e49-af40-532841445658', '深圳前海微众银行', '532cf9ab-d044-481c-b887-7beb2c4b9c0c', '微众银行'),
  ('db68aa95-edc0-43ce-9215-71174c8cfae4', '快手 Kuaishou', '4a44e91d-f766-465b-822b-001e2add122c', '快手'),
  ('af3fe0f8-a114-4ef2-a45e-ca7f266a34f9', '快看世界', 'a9205c20-7c71-4652-bb06-4bfa3c4d3bed', '快看漫画'),
  ('8ad0f73d-429d-417d-9b16-d0e7b49460cc', '江苏恒瑞医药', '98bd366f-2f0e-49db-b226-c2cbf184f6ca', '恒瑞医药'),
  ('e5a19619-d842-462e-ae80-b161b38eefc6', '招商局集团 CMHK', 'f118806c-9720-46ed-bc69-e031c766a5d4', '招商局集团'),
  ('923cc40f-15e9-43fb-a47f-00471560bbfb', '招商证券 CMS', '8fc6f7d5-bed8-4956-b136-d04bd5c9a583', '招商证券'),
  ('62abe3a3-f49d-42ac-ab9f-8eceeb5b484b', '招商证券 CMS 实习', '8fc6f7d5-bed8-4956-b136-d04bd5c9a583', '招商证券'),
  ('8f9ec538-dcdd-4a19-86bd-9a68d92933d8', '招商证券 CMS 校招', '8fc6f7d5-bed8-4956-b136-d04bd5c9a583', '招商证券'),
  ('e5671d45-ec58-455b-a093-7ddfb5a52dd3', '拼多多 Pinduoduo', '47f387cd-df9a-4a04-ae34-860ebb8baff4', '拼多多'),
  ('2fceafd2-2afa-4c1b-8a0f-bbc91c34077e', '携程集团 Trip.com', '089b6aef-c8b1-4ad3-8bd7-710ee6612310', '携程'),
  ('b7244396-76fb-4beb-8bf2-6fb957ed15f1', '文远知行 WeRide', 'd49f7e11-9abc-43f7-9bec-e4c39befb823', '文远知行'),
  ('caf0350d-1182-40f4-a78b-3b9fa3885c2c', '斗鱼直播 Douyu', '55d66975-d0e6-4a3c-9c02-4ae871fe1837', '斗鱼'),
  ('bf68adaf-2abf-4bcb-a690-4be70349d14d', '新东方 New Oriental', '0eab2263-859f-4f1b-8a37-0e30aaef8bcd', '新东方'),
  ('26ca2b57-3eb4-4a7d-bd18-02a3a789405b', '新城控股 Seazen 实习', '98bbc75e-e877-465d-abdd-db31b251d87c', '新城控股 Seazen'),
  ('700f81a5-f340-481b-8653-0ade4c6e8cbd', '新城控股 Seazen 校招', '98bbc75e-e877-465d-abdd-db31b251d87c', '新城控股 Seazen'),
  ('1d743870-cfe1-42bb-8300-6b7f7d754bd1', '新疆特变电工集团 实习', 'ba2c2aa7-4643-48f9-b9f2-c8a41f872918', '新疆特变电工集团'),
  ('3899af95-8155-4a7f-9eec-45d9a5944c22', '新疆特变电工集团 校招', 'ba2c2aa7-4643-48f9-b9f2-c8a41f872918', '新疆特变电工集团'),
  ('fff545f9-dd11-44e4-8021-59c9f7d6741c', '旭辉控股（集团）有限公司', '544c80aa-db9c-4ba8-b2f9-7c2ae86bd636', '旭辉控股集团有限公司'),
  ('cdb66d82-2a05-4202-8821-dfdc52046fc9', '易方达基金 实习', '5a6f2299-287a-4979-800c-1962d3758932', '易方达基金'),
  ('d45805ab-8051-4141-a3d5-7006e74dc3d4', '易方达基金 校招', '5a6f2299-287a-4979-800c-1962d3758932', '易方达基金'),
  ('259dcfc0-7ba4-4e3d-982d-28d2cbff8371', '曙光信息产业 校招', '506bc419-251f-4e2b-83e5-d1574b7dc155', '曙光信息产业'),
  ('f8384b21-f655-47dc-be84-83abaff78da5', '李宁 LI-NING', '65e7db72-09b9-4389-b7de-f76f79c424ff', '李宁'),
  ('ae911a4b-3932-4172-9452-bd945c2259d3', '松下 Panasonic', '8eec3ce1-147b-4882-b983-ee587bc422d1', '松下'),
  ('e9198db6-a654-45b9-96ad-42a4248eb98c', '极兔速递', '8ee2e32e-1d5c-4d70-aa1c-2d44cd0a4823', '极兔'),
  ('0c93c101-d2dc-460d-86b2-fcd054705e10', '极米科技 XGIMI', '2692eab8-1212-421b-8c0e-94eeeea5b300', '极米科技'),
  ('30f5c7c1-02d1-49c5-a9ce-5a1ba3a90fd2', '欣旺达电子', 'd345fd51-7064-4a3b-a246-a67f542c4f5f', '欣旺达'),
  ('fe0f5f61-e379-49a5-9ce5-8eb5ef3401ac', '歌尔股份 GoerTek 实习', '24107a40-c7d1-4426-8df6-c96d7fce9a16', '歌尔股份 GoerTek'),
  ('618d20c3-8c02-48e8-a1ce-f3e365ebbb52', '歌尔股份 GoerTek 校招', '24107a40-c7d1-4426-8df6-c96d7fce9a16', '歌尔股份 GoerTek'),
  ('f4b6087f-be20-46de-abc0-65fa45415cf4', '比亚迪 BYD', '3f212d7d-c079-4e34-a2d0-6dcc287ab89a', '比亚迪'),
  ('88f99738-52b2-4f1a-aa52-4f831a0a643c', '汇川技术 Inovance', '12231003-f4a5-4943-bb54-51cc51f03b14', '汇川技术'),
  ('c60fd1a2-6fd6-4eff-9c05-007c648349ab', '深圳市汇川技术', '12231003-f4a5-4943-bb54-51cc51f03b14', '汇川技术'),
  ('8273d9f4-31e6-42f3-b08f-da2cc113a56a', '泡泡玛特 POP MART', '487ae66a-6328-4481-969f-14212678747c', '泡泡玛特'),
  ('cd8719c6-ee4f-456b-b1d9-75e0af306c99', '吉利', 'cd36a02d-4c65-4a80-b58c-57ee40ab8385', '浙江吉利控股集团'),
  ('9233cfc8-4216-4750-94fd-c16c39f2d914', '海信集团', 'bb6508b0-3881-4cd4-8012-c9766cb52d92', '海信'),
  ('e9f19010-6096-415f-94a2-a5483a3bde34', '海天集团 校招', '8bd9a20a-75d1-4c15-b178-d5fdaf69c73e', '海天集团'),
  ('83c997a9-66d0-4eb9-ba00-90c38fff75ac', '传音控股 Transsion', '9a26046b-7189-4256-8f5b-d53ccf9f4e3b', '深圳传音控股'),
  ('b3a9ba5b-1a98-45ed-b7b6-7bd82ba280e6', '满帮集团 Manbang', '00a39cd4-ddf5-4fef-9257-77ac70f648fb', '满帮'),
  ('b7e58801-3386-4296-8093-1d2dbf19ef0b', '滴滴出行 DiDi', '64796e9f-8df0-449c-89bb-9216f14ea598', '滴滴'),
  ('066bc717-b953-493f-8fb6-456a6ba8d07a', '北京爱奇艺科技', '4975d928-31f1-4a06-9742-a36cdf929776', '爱奇艺'),
  ('fd767aec-12a9-49a7-b69f-d177a91da0f6', '爱奇艺股份有限公司', '4975d928-31f1-4a06-9742-a36cdf929776', '爱奇艺'),
  ('f3298de5-ee5c-47d1-83a6-cce021f182ec', '特斯拉中国 Tesla', 'd3519e3b-6529-402f-ac33-fcca1fcd8cce', '特斯拉'),
  ('f9e3f4d6-2754-4a70-8119-cf4ebcad14fd', '猫眼娱乐', '9983846f-0cf0-4d07-afef-4ffd1d52f409', '猫眼'),
  ('fdd5fb1f-6f19-4f9d-ba6e-a43535454985', '猿辅导 Yuanfudao', '4f2621e4-5c66-4bdc-8fa7-4b08957b2df2', '猿辅导'),
  ('0f522ea1-d6b5-4187-9cd3-3d7d04ebe6e9', '理想汽车 Li Auto', '0580d1b7-61ab-47de-a9fe-2378383e43c8', '理想汽车'),
  ('8e364353-92f4-464c-8f72-68e4bb1db00c', '宁波申洲针织', 'c177d741-743b-4507-9df3-3f9ad52fdec4', '申洲国际 Shenzhou'),
  ('4b5cfb03-8686-4629-b9f4-92dee791264c', '申通快递', '67e98ac7-1a02-42b5-a820-179afa6f0f9e', '申通'),
  ('cc799b2f-05cf-4993-97f2-25bf5f18da62', '知乎 Zhihu', '5a2ddec5-ccdd-4ea4-86a7-b2c272e0ccb3', '知乎'),
  ('878e1d63-ed6a-479e-b439-cbc15f53b9ae', '第四范式 4Paradigm', 'ad10f360-7b5e-4773-a56d-77f8e7ef70dd', '第四范式'),
  ('db602f34-75d0-4709-9a77-5acd46f971d9', '米哈游 miHoYo', '96b989a7-f17c-455c-9cab-3d3f29f65da2', '米哈游'),
  ('fb148b0e-5a0b-4c6f-920e-4ebbe5a8475a', '美团 Meituan', '9eb53fe7-6681-45c8-8b36-f8963357e8f3', '美团'),
  ('9acaeacf-1d0a-4f62-969c-c4593bffbb3d', '联想 Lenovo', '479d0fd8-3d93-4a8c-8d03-6d79ee83647b', '联想'),
  ('7620b1a0-ccfd-4ab5-a012-22324bc4b8cf', '腾讯音乐 TME', '14585305-96c6-4fbe-bdf2-315dd7642a44', '腾讯音乐'),
  ('dc46577a-3b32-45a7-923d-2bc0a4f7d909', '苏州凌志软件 校招', 'daaa086f-1538-4c37-83f0-02905e0cf37a', '苏州凌志软件'),
  ('d45dbcd5-43d3-49d6-97d7-0782aca26788', '荣耀 Honor', '9e1b260b-5a06-4138-a91b-d01ab796ea40', '荣耀'),
  ('8f201270-a825-4439-af3c-c68e33a376a5', '荣耀 Honor 实习', '9e1b260b-5a06-4138-a91b-d01ab796ea40', '荣耀'),
  ('9b1027c2-4b19-4dc8-803f-3913e3352d04', '药明康德 WuXi AppTec', '3a429aec-acf4-4e3d-a516-e21d734ed52c', '药明康德'),
  ('a529b98e-560e-49d7-ae0d-9acca889d1e1', '内蒙古蒙牛乳业（集团）股份有限公司（中粮集团）', 'd7d50441-a069-4fd1-8500-43b2f9334de8', '蒙牛'),
  ('464a38e3-ea1a-4762-b652-81d53a40adc1', '蒙牛乳业 MENGNIU', 'd7d50441-a069-4fd1-8500-43b2f9334de8', '蒙牛'),
  ('7e1a8261-c82e-4e20-a1c1-e13af457e190', '北京蓝色光标数据科技', '69cffd17-ace1-4931-83ee-6f62b5442da2', '蓝色光标'),
  ('1cb958f7-47b2-4b19-8bf1-858b75df5b52', '虎牙直播 Huya', 'fd91e2a1-4ab1-4c3e-aca7-32ffbe16fd6d', '虎牙 Huya'),
  ('a05c454c-686c-4285-bf78-dfb635bbe68a', '贝壳 Beike', 'e13cd503-be83-4262-a1ed-694f794cb9bb', '贝壳'),
  ('c4db5d5e-4330-4bc9-89d8-46ce079ee287', '贝壳找房', 'e13cd503-be83-4262-a1ed-694f794cb9bb', '贝壳'),
  ('a1ad63bb-ec71-4007-9f4b-73158a855a31', '货拉拉 Lalamove', '2f245bb0-8ed2-4c8b-a9bf-b68563fcc212', '货拉拉'),
  ('b86120c8-5ce6-4d5e-8b2b-a566e87ba099', '货拉拉科技', '2f245bb0-8ed2-4c8b-a9bf-b68563fcc212', '货拉拉'),
  ('74b52ba4-96f5-4d5f-9ba2-3dafaee69370', '迈瑞医疗 Mindray', '0a6e1221-29ec-44f5-8eee-18bbb09157c4', '迈瑞医疗'),
  ('13599f15-c185-4188-930d-aef297a54ea7', '迪卡侬中国 Decathlon 实习', '4a681cf7-3358-4bd5-9829-e6a712d16cc6', '迪卡侬中国 Decathlon'),
  ('9a7937c5-434b-4a1a-821d-8902badf6dc7', '迪卡侬中国 Decathlon 校招', '4a681cf7-3358-4bd5-9829-e6a712d16cc6', '迪卡侬中国 Decathlon'),
  ('ba2e7df2-54dc-4219-9263-336ac97cbd35', '通威股份 Tongwei', '782cc02e-0cd3-4105-9f65-980542337b01', '通威股份'),
  ('e25dc05c-1945-4e09-9ab9-1eca18340187', '金山办公 WPS', '14167ffd-5832-490e-879a-a23fd2ba7e27', '金山办公'),
  ('1ad5a7ac-c8ed-4f7b-822b-4cab28422625', '锐捷网络 Ruijie', 'bcc6bced-c26a-4efe-babb-e5a7c8ff3579', '锐捷网络'),
  ('52176f50-e3af-495e-a88c-f1d1d99a59de', '长安汽车 Changan', 'c31480a6-ba48-4678-96c9-52e89ab67429', '长安汽车'),
  ('25f13d5b-82df-475c-93e7-cf8a113f75ec', '阳光电源 Sungrow', '45649cb0-c1b4-4244-a925-26d018cb94bd', '阳光电源'),
  ('21395529-da75-4bca-9482-781f70ef6e4a', '阿里巴巴控股集团', 'd2122346-f903-432f-ab75-e30df989cbfe', '阿里巴巴'),
  ('dd79dcab-dfd7-4b08-abba-6862c79fdfd6', '隆基绿能 LONGi', 'e935f9ad-72b3-444e-86ec-f138d70b3694', '隆基绿能'),
  ('ebbf2c65-bdd4-4493-80e0-878fa0cb7f72', '隆基绿能 LONGi 校招', 'e935f9ad-72b3-444e-86ec-f138d70b3694', '隆基绿能'),
  ('19331b56-65a6-4a6b-b243-598ba8dd511d', '雪球 Xueqiu', 'ffd2351b-9622-4f92-ac77-7715fba99f53', '雪球'),
  ('fb78c56a-3201-4a5c-9caf-5e54b7b331a9', '顺丰 SF Express', '8fa03e33-29b0-407c-83ce-a9084dc005f9', '顺丰'),
  ('7c7c00a8-2e59-47e6-afab-b1103935a199', '领益智造 Lingyi 实习', '7727e3b4-6724-44aa-acf0-533f0f601f48', '领益智造 Lingyi'),
  ('4bb02e5e-461d-44b6-920a-5331ec20d003', '领益智造 Lingyi 校招', '7727e3b4-6724-44aa-acf0-533f0f601f48', '领益智造 Lingyi'),
  ('f3b4ea46-0c7b-4097-a6da-fc63eb01bd5f', '麦当劳（中国）有限公司', '47b51642-273a-40a0-82aa-1e79e140f5c7', '麦当劳');

create temp table _bracket_drop (id uuid primary key, company text not null) on commit drop;
insert into _bracket_drop (id, company) values
  ('4bd52aa8-fec0-4787-8d32-506744123318', '中冶建筑研究总院有限公司（北汽集团）'),
  ('b72c4ac9-7bc1-4903-998b-46bc2f1c461b', '中国建筑第四工程局有限公司深圳分公司（中国电建集团）'),
  ('5f6ac3d3-5c87-4a6a-a008-6c45b947c86f', '中国联合网络通信有限公司天津市分公司（中国海油）'),
  ('bb99958a-8ac1-446d-88e7-80e98a16e3e5', '中建四局华南建设有限公司（中国建研院）'),
  ('42b87117-6160-4d17-a852-86345046808b', '中建四局建设发展有限公司'),
  ('88e915ed-cb90-4f61-a836-b5f86af18ec2', '中建四局建设发展有限公司（中国建研院）'),
  ('8b0f22b7-114e-42d0-b0cb-fd1b4ace4632', '中建安装集团有限公司华北分公司'),
  ('57f0fbcf-668f-4bad-8778-91927d79bd09', '中建电子商务有限责任公司'),
  ('f7d73a42-5087-4594-9726-cd72414d3c37', '中能建建筑集团有限公司（中国电建集团）'),
  ('8474c110-939a-4559-ba85-9ef5107ab844', '南京晨光集团有限责任公司（中国海油）'),
  ('ac37e28c-079d-4633-a4c2-ae363caa4421', '广西水利电力建设集团有限公司（中国电建集团）'),
  ('c075aef5-e898-42d2-b68e-28c2424b0915', '易普力股份有限公司（中国有色）'),
  ('a6de0ee8-1d07-4f9e-a7ee-f234cbd38111', '易普力股份有限公司（中粮集团）'),
  ('f53f9de3-ca56-4d16-aefe-b1be16943add', '温氏食品集团股份有限公司（中国电建集团）'),
  ('f2c943d1-3d90-443a-941d-56c69f920dbe', '电力规划总院有限公司（电力规划设计总院）（中国电建集团）');

create temp table _alias_remove (id uuid not null, company text not null, alias text not null) on commit drop;
insert into _alias_remove (id, company, alias) values
  ('5ff4a84c-586c-47f7-97fa-82f9323cd154', '海尔智家', '海尔'),
  ('d2122346-f903-432f-ab75-e30df989cbfe', '阿里巴巴', '蚂蚁'),
  ('e04b3c6c-724d-4550-b7ee-64cdf3d16577', '深度求索', '幻方'),
  ('e3761411-1a93-49f5-a34b-f5420d693a96', '三一重工', '三一');

-- 业务线主体的身份键：与 crawler/bu_extract.normalize_bu 同口径（NFKC、去首尾成对的包裹符、空白折叠、不分大小写）。
create function pg_temp.bu_key(t text) returns text language sql immutable as $fn$
  select lower(regexp_replace(btrim(
    regexp_replace(btrim(
      regexp_replace(btrim(normalize(coalesce(t, ''), NFKC)), '^[【】\[\]《》](.*)[【】\[\]《》]$', '\1')
    ), '^[【】\[\]《》](.*)[【】\[\]《》]$', '\1')
  ), '\s+', ' ', 'g'))
$fn$;

-- ── 0) 现状必须与清单一致，否则整体回滚 ───────────────────────────────────
do $$
declare n int;
begin
  select count(*) into n from _merge m
    left join company_profiles p on p.id = m.loser_id and p.company = m.loser_company where p.id is null;
  if n > 0 then raise exception '待合并的画像有 % 个已不存在或已改名', n; end if;

  select count(*) into n from (select distinct keep_id, keep_company from _merge) m
    left join company_profiles p on p.id = m.keep_id and p.company = m.keep_company where p.id is null;
  if n > 0 then raise exception '要留下的画像有 % 个已不存在或已改名', n; end if;

  select count(*) into n from _merge a join _merge b on a.keep_id = b.loser_id;
  if n > 0 then raise exception '清单自相矛盾：% 个画像既要留又要删', n; end if;

  select count(*) into n from _bracket_drop b
    left join company_profiles p on p.id = b.id and p.company = b.company where p.id is null;
  if n > 0 then raise exception '国聘括号残留有 % 个已不存在或已改名', n; end if;

  -- 括号残留是「直接删」：名下一旦有说法 / 人工 / 官方事实 / 校招周期，就不是空壳了，不许删。
  select count(*) into n from insight_items i join _bracket_drop b on b.id = i.company_id where i.origin <> 'derived';
  if n > 0 then raise exception '国聘括号残留名下有 % 条非派生洞察，不能直接删', n; end if;
  select count(*) into n from recruitment_cycle_observations c join _bracket_drop b on b.id = c.company_id;
  if n > 0 then raise exception '国聘括号残留名下有 % 条校招周期，不能直接删', n; end if;

  select count(*) into n from _alias_remove r
    left join company_profiles p on p.id = r.id and p.company = r.company and r.alias = any(coalesce(p.aliases, '{}'))
    where p.id is null;
  if n > 0 then raise exception '要去掉的别名有 % 个已不在那个画像上', n; end if;

  -- 说法 / 人工 / 官方事实都该是公司级（subject_id 为空）；不是的话改挂逻辑要重想。
  select count(*) into n from insight_items i join _merge m on m.loser_id = i.company_id
    where i.origin <> 'derived' and i.subject_id is not null;
  if n > 0 then raise exception '待合并画像名下有 % 条非派生洞察挂在业务线主体上', n; end if;
end $$;

create temp table _affected on commit drop as
  select loser_id as id from _merge union select keep_id from _merge
  union select id from _bracket_drop union select id from _alias_remove;

-- ── 1) 留底（archive 模式不在接口暴露的模式里）─────────────────────────────
create schema if not exists archive;
revoke all on schema archive from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on schema archive from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on schema archive from authenticated';
  end if;
end $$;
create table archive.merge_20261011_pairs as select * from _merge;
create table archive.merge_20261011_company_profiles as
  select p.* from company_profiles p where p.id in (select id from _affected);
create table archive.merge_20261011_insight_subjects as
  select s.* from insight_subjects s where s.company_id in (select id from _affected);
create table archive.merge_20261011_insight_items as
  select i.* from insight_items i where i.company_id in (select id from _affected);
create table archive.merge_20261011_insight_item_sources as
  select x.* from insight_item_sources x join insight_items i on i.id = x.item_id
  where i.company_id in (select id from _affected);
create table archive.merge_20261011_insight_subject_daily as
  select d.* from insight_subject_daily d join insight_subjects s on s.id = d.subject_id
  where s.company_id in (select id from _affected);
create table archive.merge_20261011_recruitment_cycle_observations as
  select c.* from recruitment_cycle_observations c where c.company_id in (select id from _affected);

-- ── 2) 洞察条目 ────────────────────────────────────────────────────────────
-- 2a 派生数据：待删画像名下的全部删。它们每晚由 bu_signals 按当时的归属重算，合并后归属变了，留着就是旧口径。
delete from insight_items i using _merge m where i.company_id = m.loser_id and i.origin = 'derived';

-- 2b 说法：每组只留「在展说法最多的那个成员」的，其余成员的在展说法改成退役留档
--    （28 组里两个以上成员各有在展说法，全留会让同一张卡上同一个话题出现两条）。并列时优先留下的画像。
create temp table _members on commit drop as
  select k.keep_id as gid, k.keep_id as pid, 0 as is_loser from (select distinct keep_id from _merge) k
  union all
  select keep_id, loser_id, 1 from _merge;

with cnt as (
  select m.gid, m.pid, m.is_loser,
         count(i.id) filter (where i.origin = 'public_web' and i.status = 'active') as n
  from _members m left join insight_items i on i.company_id = m.pid
  group by m.gid, m.pid, m.is_loser
), top as (
  select distinct on (gid) gid, pid from cnt order by gid, n desc, is_loser, pid
)
update insight_items i set status = 'retired'
from _members m join top t on t.gid = m.gid
where i.company_id = m.pid and m.pid <> t.pid and i.origin = 'public_web' and i.status = 'active';

-- 2c 官方事实（百科 / 官方 / 年报）：留下的画像已有同来源同维度在展的，被并画像的那条退役，不然同一个事实出现两条。
update insight_items li set status = 'retired'
from _merge m
where li.company_id = m.loser_id and li.status = 'active'
  and li.origin in ('wikidata', 'official', 'official_filing')
  and exists (
    select 1 from insight_items ki
    where ki.company_id = m.keep_id and ki.status = 'active'
      and ki.origin = li.origin and ki.dimension = li.dimension
  );

-- 2d 同一组里两个被并画像带了同一个事实、而留下的那个没有：只留最新核实的一条在展。
with ranked as (
  select li.id,
         row_number() over (partition by m.keep_id, li.origin, li.dimension
                            order by li.last_verified_at desc nulls last, li.id) as rn
  from insight_items li join _merge m on m.loser_id = li.company_id
  where li.status = 'active' and li.origin in ('wikidata', 'official', 'official_filing')
)
update insight_items i set status = 'retired' from ranked r where r.id = i.id and r.rn > 1;

-- 2e 剩下的（说法、人工、官方事实，含已退役的留档）整体改挂到留下的画像。
update insight_items i set company_id = m.keep_id
from _merge m where i.company_id = m.loser_id;

-- ── 3) 主体 ────────────────────────────────────────────────────────────────
-- 3a 公司主体：留下的画像已有 → 被并画像的公司主体删；没有 → 把在招数最大的那个迁过去并改成留下的画像的正名
--    （不改名的话 bu_extract 下一轮按名字找不到它，会再插一个，同一个画像下出现两个公司主体）。
create temp table _company_subject on commit drop as
  select m.keep_id, m.keep_company, s.id as subject_id,
         exists (select 1 from insight_subjects k where k.company_id = m.keep_id and k.kind = 'company') as keep_has,
         row_number() over (partition by m.keep_id order by s.job_count desc, s.id) as rn
  from _merge m join insight_subjects s on s.company_id = m.loser_id and s.kind = 'company';

-- 3b 业务线主体：按身份键归并。留下的画像已有同键的 → 删；没有 → 同键里迁一个（在展优先、在招数大的优先），其余删。
create temp table _bu_subject on commit drop as
  select m.keep_id, s.id as subject_id, s.status, pg_temp.bu_key(s.name) as k,
         -- 业务线名就是留下的画像的正名（「岚图汽车科技有限公司」名下抽出过一条叫「岚图汽车」的业务线）：
         -- 到了留下的画像名下它等于公司本身，不是业务线，直接删；迁过去还会撞「同一画像下主体不重名」的唯一约束。
         pg_temp.bu_key(s.name) = pg_temp.bu_key(m.keep_company) as is_company_name,
         (select ks.id from insight_subjects ks
           where ks.company_id = m.keep_id and ks.kind = 'business_unit'
             and pg_temp.bu_key(ks.name) = pg_temp.bu_key(s.name)
           order by (ks.status = 'active') desc, ks.job_count desc, ks.id limit 1) as keep_subject_id,
         row_number() over (partition by m.keep_id, pg_temp.bu_key(s.name)
                            order by (s.status = 'active') desc, s.job_count desc, s.id) as rn
  from _merge m join insight_subjects s on s.company_id = m.loser_id and s.kind = 'business_unit';

-- 每个被并画像名下的主体怎么处理：move = 改挂；merge = 并入 target 后删；drop = 直接删。
create temp table _subject_plan on commit drop as
  select c.subject_id, c.keep_id,
         case when not c.keep_has and c.rn = 1 then 'move' else 'merge' end as action,
         case when not c.keep_has and c.rn = 1 then null
              when c.keep_has then (select k.id from insight_subjects k
                                     where k.company_id = c.keep_id and k.kind = 'company' order by k.id limit 1)
              else (select c2.subject_id from _company_subject c2 where c2.keep_id = c.keep_id and c2.rn = 1)
         end as target_id,
         c.keep_company as rename_to
  from _company_subject c
  union all
  select b.subject_id, b.keep_id,
         case when b.is_company_name then 'drop'
              when b.keep_subject_id is null and b.rn = 1 then 'move'
              else 'merge' end,
         case when b.is_company_name then null
              when b.keep_subject_id is not null then b.keep_subject_id
              when b.rn = 1 then null
              else (select b2.subject_id from _bu_subject b2
                     where b2.keep_id = b.keep_id and b2.k = b.k and b2.rn = 1)
         end,
         null
  from _bu_subject b;

-- 人工判过「这是噪声」的业务线（rejected）并进来时，结论跟着走。
update insight_subjects t set status = 'rejected'
from _subject_plan p join insight_subjects s on s.id = p.subject_id
where p.action = 'merge' and p.target_id = t.id and s.status = 'rejected' and t.status <> 'rejected';

-- 被并的那个还在展、它并入的那个却是已退役的（新疆特变电工集团的「衡变」）：并完应当在展，不能因为合并少一条业务线。
update insight_subjects t set status = 'active', job_count = greatest(t.job_count, s.job_count)
from _subject_plan p join insight_subjects s on s.id = p.subject_id
where p.action = 'merge' and p.target_id = t.id and s.status = 'active' and t.status = 'retired';

-- 3c 每日快照：被删主体的每日在招数按日加到它并入的主体上，趋势不断档。
--    例外：留下的画像别名里本来就有被并画像的正名（或反过来）——那边的每日数是 bu_signals 按「正名 + 别名」
--    取岗写的，已经把对方的岗算进去了（字节跳动 / 抖音、大疆 / 大疆创新），再加就是重复。
insert into insight_subject_daily (subject_id, day, active_count, new_30d)
select p.target_id, d.day, sum(d.active_count), sum(d.new_30d)
from _subject_plan p
join insight_subjects s on s.id = p.subject_id
join insight_subject_daily d on d.subject_id = p.subject_id
join company_profiles lp on lp.id = s.company_id
join company_profiles kp on kp.id = p.keep_id
where p.action = 'merge'
  and not (lp.company = any(coalesce(kp.aliases, '{}')) or kp.company = any(coalesce(lp.aliases, '{}')))
group by p.target_id, d.day
on conflict (subject_id, day) do update
  set active_count = insight_subject_daily.active_count + excluded.active_count,
      new_30d = case when insight_subject_daily.new_30d is null and excluded.new_30d is null then null
                     else coalesce(insight_subject_daily.new_30d, 0) + coalesce(excluded.new_30d, 0) end;

-- 3d 迁：改挂（公司主体同时改名）。
update insight_subjects s
set company_id = p.keep_id, name = coalesce(p.rename_to, s.name)
from _subject_plan p where p.subject_id = s.id and p.action = 'move';

-- 3e 删：并入别的主体的（每日快照已在 3c 加到目标上）和直接删的；它们的每日快照随之级联删。
delete from insight_subjects s using _subject_plan p where p.subject_id = s.id and p.action in ('merge', 'drop');

-- ── 4) 校招周期 / 用户投稿 ────────────────────────────────────────────────
update recruitment_cycle_observations c set company_id = m.keep_id from _merge m where c.company_id = m.loser_id;
update insight_submissions u set company_id = m.keep_id from _merge m where u.company_id = m.loser_id;

-- ── 5) 留下的画像：登记别名、补空着的事实列 ───────────────────────────────
with names as (
  select m.keep_id, m.loser_company as name from _merge m
  union
  select m.keep_id, btrim(a) from _merge m join company_profiles p on p.id = m.loser_id,
       unnest(coalesce(p.aliases, '{}')) as a
), add as (
  select n.keep_id, array_agg(n.name order by n.name) as names
  from names n join company_profiles k on k.id = n.keep_id
  where n.name <> '' and n.name <> k.company and not (n.name = any(coalesce(k.aliases, '{}')))
  group by n.keep_id
)
update company_profiles k set aliases = coalesce(k.aliases, '{}') || add.names
from add where add.keep_id = k.id;

-- 事实列留下的画像自己有就不动；空着的从被并画像里补（多个都有时取 id 最小的那个，结果确定）。
update company_profiles k set
  industry       = coalesce(k.industry,       f.industry),
  founded_year   = coalesce(k.founded_year,   f.founded_year),
  headcount_band = coalesce(k.headcount_band, f.headcount_band),
  funding_stage  = coalesce(k.funding_stage,  f.funding_stage),
  hq_location    = coalesce(k.hq_location,    f.hq_location),
  -- 留下的画像没跑过公开说法富化、而被并的跑过（说法已改挂过来）：沿用它的时间，别让这家公司马上再排一次队。
  t3_checked_at  = coalesce(k.t3_checked_at,  f.t3_checked_at)
from (
  select m.keep_id,
         (array_agg(p.industry       order by p.id) filter (where p.industry is not null))[1]       as industry,
         (array_agg(p.founded_year   order by p.id) filter (where p.founded_year is not null))[1]   as founded_year,
         (array_agg(p.headcount_band order by p.id) filter (where p.headcount_band is not null))[1] as headcount_band,
         (array_agg(p.funding_stage  order by p.id) filter (where p.funding_stage is not null))[1]  as funding_stage,
         (array_agg(p.hq_location    order by p.id) filter (where p.hq_location is not null))[1]    as hq_location,
         max(p.t3_checked_at) as t3_checked_at
  from _merge m join company_profiles p on p.id = m.loser_id group by m.keep_id
) f where f.keep_id = k.id;

-- ── 6) 删被并的画像（此时名下不该再有任何东西）───────────────────────────
do $$
declare n int;
begin
  select count(*) into n from insight_items i join _merge m on m.loser_id = i.company_id;
  if n > 0 then raise exception '被并画像名下还剩 % 条洞察没改挂', n; end if;
  select count(*) into n from insight_subjects s join _merge m on m.loser_id = s.company_id;
  if n > 0 then raise exception '被并画像名下还剩 % 个主体没处理', n; end if;
  select count(*) into n from recruitment_cycle_observations c join _merge m on m.loser_id = c.company_id;
  if n > 0 then raise exception '被并画像名下还剩 % 条校招周期没改挂', n; end if;
end $$;
delete from company_profiles p using _merge m where p.id = m.loser_id;

-- ── 7) 国聘括号残留：直接删（名下只有一个公司主体和派生数据，随画像级联删）──
delete from company_profiles p using _bracket_drop b where p.id = b.id;

-- ── 8) 撞到别家公司的别名：去掉 ───────────────────────────────────────────
update company_profiles p set aliases = array_remove(p.aliases, r.alias)
from _alias_remove r where r.id = p.id;

-- ── 9) 结果断言 ───────────────────────────────────────────────────────────
do $$
declare n int;
begin
  -- 一个画像只许有一个公司主体。
  select count(*) into n from (
    select company_id from insight_subjects where kind = 'company' group by company_id having count(*) > 1
  ) t;
  if n > 0 then raise exception '合并后有 % 个画像挂着两个以上公司主体', n; end if;

  -- 留下的画像名下，业务线主体不许有同键的两个（合并没并干净）。
  select count(*) into n from (
    select s.company_id, pg_temp.bu_key(s.name) from insight_subjects s
    where s.kind = 'business_unit' and s.company_id in (select keep_id from _merge)
    group by 1, 2 having count(*) > 1
  ) t;
  if n > 0 then raise exception '合并后留下的画像里有 % 组同名业务线主体', n; end if;

  -- 全库不许再有两个画像登记同一个名字（正名或别名）。与每日体检 insights.profile_same_name_pairs 同口径。
  with nm as (
    select id, btrim(company) as name from company_profiles
    union
    select p.id, btrim(a) from company_profiles p, unnest(coalesce(p.aliases, '{}')) as a where btrim(a) <> ''
  )
  select count(*) into n from (
    select a.id, b.id from nm a join nm b on a.name = b.name and a.id < b.id group by a.id, b.id
  ) t;
  if n > 0 then raise exception '合并后仍有 % 对画像登记了同一个名字', n; end if;
end $$;

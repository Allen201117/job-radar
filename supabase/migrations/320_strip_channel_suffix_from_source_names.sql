-- 320 — 源名去掉渠道后缀「 校招 / 实习」，并改正两条把页面里的岗位字样抄进公司名的源（创始人 2026-10-11 同意）
--
-- 调研与全集核验：docs/reviews/2026-10-11-source-name-channel-suffix.md
--
-- 现象：同一家公司的社招 / 校招 / 实习各一条源，公司名被写成「TCL」「TCL 校招」「TCL 实习」。岗位的公司名直接抄源名，
--   于是岗位卡、公司筛选、推荐理由里出现「TCL 校招」；必投匹配、洞察画像归属、/today 单公司上限都要各自处理这个后缀。
--   后缀还有两成是错的：带后缀名字下 11,246 个在招岗里 2,391 个逐岗分类是社招（北森一个租户的列表社招校招一起返回，
--   「中国交建 校招」名下 1,638 个是社招岗）。渠道本来就有 board 字段和逐岗分类，不该写进公司名。
-- 根因：53 条全是迁移里手写的（2026-06 探活批次 46 条 + 2026-09 的 228 / 259 / 260 共 7 条）；代码里没有任何地方拼后缀。
-- 另两条（迁移 219）：「神州信息—AI实习生」「豪迈集团—职能实习生」。门户页面标题自报「神州信息」「豪迈招聘」
--   （2026-10-11 curl 两个门户首页）；两个名字下 861 个在招岗里 754 个是社招。
--
-- 真库核验（2026-10-11，全集，只读）：
--   · 去后缀后撞 jobs 的 (company, title, location, jd_url) 唯一键 0 组；同一个归一岗位链接出现在两个名字下 0 组。
--   · 必投清单：55 个名字改名前后的模式命中集合、resolve_owner（国内 / 海外 / 并集）全部不变。
--   · 招聘类型：真实分类器对 11,246 + 861 行逐行算「改名前 / 改名后」，改判 0 行（正文按空算，是上界）。
--   · 用户关注（59 行）、目标公司（51 个）里没有带后缀的名字。
--
-- 本迁移做四件事：
--   ① sources.company 按 id + 旧名点名改（55 行），旧名记进 notes。
--   ② 三个正名带这些字样的画像跟着改名，旧名进别名（别名不清：改名后没有岗位再用到它们，留着无害，
--      且归属规则本来就不把末尾的渠道后缀算进公司名）。
--   ③ 两家公司的 logo 只挂在带后缀的名字下（本名那行是 not_found），按新名补一份，免得卡片先掉成首字母色块。
--   ④ 「亿纬锂能」社招源的性质标签补齐（原 unknown / 空；校招源一直标的是民营）。行业标签两条源各有说法、没有读者，不动。
-- 存量岗位的 company 不在这里改：香港库走 rename-job-company.yml 的批量模式
--   （crawler/company_renames/20261011_channel_suffix.json）。`company` 在 jobs_db._UPDATE_COLS 里，之后每轮重抓都按新名写。
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列，显式赋值整批迁移会回滚。
-- Idempotent：update 的 where 都带旧值；开头断言「每条 id 都在、名字是旧名或新名」，结尾断言「没有一条还叫旧名」。

create temp table _src_rename (id uuid primary key, old_name text not null, new_name text not null) on commit drop;
insert into _src_rename (id, old_name, new_name) values
  ('46f9c30a-f119-43a3-b3f7-88e5a73b8e90'::uuid, 'TCL 实习', 'TCL'),
  ('9e97601f-e371-4634-afe7-56f36d4c6ee9'::uuid, 'TCL 校招', 'TCL'),
  ('7f42ddb2-dcdc-4fbe-b2c6-0764d1adb097'::uuid, '万科企业 校招', '万科企业'),
  ('bc91d119-ed68-4544-825f-970bf69c13d8'::uuid, '东风汽车 DFMC 实习', '东风汽车 DFMC'),
  ('beb7d842-d767-4fc3-a976-d7014275d87a'::uuid, '东风汽车 DFMC 校招', '东风汽车 DFMC'),
  ('04591b01-4adc-48e2-a215-8c0a388a3fb4'::uuid, '中国中化 ChemChina 实习', '中国中化 ChemChina'),
  ('4ab75eeb-9e9d-4f28-8c80-72e1acfd1440'::uuid, '中国中化 ChemChina 校招', '中国中化 ChemChina'),
  ('a2a17f04-ed50-4aaf-afd2-8454168a5974'::uuid, '中国中化 ChemChina 校招', '中国中化 ChemChina'),
  ('f290c742-d702-44f6-a1ad-74a210fba4eb'::uuid, '中国交建 校招', '中国交建'),
  ('68e8d52a-14eb-4d22-9233-eda28fcfe730'::uuid, '中国人民保险 校招', '中国人民保险'),
  ('0bce1471-c5e3-41b5-bca7-b0bd0a602828'::uuid, '中国外运 校招', '中国外运'),
  ('6904d6c5-03e5-4abf-9666-5eadee9eaedd'::uuid, '中国物流集团 校招', '中国物流集团'),
  ('17a6d7ec-6b18-4e53-a1f9-6d0da6799bf0'::uuid, '云南白药 YNBY 实习', '云南白药 YNBY'),
  ('2f4bb7ba-aa18-44fd-bb68-1b83f93d5d1e'::uuid, '云南白药 YNBY 校招', '云南白药 YNBY'),
  ('0ac95ace-2ee4-48f3-a396-35131e88973e'::uuid, '云尖信息 实习', '云尖信息'),
  ('6092be4e-a8ff-47f6-908f-ab003df2e5a4'::uuid, '云尖信息 校招', '云尖信息'),
  ('3346fe9d-ca96-402b-9a7f-52de24937c0f'::uuid, '亿纬锂能 校招', '亿纬锂能'),
  ('ebabed52-16a8-41d3-8f62-6a60b5e3ea53'::uuid, '先声药业 Simcere 实习', '先声药业 Simcere'),
  ('5f6e9114-8dbf-4e19-95bb-da0293ea1293'::uuid, '先声药业 Simcere 校招', '先声药业 Simcere'),
  ('6eb41239-df65-44a6-8be0-36947b49bbf7'::uuid, '光启技术 校招', '光启技术'),
  ('bea2b2e9-5d29-485b-8bf4-94230f5dd21e'::uuid, '创维 Skyworth 校招', '创维 Skyworth'),
  ('4aa1e592-257f-4e6e-8bbd-59deb9faaa7c'::uuid, '华夏银行 HXB 校招', '华夏银行 HXB'),
  ('6130d99d-efa7-4218-9e29-339e90c4ff3b'::uuid, '华润三九 999 实习', '华润三九 999'),
  ('809ecee3-9c17-4565-97ed-97e01627c607'::uuid, '华润三九 999 校招', '华润三九 999'),
  ('c5259b4d-ffcd-4964-8b35-1ecf8b441633'::uuid, '华润电力 CR Power 校招', '华润电力 CR Power'),
  ('75a139e0-64bf-4b72-bea6-5ad9d81a200a'::uuid, '国投证券 SDIC 实习', '国投证券 SDIC'),
  ('2d9ecf94-b86b-44ac-a1bc-5f99c2324e36'::uuid, '国投证券 SDIC 校招', '国投证券 SDIC'),
  ('0f3698db-755a-4353-a85c-db0c4dcbc087'::uuid, '地平线 Horizon Robotics 实习', '地平线 Horizon Robotics'),
  ('b597fbee-fb90-4a3d-bb51-2985edf5ca1c'::uuid, '地平线 Horizon Robotics 校招', '地平线 Horizon Robotics'),
  ('bfc0263a-5ac5-431b-adb2-b79f086f64d2'::uuid, '宁德新能源 ATL 实习', '宁德新能源 ATL'),
  ('485edff7-65ba-4e56-bb40-1b417856cb8e'::uuid, '宁德新能源 ATL 校招', '宁德新能源 ATL'),
  ('5569bc76-4ed0-4a14-a7eb-a19979d5f3cf'::uuid, '完美世界 校招', '完美世界'),
  ('d9051377-c483-439d-b281-be42d5b41f38'::uuid, '广发证券 GF 实习', '广发证券 GF'),
  ('2585080a-7f72-451c-a4ba-0a2e637b0be9'::uuid, '广发证券 GF 校招', '广发证券 GF'),
  ('9a454eaa-3b86-4bfc-ae1a-1b16ca5eced5'::uuid, '广西柳工 LiuGong 校招', '广西柳工 LiuGong'),
  ('a18fd531-07f5-430a-8f2d-21d70e9d5163'::uuid, '开源证券 Kysec 实习', '开源证券 Kysec'),
  ('ad92802b-fdb2-4fe2-af10-e4b857fdcebd'::uuid, '开源证券 Kysec 校招', '开源证券 Kysec'),
  ('e398b116-19c3-4f8c-9e0e-9094646b8ba6'::uuid, '招商证券 CMS 实习', '招商证券 CMS'),
  ('abe2ce60-b0b8-463a-b96e-b93d12793b28'::uuid, '招商证券 CMS 校招', '招商证券 CMS'),
  ('1f74eb7a-a1ae-433d-b04c-8940fdd38845'::uuid, '新城控股 Seazen 实习', '新城控股 Seazen'),
  ('38f87e02-7ab5-4015-a507-b842b37214e1'::uuid, '新城控股 Seazen 校招', '新城控股 Seazen'),
  ('4f496bd8-3dcd-46bc-8421-1d0e4f9c09d8'::uuid, '新疆特变电工集团 实习', '新疆特变电工集团'),
  ('eeccc10b-0bd7-41f4-90f5-b970a1641ee1'::uuid, '新疆特变电工集团 校招', '新疆特变电工集团'),
  ('1ad53c17-3de5-4d81-9e1b-948477dc8fb2'::uuid, '易方达基金 实习', '易方达基金'),
  ('14e6ead5-77a2-4272-96f0-4f4aac297176'::uuid, '易方达基金 校招', '易方达基金'),
  ('d09cc558-423d-46cf-b30f-ad35aeb593db'::uuid, '曙光信息产业 校招', '曙光信息产业'),
  ('ba5f6ce2-7796-44c1-9e07-34d2b0d202e1'::uuid, '歌尔股份 GoerTek 实习', '歌尔股份 GoerTek'),
  ('6f9aa108-6f94-4e70-849e-b0c706cfa94a'::uuid, '歌尔股份 GoerTek 校招', '歌尔股份 GoerTek'),
  ('3540afa5-1885-425f-a506-4cd20c34e33e'::uuid, '海天集团 校招', '海天集团'),
  ('532b0552-5c82-4e58-9f7b-83758d38d203'::uuid, '神州信息—AI实习生', '神州信息'),
  ('ae381752-bfbe-4867-a9d4-5aec9fe4668e'::uuid, '荣耀 Honor 实习', '荣耀 Honor'),
  ('5e77da6e-49b0-40dc-8b40-e009a26e600d'::uuid, '豪迈集团—职能实习生', '豪迈集团'),
  ('0a56e8c2-c633-4729-9801-d8bc67987366'::uuid, '迪卡侬中国 Decathlon 实习', '迪卡侬中国 Decathlon'),
  ('1221ad45-3b1d-4ece-bdfc-8573f106f234'::uuid, '迪卡侬中国 Decathlon 校招', '迪卡侬中国 Decathlon'),
  ('fd1eb697-2be9-4065-a7d2-95650aabce1c'::uuid, '隆基绿能 LONGi 校招', '隆基绿能 LONGi');

do $$
declare
  missing int;
  drifted text;
begin
  select count(*) into missing from _src_rename r where not exists (select 1 from public.sources s where s.id = r.id);
  if missing > 0 then
    raise exception '320：清单里有 % 条源已不在 sources 表，现状与调研时不一致，先重拉清单', missing;
  end if;
  select string_agg(s.company, ' | ') into drifted
    from _src_rename r join public.sources s on s.id = r.id
   where s.company not in (r.old_name, r.new_name);
  if drifted is not null then
    raise exception '320：这些源的名字既不是旧名也不是新名（有人改过）：%', drifted;
  end if;
end $$;

update public.sources s
   set company = r.new_name,
       notes = coalesce(s.notes, '') || E'\n\n' || '2026-10-11 公司名由「' || r.old_name || '」改为「' || r.new_name
               || '」：招聘渠道看 board 与逐岗分类，不写进公司名（迁移 320）。'
  from _src_rename r
 where s.id = r.id
   and s.company = r.old_name;

-- ② 画像正名跟着改，旧名进别名。新名已被别的画像占用时不动（留给每日体检点名，别在这里撞唯一键）。
update public.company_profiles p
   set company = r.new_name,
       display_name = case when p.display_name = r.old_name then r.new_name else p.display_name end,
       aliases = case when r.old_name = any (coalesce(p.aliases, '{}')) then p.aliases
                      else array_append(coalesce(p.aliases, '{}'), r.old_name) end,
       updated_at = now()
  from (values
    ('5197fecd-7e3f-48e4-b86c-10d068f96c1b'::uuid, '创维 Skyworth 校招', '创维 Skyworth'),
    ('7e1bb29e-4cd5-4e90-ac0a-066b94760c79'::uuid, '神州信息—AI实习生', '神州信息'),
    ('904110c3-fc31-4447-8b7b-2101d8170e00'::uuid, '豪迈集团—职能实习生', '豪迈集团')
  ) as r(id, old_name, new_name)
 where p.id = r.id
   and p.company = r.old_name
   and not exists (select 1 from public.company_profiles x where x.company = r.new_name);

-- ③ logo：带后缀那行抓到了（域名与本名那行推导的是同一家公司的），本名那行是 not_found → 把图补到本名行。
update public.company_logos b
   set logo_data = a.logo_data, domain = a.domain, width = a.width, source = a.source,
       status = 'found', fetched_at = a.fetched_at
  from public.company_logos a
 where (a.company, b.company) in (('中国人民保险 校招', '中国人民保险'), ('完美世界 校招', '完美世界'))
   and a.status = 'found'
   and a.logo_data is not null
   and b.status = 'not_found';

-- ④ 亿纬锂能社招源：性质标签补齐。
update public.sources
   set segment = 'private',
       ownership = 'private'
 where company = '亿纬锂能'
   and source_url = 'https://wecruit.hotjob.cn/SU630487ca0dcad45aa7768a79/pb/social.html'
   and coalesce(ownership, 'unknown') = 'unknown';

do $$
declare
  left_old int;
begin
  select count(*) into left_old from _src_rename r join public.sources s on s.id = r.id where s.company <> r.new_name;
  if left_old > 0 then
    raise exception '320：还有 % 条源没改成新名', left_old;
  end if;
end $$;

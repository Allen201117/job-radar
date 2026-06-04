-- ============================================================
-- 021 — 职业洞察行业维度 + 跨行业公司 worklist + 百度实习源（任务 4.3 + 扩源）
-- ============================================================
-- 现状：洞察只覆盖少数互联网公司。这里给 company_profiles 加 industry 维度，并 seed 一批
-- 跨行业公司「画像壳」（仅公司名/别名/行业，无洞察内容）——给 admin 一个按行业的录入 worklist。
-- 不伪造洞察：壳公司在前台抽屉仍显示「暂无核实洞察」，待 admin 在 /admin/insights 录入真实带源条目。

alter table company_profiles add column if not exists industry text;
create index if not exists idx_company_profiles_industry on company_profiles(industry);

-- 跨行业公司 worklist：on conflict 既给已有互联网公司补 industry，也为新行业建壳。
insert into company_profiles (company, display_name, aliases, industry) values
  -- 互联网/科技（多为已有画像，这里补行业标签）
  ('字节跳动', '字节跳动', '{ByteDance,字节}', '互联网/科技'),
  ('腾讯', '腾讯', '{Tencent}', '互联网/科技'),
  ('阿里巴巴', '阿里巴巴', '{Alibaba,阿里}', '互联网/科技'),
  ('京东', '京东', '{JD,JD.com}', '互联网/科技'),
  ('美团', '美团', '{Meituan}', '互联网/科技'),
  ('百度', '百度', '{Baidu}', '互联网/科技'),
  ('华为', '华为', '{Huawei}', '互联网/科技'),
  -- 金融
  ('招商银行', '招商银行', '{招行,CMB}', '金融'),
  ('中国平安', '中国平安', '{平安,Ping An}', '金融'),
  ('中信证券', '中信证券', '{CITIC Securities}', '金融'),
  -- 消费/零售
  ('美的集团', '美的集团', '{美的,Midea}', '消费/零售'),
  ('海尔智家', '海尔智家', '{海尔,Haier}', '消费/零售'),
  ('伊利股份', '伊利', '{伊利集团,Yili}', '消费/零售'),
  -- 制造/工业
  ('比亚迪', '比亚迪', '{BYD}', '制造/工业'),
  ('宁德时代', '宁德时代', '{CATL}', '制造/工业'),
  ('三一重工', '三一重工', '{三一,SANY}', '制造/工业'),
  -- 汽车/出行
  ('理想汽车', '理想汽车', '{理想,Li Auto,LiAuto}', '汽车/出行'),
  -- 医疗/医药
  ('药明康德', '药明康德', '{WuXi AppTec}', '医疗/医药'),
  ('迈瑞医疗', '迈瑞医疗', '{迈瑞,Mindray}', '医疗/医药'),
  ('恒瑞医药', '恒瑞医药', '{恒瑞,Hengrui}', '医疗/医药'),
  -- 能源/化工
  ('国家电网', '国家电网', '{State Grid}', '能源/化工'),
  ('中国石油', '中国石油', '{中石油,PetroChina,CNPC}', '能源/化工'),
  ('隆基绿能', '隆基绿能', '{隆基,LONGi}', '能源/化工'),
  -- 央国企 / 地产
  ('中国移动', '中国移动', '{China Mobile}', '央国企'),
  ('中国建筑', '中国建筑', '{中建,CSCEC}', '央国企'),
  ('万科', '万科', '{Vanke}', '地产/建筑')
on conflict (company) do update
  set industry = excluded.industry,
      updated_at = now();

-- 扩源：百度实习列表（与社招/校招同站，baidu adapter 解析对 recruitType 通用，仅换列表 URL）。
insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '百度', 'https://talent.baidu.com/jobs/intern-list', 'official', 'baidu', 'http', '百度实习（与社招同站，实习列表）'
where not exists (select 1 from sources where source_url = 'https://talent.baidu.com/jobs/intern-list');

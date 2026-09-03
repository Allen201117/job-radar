-- 219 — 扩源：9 个新北森租户（probe.py 完整链路 live 探活通过，含**详情路由**探测）
--
-- 承接迁移 218：同一份 Apache-2.0 校招聚合数据集里还有 171 个库里没有的北森租户。
-- 先用便宜的 httpx 量了一遍（只打 GetJobAdPageList 首页）：148/171 真有岗、合计 22,939 个。
-- 但北森**光有岗不够**——jd_url 需要本租户的详情路由（要浏览器点击探测），探不到就拼不出链接、
-- 全部会被质量门丢掉。所以按岗位数取 Top25 跑 probe.py 完整链路（含路由探测），
-- **只有真拼得出 jd_url 的 9 个入库**，另外 16 个路由探不到，按「拿不到稳定详情链接的源不入库」
-- 的红线丢弃（不是永久结论，路由可由 harvest_beisen_routes.py 后续再探）。
--
-- 通过的：优衣库 1917 / 泰康之家 1619 / 基准方中 490 / 神州信息 416 / 豪迈集团 408 /
--         迪普科技 391 / MOVA 385 / 普渡机器人 316 / 立信会计事务所 273
--
-- 剩余 123 个「有岗但未跑路由探测」的候选留在下一轮（浏览器档慢，一次跑不完）。
--
-- 这 9 家的详情路由已同步落进 crawler/beisen_routes.json（probe.py 只在内存里探到、不落盘），
-- 所以它们**直接进 httpx 快车道**（beisen_httpx_ready 已验证 True），不必每轮再开浏览器重探；
-- crawl_method 因此写 http 而非 playwright。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '优衣库', 'https://uniqlo.zhiye.com/social', 'official', 'beisen', 'http', 'private', '综合', '优衣库（综合，probe live 探活 在华 1160 岗）'
where not exists (select 1 from sources where source_url = 'https://uniqlo.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '泰康之家', 'https://jobtaikang.zhiye.com/social', 'official', 'beisen', 'http', 'private', '综合', '泰康之家（综合，probe live 探活 在华 1128 岗）'
where not exists (select 1 from sources where source_url = 'https://jobtaikang.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '基准方中', 'https://jzfz.zhiye.com/social', 'official', 'beisen', 'http', 'private', '建筑地产', '基准方中（建筑地产，probe live 探活 490 岗）'
where not exists (select 1 from sources where source_url = 'https://jzfz.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '神州信息—AI实习生', 'https://dcits.zhiye.com/social', 'official', 'beisen', 'http', 'private', '互联网科技', '神州信息—AI实习生（互联网科技，probe live 探活 在华 324 岗）'
where not exists (select 1 from sources where source_url = 'https://dcits.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '豪迈集团—职能实习生', 'https://himile1.zhiye.com/social', 'official', 'beisen', 'http', 'private', '装备重工', '豪迈集团—职能实习生（装备重工，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://himile1.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '迪普科技', 'https://dptech.zhiye.com/social', 'official', 'beisen', 'http', 'private', '互联网科技', '迪普科技（互联网科技，probe live 探活 在华 299 岗）'
where not exists (select 1 from sources where source_url = 'https://dptech.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'MOVA', 'https://mova.zhiye.com/social', 'official', 'beisen', 'http', 'private', '快消零售', 'MOVA（快消零售，probe live 探活 在华 352 岗）'
where not exists (select 1 from sources where source_url = 'https://mova.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '普渡机器人', 'https://pudutech1.zhiye.com/social', 'official', 'beisen', 'http', 'private', '互联网科技', '普渡机器人（互联网科技，probe live 探活 在华 305 岗）'
where not exists (select 1 from sources where source_url = 'https://pudutech1.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '立信会计事务所', 'https://bdochina.zhiye.com/social', 'official', 'beisen', 'http', 'private', '综合', '立信会计事务所（综合，probe live 探活 在华 224 岗）'
where not exists (select 1 from sources where source_url = 'https://bdochina.zhiye.com/social');

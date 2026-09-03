-- 218 — 扩源：32 个新飞书招聘租户（probe.py live 探活通过，仅含真返回岗位 + 真 jd_url 的源）
--
-- 来源：2026-09-04 在 GitHub 上找到 Apache-2.0 的校招信息聚合数据集，从中提取出**库里没有的**
-- 租户 310 个（北森 171 / Moka 91 / 飞书 48）。⚠️ 清单只是**候选**，不是已验证源——
-- 按 CLAUDE.md 核心原则 #3「加源必须 live 探活，禁止猜 slug 入库」，全部过 probe.py 的探活门：
-- 解析出 ≥1 条过质量门（含可用 jd_url）的岗位才入库，探不过的直接丢。飞书 48 个里通过 32 个。
--
-- 通过的租户里有分量的：波克城市 503 / 深圳自变量机器人 220 / 中际旭创 166 / 禾赛科技 143 /
-- 启元机器人 134 / 网眼科技 82 / 原力灵机 59 / 永卓控股 56。
--
-- crawl_method 写 http：飞书是 httpx-first（adapters/feishu.py），probe.py 的 _HTTPX_ADAPTERS
-- 早先漏了飞书家族，生成时会误写成 playwright —— 同一 commit 里已修 probe.py，此处一并纠正。
-- （车道选择实际看 run.py 的 _HTTPX_SAFE_ADAPTERS，不看这一列，所以只是口径纠正，不影响行为。）

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '卡方科技', 'https://kafangtech.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '银行金融', '卡方科技（银行金融，probe live 探活 在华 4 岗）'
where not exists (select 1 from sources where source_url = 'https://kafangtech.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '原力灵机', 'https://dexmal-inc.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '互联网科技', '原力灵机（互联网科技，probe live 探活 在华 59 岗）'
where not exists (select 1 from sources where source_url = 'https://dexmal-inc.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '洋葱学园', 'https://guanghe.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '互联网科技', '洋葱学园（互联网科技，probe live 探活 在华 44 岗）'
where not exists (select 1 from sources where source_url = 'https://guanghe.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '波克城市', 'https://boke.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '互联网科技', '波克城市（互联网科技，probe live 探活 在华 502 岗）'
where not exists (select 1 from sources where source_url = 'https://boke.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳自变量机器人', 'https://x2-robot.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '装备重工', '深圳自变量机器人（装备重工，probe live 探活 在华 219 岗）'
where not exists (select 1 from sources where source_url = 'https://x2-robot.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '网眼科技', 'https://webeye.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '互联网科技', '网眼科技（互联网科技，probe live 探活 在华 82 岗）'
where not exists (select 1 from sources where source_url = 'https://webeye.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '禾赛科技', 'https://kwh0jtf778.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '装备重工', '禾赛科技（装备重工，probe live 探活 在华 126 岗）'
where not exists (select 1 from sources where source_url = 'https://kwh0jtf778.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海航天电子技术研究所', 'https://toa7dmu9bq.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '综合', '上海航天电子技术研究所（综合，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://toa7dmu9bq.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '舒客电商', 'https://tianzhulingshan.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '互联网科技', '舒客电商（互联网科技，probe live 探活 在华 19 岗）'
where not exists (select 1 from sources where source_url = 'https://tianzhulingshan.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '水滴', 'https://wdh.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '互联网科技', '水滴（互联网科技，probe live 探活 在华 81 岗）'
where not exists (select 1 from sources where source_url = 'https://wdh.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '梅花集团', 'https://j8fq0c3gg7.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '医药医疗', '梅花集团（医药医疗，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://j8fq0c3gg7.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '容知日新', 'https://mammotion.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '装备重工', '容知日新（装备重工，probe live 探活 在华 108 岗）'
where not exists (select 1 from sources where source_url = 'https://mammotion.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '会通股份', 'https://orinko-ht.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '建筑地产', '会通股份（建筑地产，probe live 探活 在华 18 岗）'
where not exists (select 1 from sources where source_url = 'https://orinko-ht.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '北电数智', 'https://caz6yhvgk5z.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '综合', '北电数智（综合，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://caz6yhvgk5z.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '千岛', 'https://echotech.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '互联网科技', '千岛（互联网科技，probe live 探活 在华 101 岗）'
where not exists (select 1 from sources where source_url = 'https://echotech.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '启元机器人', 'https://primebot.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '装备重工', '启元机器人（装备重工，probe live 探活 在华 134 岗）'
where not exists (select 1 from sources where source_url = 'https://primebot.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中际旭创', 'https://zj-innolight.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '通信运营商', '中际旭创（通信运营商，probe live 探活 在华 155 岗）'
where not exists (select 1 from sources where source_url = 'https://zj-innolight.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '英科医疗', 'https://global-intco.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '医药医疗', '英科医疗（医药医疗，probe live 探活 在华 35 岗）'
where not exists (select 1 from sources where source_url = 'https://global-intco.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '卡尔动力', 'https://kargobot.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '汽车制造', '卡尔动力（汽车制造，probe live 探活 在华 17 岗）'
where not exists (select 1 from sources where source_url = 'https://kargobot.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '星辉游戏', 'https://rastargame.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '互联网科技', '星辉游戏（互联网科技，probe live 探活 在华 16 岗）'
where not exists (select 1 from sources where source_url = 'https://rastargame.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '半鞅私募基金', 'https://banyangcap.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '银行金融', '半鞅私募基金（银行金融，probe live 探活 在华 8 岗）'
where not exists (select 1 from sources where source_url = 'https://banyangcap.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '知存科技', 'https://iucylxooqp.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '装备重工', '知存科技（装备重工，probe live 探活 在华 64 岗）'
where not exists (select 1 from sources where source_url = 'https://iucylxooqp.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '芯耀辉科技', 'https://geg7eg8cyc.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '装备重工', '芯耀辉科技（装备重工，probe live 探活 在华 29 岗）'
where not exists (select 1 from sources where source_url = 'https://geg7eg8cyc.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '普源精电', 'https://rigolportal.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '装备重工', '普源精电（装备重工，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://rigolportal.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '光轮智能', 'https://lightwheel.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '装备重工', '光轮智能（装备重工，probe live 探活 在华 115 岗）'
where not exists (select 1 from sources where source_url = 'https://lightwheel.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '永卓控股', 'https://everrising.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '综合', '永卓控股（综合，probe live 探活 在华 48 岗）'
where not exists (select 1 from sources where source_url = 'https://everrising.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '歌尔丹拿', 'https://k13pqewe7i.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '装备重工', '歌尔丹拿（装备重工，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://k13pqewe7i.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '千署科技', 'https://tranxmart.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '汽车制造', '千署科技（汽车制造，probe live 探活 在华 9 岗）'
where not exists (select 1 from sources where source_url = 'https://tranxmart.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '算秩未来', 'https://acnizrso7ikb.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '互联网科技', '算秩未来（互联网科技，probe live 探活 在华 17 岗）'
where not exists (select 1 from sources where source_url = 'https://acnizrso7ikb.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '其域创新', 'https://pecivkvtit.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '互联网科技', '其域创新（互联网科技，probe live 探活 在华 23 岗）'
where not exists (select 1 from sources where source_url = 'https://pecivkvtit.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '量派投资', 'https://jo0ikgajg1.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '银行金融', '量派投资（银行金融，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://jo0ikgajg1.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '游戏精酿', 'https://gamealestudio.jobs.feishu.cn/index/position', 'official', 'feishu', 'http', 'private', '互联网科技', '游戏精酿（互联网科技，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://gamealestudio.jobs.feishu.cn/index/position');

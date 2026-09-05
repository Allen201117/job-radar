-- 235 — 国家能源集团：从「项目制投递入口」撤下，改接正常源（2026-09-05 live 复核）
--
-- 迁移 229 把国家能源集团以 program_type='announcement' 收进了 apply_programs，
-- 依据是它的招聘官网首页挂着「2027年度高校毕业生直招/统招公告」。**这个判断是错的。**
--
-- 2026-09-05 逐层 live 复核（浏览器渲染 + 纯 httpx 双向验证）：
--   · 列表 POST https://zhaopin.chnenergy.com.cn/recTypeSerch（form，pagenum 0-based，10 条/页）
--     自报总数：统招 2,413 / 直招 422 / 藏青疆 156 / 乡村振兴 17 / 菁英管培生 9 / 社招 259。
--   · 每个岗位都有**稳定且可匿名打开**的详情页 /annc/showgw?id={uuid}：
--     返回岗位名（与列表逐字一致）、招聘单位、工作地点、招聘人数、岗位职责、岗位要求、报名截止日期。
--     例：/annc/showgw?id=5a798bfe-a4d4-0be4-e063-98b4d40a088a → 「仪表检维修」，中国神华煤制油化工…
--
-- 也就是说它**有一岗一页**，只是同时也发公告。挂着「公告制」徽章等于对用户说假话：
-- 用一个公告链接替掉了本可以给用户的 3,000+ 条真实岗位链接，正是 226 立的那条红线。
--
-- 处置：apply_programs 行**停用不删**（保留可回滚 + 保留这段判断依据），另插正常源。
-- ⚠️ 时效：2027 届校招 2026-09-02 开、报名截止 2026-10-07，接晚了这批岗就过期了。

update apply_programs
   set enabled = false, updated_at = now()
 where entry_url = 'https://zhaopin.chnenergy.com.cn/index1';

-- ⚠️ 先更新 board 分类函数，再插源 —— board 是 generated 列，值在 INSERT 那一刻算死。
-- chnenergy 一条源同时抓校招（kinds=1，3,017 岗）和社招（kinds=3，259 岗），属于规则①的 mixed。
-- 不加进去它会落到兜底分支 'social'，后果不是难看而是**校招车道整个漏掉它**：
-- campus-crawl 选源用 board in ('campus','mixed')，校招覆盖度量的 hasCampusSource 同样只认这两个值。
-- ⚠️ 这个函数是**全量重建而非增量**：下面必须把旧的枚举值一个不落抄全，漏一个会把存量源打错档。
create or replace function public.classify_source_board(p_adapter text, p_url text)
returns text
language sql
immutable
as $$
  select case
    -- ① adapter 一次抓全社招+校招+实习
    when coalesce(p_adapter, '') in ('tencent', 'baidu', 'wt', 'beisen', 'chnenergy') then 'mixed'
    -- ② 专职校招 adapter：只抓校招/实习，与社招是两个独立源。
    --    ⚠️ 判据是 adapter 而不是 URL —— 校招域名叫什么各家随意（join.qq.com 无任何令牌）。
    when coalesce(p_adapter, '') in (
      'bytedance_campus', 'tencent_campus', 'hikvision', 'jd_campus',
      'alibaba_campus', 'meituan_campus', 'kuaishou_campus', 'huawei_campus'
    ) then 'campus'
    -- ③ 阿里 BU 的 off-campus = 社招频道，必须先短路
    when coalesce(p_url, '') ~* 'off-campus' then 'social'
    -- ④ URL 校招令牌
    when coalesce(p_url, '') ~* '(campus|/school|school\.html|/grad|university|xiaozhao)' then 'campus'
    -- ⑤ URL 实习令牌
    when coalesce(p_url, '') ~* '(intern|shixi)' then 'intern'
    else 'social'
  end
$$;

-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列（迁移 187），显式赋值会让整批迁移回滚。
-- ⚠️ crawl_method 只认 http / playwright / manual —— 这条是纯 httpx，填 http。
insert into sources (company, source_url, adapter_name, crawl_method, regions, segment, industry, enabled, notes)
values
  ('国家能源集团', 'https://zhaopin.chnenergy.com.cn/index1', 'chnenergy', 'http', '{CN}', 'soe', '能源/化工', true,
   'POST /recTypeSerch 列表（kinds=1 校招含 5 个子渠道 schType=18/1/2/19/7，kinds=3 社招；'
   'kinds=2 内部招聘刻意不抓）+ GET /annc/showgw?id={uuid} 逐岗详情补正文。'
   '完整性逐渠道判，不拿去重后条数比各渠道总数之和（渠道会重叠）。'
   '岗位 id 是 Oracle GUID、前 8 位共享前缀，去重比对必须用全串。'
   '列表里的招聘单位是子公司（如中国神华煤制油化工），刻意不写进 company —— '
   '名字里没有「国家能源」，写进去会让这批岗掉出必投清单 %国家能源% 的统计口径，改放 summary 抬头。')
on conflict (source_url) do nothing;

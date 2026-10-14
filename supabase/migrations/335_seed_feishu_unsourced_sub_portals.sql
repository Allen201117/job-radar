-- 335 — 接入 16 个飞书租户上「有在招岗、库里没有源」的子门户（校招 / 实习 / 新社招门户）
--       （2026-10-15 全量普查 + 逐门户核实）
--
-- 入口是怎么找到的（没有猜路径）：飞书租户首页的 HTML 里内嵌着导航配置（转义 JSON 的 "path" 字段，
--   写成 https://{host}/{段} 或 /{段}），租户自己在顶栏链出去的门户都在里面。把在用的 111 个飞书系 host
--   的首页（及各门户首页）读一遍、每个门户带 website-path 头把列表翻全，再减去库里已有源取到的岗。
--   跨域名的同一租户（jobs.chagee.com / xd-legacy / yvjpcqa2af / campus.dewu.com）按 website_info.id
--   与岗位编号对过：霸王茶姬社招 / 实习、利欧社招、得物社招都已由现有源抓到，不重复接。
--
-- 每个门户都核过的（2026-10-15 live，全部只读）：
--   · 身份只认门户自报（<title> / tenant_name / website_info.name），16 个门户的租户名都与本租户已有主门户源相同；
--     千岛那个门户自报「回响科技校园招聘」，与 10-11 普查时主门户的自报相同（回响科技是千岛的运营公司，源名沿用「千岛」）。
--   · 真实 adapter 端到端（robots → should_skip → fetch → parse → 质量门 → normalize，不写库）：
--     16 个门户全部标抓全（列表条数 = 接口自报总数），质量门 832/832 通过。
--   · 逐岗带本门户的 website-path 读详情接口 channel_online_status（全集）：832/832 在线。
--   · 香港库按公司名查在招岗（任何来源）：除下面两家的 14 个重叠岗外，这 832 个岗位编号一个都不在库里，
--     爱奇艺北森源（iqiyi.zhiye.com）只有 17 个社招 / 实习岗。
-- 两家的重叠岗（同一个岗在本租户两个门户上都挂着、都在线）由 adapter 的 _SHARED_TENANT_PORTAL_OWNER 只留一行：
--   · 亚信安全：index 是「社招官网（旧版）」12 岗，12 个全部也在新社招门户 social 上 → 归 social；
--     主门户源库里那 12 行下架成 removed（0 条用户动作），主门户源此后只剩自报的 campus 12 岗。
--   · 爱奇艺：intern 与已有的 campus、internship 源各重 1 个 → 归 intern，那 2 行下架成 removed（0 条用户动作）。
-- 没接的（都在普查结果里，非遗漏）：
--   · 拓竹 global（Join the team at Bambu Lab，101 岗）：87 个已在主门户 experienced 上，另 14 个里 12 个在
--     圣克拉拉 / 法兰克福 / 新加坡 / 奥斯汀 —— 接它要么一岗两行、要么只为十几个海外岗多一道登记，先不接。
--   · 霸王茶姬 store（门店招聘 5 岗：茶饮师（兼职）/ 店长…）与 640739（2026 校园招聘，0 岗）。
--   · 利欧 referral（内推官网）：内推门户不接（同字节 /referral）。
-- 已知而没处理的：
--   · board 是派生列，10 条地址里没有 campus / intern 字样（379481 / 420214 / 252342 / leoxz / 285572 / 021343 /
--     051736 / 581609 / 912130 / 117745），会派生成 social；逐岗分类按标题 / 自报类型判，不受影响。必投清单上的
--     利欧、度小满两家，若校招门户日后清零，校招覆盖卡会把缺口记成「我们的」（同迁移 332 英科医疗校招）。
--   · 普查只证明今天两两门户不重叠；对方日后把同一个岗同时挂到主门户和这些门户上，没登记的租户会一岗两行。
-- ⚠️ 只写 sources 允许直填的列（board 是 generated 列）；segment / industry / industry_group / ownership 抄本租户主门户源
--    （受 CHECK 约束的列不手写取值）。源名沿用主门户源的公司名，不带渠道后缀。
-- Idempotent：insert 按 source_url 防重；末尾终态断言不成立整批回滚（scripts/db-migrate.sh 用 psql -1 跑，一个文件一个事务）。
-- 回滚：update sources set enabled = false where notes like '2026-10-15 接入（迁移 335）%'; 并撤掉 adapters/feishu.py 里亚信 / 爱奇艺两条登记。


set local lock_timeout = '10s';

-- ① 16 条新源。清单放临时表：插入和末尾的终态断言读同一份，少插了哪条能点名。
create temp table m335 (source_url text primary key, main_url text not null, notes text not null) on commit drop;
insert into m335 (source_url, main_url, notes) values
  ('https://vrfi1sk8a0.jobs.feishu.cn/379481/position', 'https://vrfi1sk8a0.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：MiniMax 校招官网。主门户首页导航链到 /379481；门户自报 title「加入MiniMax」、website_info.name「校招官网」、tenant_name「MiniMax」。带 website-path: 379481 取列表 101 岗（校招 31 / 实习 70），逐岗读状态 101/101 在线，与主门户交集 0。$md$),
  ('https://xtool.jobs.feishu.cn/420214/position', 'https://xtool.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：xTool 校招官网。主门户首页导航链到 /420214；门户自报 title「加入xTool」、website_info.name「校招官网」、tenant_name「xTool」。列表 27 岗（全是校招），逐岗读状态 27/27 在线，与主门户交集 0。$md$),
  ('https://asiainfo-sec.jobs.feishu.cn/social/position', 'https://asiainfo-sec.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：亚信安全新社招门户。门户自报 title「加入亚信安全」、website_info.name「亚信安全社招」、tenant_name「亚信」。列表 71 岗（社招 60 / 实习 11），逐岗读状态 71/71 在线。租户首页自报的是 campus（校园招聘），index 是「社招官网（旧版）」12 岗、全部也在本门户上 → 归本源（adapter 登记 _SHARED_TENANT_PORTAL_OWNER）。$md$),
  ('https://pecivkvtit.jobs.feishu.cn/252342/position', 'https://pecivkvtit.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：其域创新校招官网。主门户首页导航链到 /252342；门户自报 title「加入深圳市其域创新科技有限公司」、website_info.name「校招官网」。列表 31 岗（校招 26 / 实习 5），逐岗读状态 31/31 在线，与主门户交集 0。$md$),
  ('https://leoglobal.jobs.feishu.cn/leoxz/position', 'https://leoglobal.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：利欧集团 2027 届校招官网。主门户首页导航链到 /leoxz；门户自报 title「利欧集团校招」、website_info.name「2027届校招官网」、tenant_name「利欧集团」。列表 28 岗，逐岗读状态 28/28 在线，与主门户（自报 leosz）交集 0。同租户的内推门户 referral 不接。$md$),
  ('https://echotech.jobs.feishu.cn/xiaozhao/position', 'https://echotech.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：千岛（运营公司回响科技）校招官网。主门户首页导航链到 /xiaozhao；门户自报 title「回响科技校园招聘」、website_info.name「校招官网」、tenant_name「回响科技」，与主门户自报相同。列表 19 岗（校招 5 / 实习 14），逐岗读状态 19/19 在线，与主门户（自报 qiandaozhaopin）交集 0。$md$),
  ('https://dexmal-inc.jobs.feishu.cn/285572/position', 'https://dexmal-inc.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：原力灵机校招官网。主门户首页导航链到 /285572；门户自报 title「欢迎加入原力灵机」、website_info.name「校招官网」、tenant_name「原力灵机」。列表 37 岗（校招 20 / 实习 17），逐岗读状态 37/37 在线，与主门户交集 0。$md$),
  ('https://tarsrobot.jobs.feishu.cn/021343/position', 'https://tarsrobot.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：它石智航校园招聘门户。主门户首页导航链到 /021343；门户自报 title「加入它石智航」、website_info.name「校园招聘」、tenant_name「它石智航」。列表 40 岗（校招 27 / 实习 13），逐岗读状态 40/40 在线，与主门户交集 0。$md$),
  ('https://mammotion.jobs.feishu.cn/campus_recruitment/position', 'https://mammotion.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：库犸科技校园招聘门户。主门户首页导航链到 /campus_recruitment；门户自报 title「加入深圳库犸科技有限公司」、website_info.name「库犸科技-校园招聘」、tenant_name「深圳库犸创新科技集团有限公司」。列表 11 岗（校招 5 / 实习 6），逐岗读状态 11/11 在线，与主门户（自报 social_recruitment）交集 0。$md$),
  ('https://duxiaoman.jobs.feishu.cn/051736/position', 'https://duxiaoman.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：度小满 2027 校园招聘门户。主门户首页导航链到 /051736；门户自报 title 与 website_info.name 都是「度小满2027校园招聘」、tenant_name「度小满科技（北京）有限公司」。列表 35 岗，逐岗读状态 35/35 在线，与主门户交集 0。$md$),
  ('https://everrising.jobs.feishu.cn/graduate/position', 'https://everrising.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：永卓控股校园招聘门户。主门户首页导航链到 /graduate；门户自报 title「永卓控股校园招聘」、website_info.name「校招官网」、tenant_name「永卓控股有限公司」。列表 45 岗（校招 42 / 实习 3），逐岗读状态 45/45 在线，与主门户交集 0。$md$),
  ('https://boke.jobs.feishu.cn/581609/position', 'https://boke.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：波克城市校招新官网。主门户首页导航链到 /581609；门户自报 title「波克校园招聘」、website_info.name「校招新官网」、tenant_name「波克科技集团」。列表 114 岗（校招 103 / 实习 11），逐岗读状态 114/114 在线，与主门户交集 0。$md$),
  ('https://x2-robot.jobs.feishu.cn/912130/position', 'https://x2-robot.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：自变量机器人校招官网。主门户首页导航链到 /912130；门户自报 title「加入自变量机器人 | 校园招聘」、website_info.name「自变量机器人校招官网」。列表 82 岗，逐岗读状态 82/82 在线，与主门户交集 0。$md$),
  ('https://iq.jobs.feishu.cn/intern/position', 'https://iq.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：爱奇艺实习生官网。主门户首页导航链到 /intern（与已有的 /internship 是两个门户）；门户自报 title「爱奇艺实习生招聘」、website_info.name「实习生官网」、tenant_name「爱奇艺」。列表 97 岗（全是实习），逐岗读状态 97/97 在线。与 campus、internship 两条源各重 1 个岗 → 归本源（adapter 登记 _SHARED_TENANT_PORTAL_OWNER）。$md$),
  ('https://lilithgames.jobs.feishu.cn/intern/position', 'https://lilithgames.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：莉莉丝实习生招聘官网。主门户首页导航链到 /intern；门户自报 title「莉莉丝校园招聘」、website_info.name「实习生招聘官网」、tenant_name「莉莉丝」。列表 58 岗（实习 57 / 校招 1），逐岗读状态 58/58 在线，与主门户（自报 career）及 campus 源交集 0。$md$),
  ('https://xd-legacy.jobs.feishu.cn/117745/position', 'https://xd.jobs.feishu.cn/index/position',
   $md$2026-10-15 接入（迁移 335）：心动（XD Inc.）校招官网。xd.jobs.feishu.cn 首页导航「校园招聘」链到 xd-legacy.jobs.feishu.cn/117745（两个域名是同一租户：website_info.id 相同，社招门户岗位编号 57/57 相同），按对方自己的链接用 xd-legacy 域名。门户自报 title「加入XD Inc.」、website_info.name「校招官网」、tenant_name「XD Inc.」。列表 36 岗（实习 34 / 校招 2），逐岗读状态 36/36 在线，与社招门户交集 0。$md$);

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select m.company, v.source_url, 'official', 'feishu', 'http', true, '{CN}',
       m.segment, m.industry, m.industry_group, m.ownership, v.notes
from m335 v
join public.sources m on m.source_url = v.main_url and m.adapter_name = 'feishu'
where not exists (select 1 from public.sources x where x.source_url = v.source_url);

-- ② 让出重叠岗的三条源记一句为什么（剔除与下架由 adapter 的登记表执行，库里只留说明，同迁移 332）
update public.sources s
   set notes = coalesce(s.notes, '') || E'\n\n' || u.note
from (values
  ('https://asiainfo-sec.jobs.feishu.cn/index/position',
   $md$2026-10-15（迁移 335）：本源取的是租户首页自报的 campus 门户 ∪ index 门户。index 是「社招官网（旧版）」，接入时它的 12 个岗全部也挂在新社招门户 social 上，归新接的 social 源：本源抓的时候剔掉它们，库里已有的下架成 removed（adapter 登记 _SHARED_TENANT_PORTAL_OWNER）。social 门户列表没取全时本源整轮记失败。$md$),
  ('https://iq.jobs.feishu.cn/campus/position',
   $md$2026-10-15（迁移 335）：本门户与新接的 intern 门户（实习生官网）都挂着的岗归 intern 源（接入时 1 个：数据标注实习生）：本源抓的时候剔掉它们，库里已有的下架成 removed（adapter 登记 _SHARED_TENANT_PORTAL_OWNER）。intern 门户列表没取全时本源整轮记失败。$md$),
  ('https://iq.jobs.feishu.cn/internship/position',
   $md$2026-10-15（迁移 335）：本门户与新接的 intern 门户（实习生官网）都挂着的岗归 intern 源（接入时 1 个：Social Media & Content Intern (Chinese & Arabic)）：本源抓的时候剔掉它们，库里已有的下架成 removed（adapter 登记 _SHARED_TENANT_PORTAL_OWNER）。intern 门户列表没取全时本源整轮记失败。$md$)
) as u(source_url, note)
where s.source_url = u.source_url and s.adapter_name = 'feishu'
  and coalesce(s.notes, '') not like '%（迁移 335）%';

-- 终态断言：任何一条不成立，整份迁移回滚。①靠主门户源的 URL 精确匹配取列：对不上会安静地少插，这里点名是哪几条。
do $$
declare
  missing text[];
  noted int;
begin
  select array_agg(v.source_url order by v.source_url) into missing
    from m335 v
   where not exists (select 1 from public.sources s
                      where s.source_url = v.source_url and s.adapter_name = 'feishu' and s.enabled
                        and s.regions = '{CN}' and s.company is not null and s.industry_group is not null);
  if missing is not null then
    raise exception '335: 这些源没落成（主门户源 URL 没对上，或同地址已有一条停用 / 改过的源）：%', missing;
  end if;
  select count(*) into noted from public.sources
   where source_url in ('https://asiainfo-sec.jobs.feishu.cn/index/position', 'https://iq.jobs.feishu.cn/campus/position', 'https://iq.jobs.feishu.cn/internship/position')
     and adapter_name = 'feishu' and enabled and notes like '%2026-10-15（迁移 335）%';
  if noted <> 3 then
    raise exception '335: 让出重叠岗的三条源只有 % 条写上了说明（应为 3）', noted;
  end if;
end $$;

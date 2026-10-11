-- 318 — 纠正两条张冠李戴（2026-10-11 查实，创始人同日同意「按建议来」）：
--   A. 北森租户 dongpeng.zhiye.com 是「广东东鹏控股股份有限公司」（瓷砖卫浴，003012），不是「东鹏饮料」（605499）
--   B. Moka 租户 zulong 的社招门户是「祖龙娱乐」（9990.HK，游戏），不是「上海鹰瞳医疗科技集团股份有限公司」
--
-- 对方页面自己怎么说（live，全部只读）：
--   A. dongpeng.zhiye.com 的 / 、/campus 、/social 、/social/jobs 、/intern 五个入口同一个 PortalId，
--      <title>广东东鹏控股股份有限公司</title>。列表全量翻完 100 岗（自报 Count=100），招聘机构是「瓷砖事业部」
--      「东鹏控股」「国际营销中心」…，地点佛山 77 / 清远 / 澧县 / 宜春 / 重庆；整份列表里「饮料」出现 0 次。
--      库里这个前缀下 100 个 active 岗全挂「东鹏饮料」，与门户现挂的 100 个按 jobAdId 一一对上、标题逐条相同
--      （库里有门户没有 0 / 门户有库里没有 0）；公司名含「东鹏」的行只有这 100 行。
--   B. social-recruitment/zulong/25157  <title>祖龙娱乐 - 社会招聘</title>
--      campus-recruitment/zulong/25158  <title>祖龙娱乐-校园招聘</title>
--      两页 org.name=祖龙娱乐，intro「祖龙娱乐（股票代码：9990.HK）是中国领先的移动游戏公司…」；「鹰瞳」出现 0 次。
--      库里社招前缀下 27 个 active 岗全挂「上海鹰瞳医疗…」（剧情导演 / 数值策划 / 资深游戏特效…），
--      公司名含「鹰瞳」的行只有这 27 行；同租户校招源（auto_discover 2026-08-04 接的）名字本来就是「祖龙娱乐」。
--      真正的鹰瞳（北京鹰瞳科技发展股份有限公司，Airdoc，2251.HK）另有 Moka 租户 airdoc，未接，本迁移不接。
-- 根因：
--   A. 探活清单「东鹏饮料」的 cn='东鹏'，标题核验只要求标题含 cn，「广东东鹏控股股份有限公司」照样放行（同 291 大华）。
--      之后迁移 186 清同租户重复源，留下了挂着岗的这条错名源，停掉了名字对的「东鹏」（/social/jobs）。
--      清单那一行同批改成 cn='东鹏饮料' 并去掉 slug dongpeng：不改的话，改名后扩源会判「库里缺东鹏饮料」，
--      把同一个租户以原名插回来（北森候选是 /social 与 /campus，库里只占了 /campus 与 /social/jobs）。
--   B. 迁移 129（moka slug oracle 那批）seed 时公司名就是错的，行业却写的是「游戏」。当时的清单没进仓库，
--      cn 是什么查不到；任何带「鹰瞳」的 cn 都过不了「祖龙娱乐 - 社会招聘」这个标题的核验。
-- 影响：这 127 个岗上没有任何用户动作（job_actions 0 行）；两家都不在必投清单里，缺口台账不受影响。
--   按公司名分行业时「东鹏饮料」落在消费/零售、「上海鹰瞳医疗…」落在医疗/医药，岗位其实是建材和游戏。
--   年报没挂错：「东鹏」画像下是 003012 的上市状态与 2025 年报，「东鹏饮料」画像下是 605499 的；
--   挂错的只有岗位，以及按这批岗算出来的派生指标（东鹏饮料 8 条、鹰瞳 6 条）。
--   上线前只读演练（按下面每条语句的 where 在真库上数）：①快照相加 38 行 / ②源 1+1+1 行 / ③画像 1 行 + 文案 1 行 /
--   ④主体 1 行 + 派生条目 8 行 / ⑤撤下 6 行 + 归零 1 行；末尾断言的前提全部成立。
--
-- 处置（两条源本身是好的：岗位真实、jd_url 稳定，只是挂错了名 → 保留、改名）：
--   ① 祖龙娱乐公司主体的每日在招数快照，补上社招那 27 个岗的部分（两个主体各 38 天，日期逐天对得上）。
--      不补的话改名后祖龙娱乐从 21 个岗跳到 48 个，派生指标会写出「30 天环比 +140%」——那 27 个岗一直都是它的。
--      ⚠️ 必须排在源改名之前：用「源还挂着旧名」当闸，重复执行不会再加一遍。
--   ② 三条源改名。dongpeng 两条（含 186 停掉的那条）→「东鹏控股」，在抓的那条行业改建材；zulong 社招 →「祖龙娱乐」。
--   ③ 画像「东鹏」改名「东鹏控股」（它名下本来就是 003012 的官方事实）。源改名后岗位公司名是「东鹏控股」，
--      正名对上最稳；不登记别名「东鹏」——它在东鹏控股与东鹏饮料之间有歧义。
--   ④ 「东鹏饮料」画像下的公司主体（连同 38 天快照）和挂在它上面的派生指标，整体改挂到「东鹏控股」画像：
--      这些数就是拿东鹏控股的 100 个岗算的，内容没错，只是挂错了画像。派生指标的唯一键是 (subject_id, metric_key)，
--      改挂不撞键。「东鹏饮料」画像保留，名下剩 605499 的 3 条官方事实。
--   ⑤ 「上海鹰瞳医疗…」画像下的派生指标撤下、公司主体在招数归零。画像保留（创始人选不删）。
--   ⑥ 香港库存量 127 行改名走 rename-job-company.yml（jd_url 前缀 https://dongpeng.zhiye.com/ 与
--      https://app.mokahr.com/social-recruitment/zulong/）；`company` 在 jobs_db._UPDATE_COLS 里，之后每轮重抓按新名写。
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列，显式赋值整批迁移会回滚。industry_group 受 CHECK 约束
--    （迁移 265），'制造/工业' 是已有取值（186 停掉的那条「东鹏」源就是它）。
-- ⚠️ 没有删任何行，也没有留底表：①可由鹰瞳主体原样保留的快照减回去，②~⑤都是改名 / 改挂 / 改状态。
-- Idempotent：每条 update 的 where 带旧值，①带闸；末尾的终态断言任何一条不成立整批回滚
--   （scripts/db-migrate.sh 用 psql -1 跑，一个文件一个事务）。

set local lock_timeout = '10s';

-- ① 祖龙娱乐主体的每日快照补上社招那部分
do $$
declare
  y_subject uuid;
  z_subject uuid;
begin
  if not exists (select 1 from sources
                  where source_url = 'https://app.mokahr.com/social-recruitment/zulong/25157'
                    and company = '上海鹰瞳医疗科技集团股份有限公司') then
    return;  -- 源已经改过名 = 这一步做过了
  end if;
  select s.id into y_subject
    from insight_subjects s join company_profiles p on p.id = s.company_id
   where p.company = '上海鹰瞳医疗科技集团股份有限公司' and s.kind = 'company';
  select s.id into z_subject
    from insight_subjects s join company_profiles p on p.id = s.company_id
   where p.company = '祖龙娱乐' and s.kind = 'company';
  if y_subject is null or z_subject is null then
    return;
  end if;
  update insight_subject_daily z
     set active_count = z.active_count + y.active_count,
         new_30d = coalesce(z.new_30d, 0) + coalesce(y.new_30d, 0)
    from insight_subject_daily y
   where z.subject_id = z_subject
     and y.subject_id = y_subject
     and y.day = z.day;
  -- 祖龙那边缺的日子（实测 0 天）原样补一行，放在相加之后，避免被加两遍。
  insert into insight_subject_daily (subject_id, day, active_count, new_30d)
  select z_subject, y.day, y.active_count, y.new_30d
    from insight_subject_daily y
   where y.subject_id = y_subject
     and not exists (select 1 from insight_subject_daily z
                      where z.subject_id = z_subject and z.day = y.day);
end $$;

-- ② 源改名
update sources
   set company = '祖龙娱乐',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-11 公司名由「上海鹰瞳医疗科技集团股份有限公司」纠正为「祖龙娱乐」：Moka 租户 zulong 的社招门户页面自报 org.name=祖龙娱乐（9990.HK，游戏），title「祖龙娱乐 - 社会招聘」，与同租户校招源（campus-recruitment/zulong/25158）同一家；页面里「鹰瞳」出现 0 次。真正的鹰瞳（Airdoc，2251.HK）另有 Moka 租户 airdoc，未接。$md$
 where source_url = 'https://app.mokahr.com/social-recruitment/zulong/25157'
   and company = '上海鹰瞳医疗科技集团股份有限公司';

update sources
   set company = '东鹏控股',
       industry = '建材',
       industry_group = '制造/工业',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-11 公司名由「东鹏饮料」纠正为「东鹏控股」：北森租户 dongpeng 页面 title=广东东鹏控股股份有限公司（瓷砖卫浴，003012），列表 100 个岗的招聘机构是瓷砖事业部 / 东鹏控股…，地点佛山 / 清远，「饮料」出现 0 次。东鹏饮料（605499）是另一家公司，没有公开的逐岗官方门户（邮箱 + 公众号 + 第三方托管网申页）。$md$
 where source_url = 'https://dongpeng.zhiye.com/campus'
   and company = '东鹏饮料';

update sources
   set company = '东鹏控股',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-11 公司名由「东鹏」统一为「东鹏控股」（与同租户在抓的 /campus 源一致；本条自迁移 186 起停用）。$md$
 where source_url = 'https://dongpeng.zhiye.com/social/jobs'
   and company = '东鹏';

-- ③ 画像「东鹏」→「东鹏控股」
update company_profiles
   set company = '东鹏控股',
       updated_at = now()
 where company = '东鹏'
   and not exists (select 1 from company_profiles where company = '东鹏控股');

update insight_items
   set content = replace(content, '，东鹏为已上市公司', '，东鹏控股为已上市公司'),
       updated_at = now()
 where company_id in (select id from company_profiles where company = '东鹏控股')
   and origin = 'official'
   and dimension = 'listing'
   and content like '%，东鹏为已上市公司%';

-- ④ 「东鹏饮料」画像下的公司主体 + 派生指标 → 改挂到「东鹏控股」画像
update insight_subjects s
   set company_id = t.id,
       name = '东鹏控股',
       updated_at = now()
  from company_profiles t, company_profiles f
 where t.company = '东鹏控股'
   and f.company = '东鹏饮料'
   and s.company_id = f.id
   and s.kind = 'company'
   and s.origin = 'derived_title'
   and not exists (select 1 from insight_subjects x where x.company_id = t.id and x.name = '东鹏控股');

update insight_items i
   set company_id = s.company_id,
       title = '东鹏控股',
       updated_at = now()
  from insight_subjects s
  join company_profiles t on t.id = s.company_id
 where t.company = '东鹏控股'
   and s.kind = 'company'
   and s.name = '东鹏控股'
   and i.subject_id = s.id
   and i.origin = 'derived'
   and i.company_id is distinct from s.company_id;

-- ⑤ 「上海鹰瞳医疗…」画像：派生指标撤下，公司主体在招数归零（画像保留）
update insight_items
   set status = 'retired',
       updated_at = now()
 where company_id in (select id from company_profiles where company = '上海鹰瞳医疗科技集团股份有限公司')
   and origin = 'derived'
   and status = 'active';

update insight_subjects
   set job_count = 0,
       updated_at = now()
 where company_id in (select id from company_profiles where company = '上海鹰瞳医疗科技集团股份有限公司')
   and kind = 'company'
   and origin = 'derived_title'
   and job_count <> 0;

-- 终态断言：任何一条不成立，整份迁移回滚
do $$
begin
  if exists (select 1 from sources
              where source_url like 'https://dongpeng.zhiye.com/%' and company <> '东鹏控股') then
    raise exception '318: dongpeng.zhiye.com 下还有源不叫「东鹏控股」';
  end if;
  if (select count(*) from sources where source_url like 'https://dongpeng.zhiye.com/%') <> 2 then
    raise exception '318: dongpeng.zhiye.com 下的源不是预期的 2 条';
  end if;
  if exists (select 1 from sources
              where source_url like 'https://app.mokahr.com/%/zulong/%' and company <> '祖龙娱乐') then
    raise exception '318: Moka 租户 zulong 下还有源不叫「祖龙娱乐」';
  end if;
  if exists (select 1 from sources
              where enabled and company in ('东鹏饮料', '东鹏', '上海鹰瞳医疗科技集团股份有限公司')) then
    raise exception '318: 还有 enabled 的源挂着旧名';
  end if;
  if (select count(*) from company_profiles where company = '东鹏控股') <> 1
     or exists (select 1 from company_profiles where company = '东鹏') then
    raise exception '318: 画像「东鹏」→「东鹏控股」没有落成恰好一个';
  end if;
  if exists (select 1
               from insight_items i
               join company_profiles p on p.id = i.company_id
              where p.company in ('东鹏饮料', '上海鹰瞳医疗科技集团股份有限公司')
                and i.origin = 'derived'
                and i.status = 'active') then
    raise exception '318: 错名画像下还有在展的派生指标';
  end if;
  if exists (select 1
               from insight_items i
               join insight_subjects s on s.id = i.subject_id
              where i.company_id is distinct from s.company_id
                and s.company_id in (select id from company_profiles
                                      where company in ('东鹏控股', '东鹏饮料', '祖龙娱乐',
                                                        '上海鹰瞳医疗科技集团股份有限公司'))) then
    raise exception '318: 有洞察条目的画像与它所属主体的画像不一致';
  end if;
end $$;

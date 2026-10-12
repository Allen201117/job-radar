-- 323 — 纠正三条挂错公司名的飞书源，停用门户已不存在的道旅科技
--       （2026-10-11 飞书系 138 条源全量普查查实，创始人 2026-10-12 同意「1234 都做」）
--
-- 现象（三条都是迁移 218 那批：外部清单 → probe.py 探活 → 入库，那条路当时没有任何核名）：
--   A. mammotion.jobs.feishu.cn 记成「容知日新」（688768，设备状态监测）。门户自报深圳库犸创新科技集团有限公司 /
--      「加入深圳库犸科技有限公司」（Mammotion，庭院割草机器人）；首页正文「库犸」21 处、「容知」0 处；
--      84 个在招岗在深圳 / 杜塞尔多夫（激光 SLAM、Service Partner Management）。两家没有任何关系。
--   B. global-intco.jobs.feishu.cn 记成「英科医疗」（300677，一次性手套）。门户标题「英科再生社会招聘官网」
--      （688087，再生塑料；同一实控人的另一家上市公司）；87 个在招岗里「手套」0 个，有「再生塑料粒子」「回收设备」
--      「框条」，地点淄博 / 上海 / 六安 / 镇江 / 越南清化 / 马来西亚巴生，另有 15 个淮北「凯泽」岗（集团里另一家，
--      挂在这个门户上）。租户名只写「英科」。
--      ⚠️ 这是集团共用租户：不带门户头能取到 465 个，公开门户只有这 87 个；另外 381 个（淮北 / 安庆 / 九江，
--      正文有手套、丁腈、轮椅）不在这个门户上，是英科医疗一侧的，挂在哪个公开门户没查到 —— 英科医疗目前零源，另行找入口。
--   C. tranxmart.jobs.feishu.cn 记成「千署科技」。门户自报「千曙科技」（千方科技的自动驾驶子公司），同一家，写错一个字。
--   D. didatravel.jobs.feishu.cn（道旅科技 Dida）：租户首页 404，浏览器里是 Not Found；最近 4 轮都是
--      「抓到 0 个、记成功」，香港库 0 个在招（21 行早已 removed）。
-- 核验（全部只读）：三条的岗位详情页浏览器里都能开（各实开 1 条，标签页标题就是门户自报名）；
--   这 179 个岗上没有任何用户动作（job_actions 0 行）；三家都不在必投清单 / 扩源清单 / 关注请求里；
--   库里没有叫「库犸科技」「英科再生」「千曙科技」的源或画像。
--   完整清单与复现方法：docs/reviews/2026-10-11-feishu-source-attribution-census.md。
--
-- 处置（三条源本身是好的：岗位真实、jd_url 稳定，只是挂错了名 → 保留、改名）：
--   ① 三条源改名；库犸、英科再生的行业一并改对（原来按错的公司填的装备重工 / 医药医疗）。
--   ② 道旅科技停用（保留行可回滚）。
--   ③ 画像「千署科技」改名「千曙科技」，公司主体同步改名（同一家公司，37 天快照原样留着），并登记别名「千署科技」：
--      香港库存量改名之前，岗位还挂着旧写法，别名让它们继续归到这个画像，不会被当成新公司再建一个。
--   ④ 「容知日新」「英科医疗」画像下的派生指标撤下、公司主体在招数归零。那 16 条是拿库犸和英科再生的岗算的
--      （例：「容知日新在招岗位数 84 个」）；画像保留，名下来自年报 / 上市公告的 5 条事实是真的。
--      库犸科技、英科再生的画像不在这里建：建画像只有一个入口（先认别名，没有才建），改名后由日常链路去建。
--   ⑤ 香港库存量 179 行改名走 rename-job-company.yml（三个 jd_url 前缀）；`company` 在 jobs_db._UPDATE_COLS 里，
--      之后每轮重抓按新名写。
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列；industry_group 受 CHECK 约束（迁移 265），'制造/工业' 是已有取值。
-- ⚠️ 没有删任何行，也没有留底表：①~④ 都是改名 / 改状态，每条 where 带旧值，可按本文件反向改回。
-- Idempotent：重复执行每条 update 命中 0 行；末尾的终态断言任何一条不成立整批回滚
--   （scripts/db-migrate.sh 用 psql -1 跑，一个文件一个事务）。

set local lock_timeout = '10s';

-- ① 源改名
update sources
   set company = '库犸科技',
       industry = '智能硬件',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 公司名由「容知日新」纠正为「库犸科技」：飞书租户 mammotion 首页自报 tenant_name=深圳库犸创新科技集团有限公司、title「加入深圳库犸科技有限公司」（Mammotion，庭院割草机器人）；首页正文「库犸」21 处、「容知」0 处，岗位在深圳 / 杜塞尔多夫。容知日新（688768）是另一家公司，未接。$md$
 where source_url = 'https://mammotion.jobs.feishu.cn/index/position'
   and company = '容知日新';

update sources
   set company = '英科再生',
       industry = '再生塑料',
       industry_group = '制造/工业',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 公司名由「英科医疗」纠正为「英科再生」：飞书租户 global-intco 的公开门户 title「英科再生社会招聘官网」（688087），87 个岗里「手套」0 个，有再生塑料粒子 / 回收设备 / 框条。租户是集团共用的（tenant_name=英科）：另有 381 个岗不在这个门户上（淮北 / 安庆 / 九江，正文有手套、丁腈），是英科医疗（300677）一侧的，公开门户地址没查到，英科医疗未接。门户上另有 15 个淮北「凯泽」岗，跟着门户名走。$md$
 where source_url = 'https://global-intco.jobs.feishu.cn/index/position'
   and company = '英科医疗';

update sources
   set company = '千曙科技',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 公司名由「千署科技」纠正为「千曙科技」：飞书租户 tranxmart 首页自报 tenant_name=千曙科技（千方科技的自动驾驶子公司），原名写错一个字。$md$
 where source_url = 'https://tranxmart.jobs.feishu.cn/index/position'
   and company = '千署科技';

-- ② 道旅科技停用
update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 停用：门户已不存在。租户首页 https://didatravel.jobs.feishu.cn/ 返回 404，浏览器里是 Not Found；最近 4 轮都是「抓到 0 个、记成功」，香港库 0 个在招。对方重新开门户后按新地址重新接。$md$
 where source_url = 'https://didatravel.jobs.feishu.cn/index/position'
   and company = '道旅科技 Dida'
   and enabled;

-- ③ 画像「千署科技」→「千曙科技」（同一家），登记旧写法为别名；公司主体同步改名
update company_profiles
   set company = '千曙科技',
       aliases = case when '千署科技' = any(coalesce(aliases, '{}'))
                      then aliases
                      else coalesce(aliases, '{}') || array['千署科技'] end,
       updated_at = now()
 where company = '千署科技'
   and not exists (select 1 from company_profiles where company = '千曙科技');

update insight_subjects s
   set name = '千曙科技',
       updated_at = now()
  from company_profiles p
 where p.id = s.company_id
   and p.company = '千曙科技'
   and s.kind = 'company'
   and s.origin = 'derived_title'
   and s.name = '千署科技';

-- ④ 「容知日新」「英科医疗」画像：派生指标撤下，公司主体在招数归零（画像与官方事实保留）
update insight_items
   set status = 'retired',
       updated_at = now()
 where company_id in (select id from company_profiles where company in ('容知日新', '英科医疗'))
   and origin = 'derived'
   and status = 'active';

update insight_subjects
   set job_count = 0,
       updated_at = now()
 where company_id in (select id from company_profiles where company in ('容知日新', '英科医疗'))
   and kind = 'company'
   and origin = 'derived_title'
   and job_count <> 0;

-- 终态断言：任何一条不成立，整份迁移回滚
do $$
begin
  if (select count(*) from sources
       where (source_url = 'https://mammotion.jobs.feishu.cn/index/position' and company = '库犸科技')
          or (source_url = 'https://global-intco.jobs.feishu.cn/index/position' and company = '英科再生')
          or (source_url = 'https://tranxmart.jobs.feishu.cn/index/position' and company = '千曙科技')) <> 3 then
    raise exception '323: 三条源没有都改成新名';
  end if;
  if exists (select 1 from sources
              where (source_url like 'https://mammotion.jobs.feishu.cn/%' and company <> '库犸科技')
                 or (source_url like 'https://global-intco.jobs.feishu.cn/%' and company <> '英科再生')
                 or (source_url like 'https://tranxmart.jobs.feishu.cn/%' and company <> '千曙科技')) then
    raise exception '323: 这三个租户下还有源挂着别的名字';
  end if;
  if exists (select 1 from sources where enabled and company in ('容知日新', '英科医疗', '千署科技')) then
    raise exception '323: 还有 enabled 的源挂着旧名';
  end if;
  if exists (select 1 from sources
              where source_url = 'https://didatravel.jobs.feishu.cn/index/position' and enabled) then
    raise exception '323: 道旅科技的源还是 enabled';
  end if;
  if (select count(*) from company_profiles where company = '千曙科技') <> 1
     or exists (select 1 from company_profiles where company = '千署科技') then
    raise exception '323: 画像「千署科技」→「千曙科技」没有落成恰好一个';
  end if;
  if exists (select 1
               from insight_subjects s
               join company_profiles p on p.id = s.company_id
              where p.company = '千曙科技' and s.kind = 'company' and s.name <> '千曙科技') then
    raise exception '323: 「千曙科技」画像下的公司主体还叫旧名';
  end if;
  if exists (select 1
               from insight_items i
               join company_profiles p on p.id = i.company_id
              where p.company in ('容知日新', '英科医疗')
                and i.origin = 'derived'
                and i.status = 'active') then
    raise exception '323: 错名画像下还有在展的派生指标';
  end if;
end $$;

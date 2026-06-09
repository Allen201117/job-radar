-- 105 — 外企「中英文两种写法」重复源去重（岗位并入规范名 + 停用重复 source）
-- ============================================================================
-- 背景：部分外企被分别以两种写法各建了一行 source（中英顺序颠倒 / 纯英文 vs 中英混排），
--   导致同一公司在 jobs 库以两个 company 名出现、并产生重复岗位（前端按公司筛选时分裂）。
--   经 live 核对（service-role 直连 PostgREST）确认：每组两行指向同一招聘系统（同 greenhouse
--   板块 / 同 workday 租户，仅 URL 大小写不同），且「被去重源」的岗位按 标题+城市 归并后**全部**
--   已被「保留源」覆盖（D_unique=0），删除不丢任何真实岗位；保留源继续每日抓取会自动补回。
-- 处置：保留「中文 English」规范写法的一行；把重复写法的岗位按 jd_url / 标题+城市 去重后并入规范名，
--   再停用（enabled=false；crawler 仅抓 enabled）重复 source 行。AstraZeneca 例外见 B 段。
-- Idempotent：重复写法的 company 清零后再跑 delete/update 均 0 行；source 重复 disable 为幂等。
-- ============================================================================

-- ── A. 同一招聘系统的「中英不同写法」重复对：岗位去重并入规范名 + 停用重复源 ──
do $$
declare
  r record;
begin
  for r in (values
      ('Airbnb',               '爱彼迎 Airbnb'),       -- greenhouse 同板块（board slug 大小写不敏感）
      ('Baxter 百特',           '百特 Baxter'),          -- workday 同租户 baxter.wd1
      ('HPE 慧与',              '慧与 HPE'),             -- workday 同租户 hpe.wd5
      ('Marsh McLennan 威达信',  '达信 Marsh McLennan'),   -- workday 同租户 mmc.wd1（规范取「中文 English」格式的现有行）
      ('Riot Games',           '拳头游戏 Riot Games'),    -- greenhouse 同板块
      ('Thermo Fisher 赛默飞',   '赛默飞 Thermo Fisher')    -- workday 同租户 thermofisher.wd5
    ) as t(old_name, new_name)
  loop
    -- 1) 删除与规范名 jd_url 完全相同的重复岗位（greenhouse 返回同一 absolute_url）
    delete from jobs d
     where d.company = r.old_name
       and exists (select 1 from jobs c where c.company = r.new_name and c.jd_url = d.jd_url);
    -- 2) 删除与规范名「同岗位」（标题+城市相同、仅 URL 大小写不同）的重复岗位（workday 站名大小写差异）
    delete from jobs d
     where d.company = r.old_name
       and exists (select 1 from jobs c
                    where c.company = r.new_name
                      and c.title = d.title
                      and coalesce(c.location, '') = coalesce(d.location, ''));
    -- 3) 剩余（规范名没有的独有岗位，本次核对为 0）并入规范名，避免任何真实岗位丢失
    update jobs set company = r.new_name where company = r.old_name;
    -- 4) 停用重复写法的 source 行（每公司仅 1 行，按 company+segment 精确命中；规范名行不受影响）
    update sources set enabled = false
     where company = r.old_name and segment = 'foreign';
  end loop;
end $$;

-- ── B. AstraZeneca / 阿斯利康：两行指向**不同**招聘系统（workday 大陆岗 463 / eightfold 香港岗 10），
--    岗位互补不重叠（role_dup=0）→ 不停用任何一行，只统一显示名以消除前端公司分裂。 ──
update jobs set company = '阿斯利康 AstraZeneca' where company = 'AstraZeneca';
update sources set company = '阿斯利康 AstraZeneca'
 where company = 'AstraZeneca' and adapter_name = 'eightfold' and segment = 'foreign';

-- ── C. 同名（写法完全一致）但 URL 大小写重复的 greenhouse 源：停用 0 岗的冗余行（其每次抓取都会
--    与小写孪生源的岗位撞唯一键而失败）。同名不分裂、唯一键已防重岗，故仅停用冗余 source、不动 jobs。
--    安全网：仅当该公司仍有 >1 个 enabled 源时才停用，绝不停用某公司最后一个 enabled 源。 ──
update sources s set enabled = false
 where s.source_url = 'https://boards-api.greenhouse.io/v1/boards/Elastic/jobs?content=true'
   and (select count(*) from sources s2 where s2.company = s.company and s2.enabled) > 1;
update sources s set enabled = false
 where s.source_url = 'https://boards-api.greenhouse.io/v1/boards/Hasbro/jobs?content=true'
   and (select count(*) from sources s2 where s2.company = s.company and s2.enabled) > 1;
update sources s set enabled = false
 where s.source_url = 'https://boards-api.greenhouse.io/v1/boards/Mongodb/jobs?content=true'
   and (select count(*) from sources s2 where s2.company = s.company and s2.enabled) > 1;
update sources s set enabled = false
 where s.source_url = 'https://boards-api.greenhouse.io/v1/boards/Stripe/jobs?content=true'
   and (select count(*) from sources s2 where s2.company = s.company and s2.enabled) > 1;
update sources s set enabled = false
 where s.source_url = 'https://boards-api.greenhouse.io/v1/boards/Zscaler/jobs?content=true'
   and (select count(*) from sources s2 where s2.company = s.company and s2.enabled) > 1;

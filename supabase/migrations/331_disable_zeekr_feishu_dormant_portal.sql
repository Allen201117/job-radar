-- 331 — 停用「极氪汽车」飞书源：2021 年开了就没再用的门户
--
-- 现象：company=「极氪汽车」、source_url=https://zeekrlife.jobs.feishu.cn/index/position 的源，2026-10-12 00:23 UTC
--   由自动扩源入库（备注「live探活 1 岗」）。每周归属复核判它「对不上」；线上按公司筛「极氪」只出 1 张卡：
--   「绩效经理 · 杭州」，发布日 2021-11-13。
--
-- 核实（2026-10-12：浏览器实开门户首页与详情页 + 列表 / 详情接口 + 香港库全集）：
--   · 租户是极氪自己的（tenant_name=极氪智能科技有限公司，域名与官网 zeekrlife.com 同名），但门户早就不用了：
--     带门户头取到 1 个岗「绩效经理」（2021-11-13 发布），不带头取到 1 个「测试职位（勿操作勿投递）」（2021-11-10 发布）；
--     门户编号里的时间戳是 2021-11-08；页面是飞书默认模板。门户标题「加入浙江领克汽车实业有限公司」与微信分享标题、
--     副标题同名，是建门户时存下的文案。没看到集团共用租户那种「另一侧还有一批岗」。
--   · 极氪官网「关于极氪 → 加入我们」打开的是 app.mokahr.com/social-recruitment/geely/102003（标题「极氪科技集团 - 社会招聘」）。
--     用 MokaAdapter 翻全 831 个岗（= 门户自报数），830 个已在库里在招，挂在「浙江吉利控股集团」那条源（geely/96123）名下，
--     岗位编号逐个相同；另 1 个库里没有。
--   · 必投台账里「极氪」本来就靠吉利门户里标题带极氪的岗算覆盖（138 个健康岗），停掉这条源不新增缺口。
--   · 这条源名下只有 1 行，没有用户收藏 / 投递。
--
-- 处理：停用（保留行可回滚）。香港库那 1 行由 remove-jobs-by-url-prefix 标 removed（可逆）。
--   自动建出来的「极氪汽车」画像是空的（0 条说法），不动。
--   ⚠️ 别把 geely/102003 加成极氪的源：它和 geely/96123 是同一批岗，加了就是同一个岗两张卡。

update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 停用：2021 年开了就没再用的门户。租户是极氪自己的（tenant_name=极氪智能科技有限公司），但公开门户上只有 1 个岗「绩效经理」，发布于 2021-11-13，另有 1 个「测试职位（勿操作勿投递）」；门户建于 2021-11-08，页面是飞书默认模板，标题「加入浙江领克汽车实业有限公司」是建门户时存下的文案。极氪官网「加入我们」指向 app.mokahr.com/social-recruitment/geely/102003（极氪科技集团 - 社会招聘，831 岗），其中 830 个已在「浙江吉利控股集团」那条源（geely/96123）名下在招、岗位编号相同 —— 不要把 102003 另接成源（同一个岗两张卡）。对方重新启用这个飞书门户再重新评估。$md$
 where source_url = 'https://zeekrlife.jobs.feishu.cn/index/position'
   and company = '极氪汽车'
   and enabled;

-- 终态断言：任何一条不成立，整份迁移回滚
do $$
begin
  if (select count(*) from sources
       where source_url = 'https://zeekrlife.jobs.feishu.cn/index/position' and company = '极氪汽车') <> 1 then
    raise exception '331: 极氪汽车这条飞书源不是恰好 1 行';
  end if;
  if exists (select 1 from sources
              where source_url like 'https://zeekrlife.jobs.feishu.cn/%' and enabled) then
    raise exception '331: zeekrlife.jobs.feishu.cn 下还有 enabled 的源';
  end if;
end $$;

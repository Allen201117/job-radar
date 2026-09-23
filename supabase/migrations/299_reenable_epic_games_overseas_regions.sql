-- 299: 重新启用 Epic Games（Greenhouse），抓取地区放开到海外口径 {CN,US,SG,Remote}。
--
-- 当初为什么停：迁移 146（2026-06-16「MVP 精>量」）以「面向中国求职者、板上抓不到任何在华岗」
-- 为由停用，当时 regions 只有 {CN}。
-- 为什么现在不成立（2026-09-23 live 实测）：
--   · 产品 2026-07-02 起覆盖海外（US/SG/Remote），Epic Games 在海外必投清单
--     crawler/targets_overseas_must_apply.json 里；海外扩源道每天探活都通过、却因这行 disabled 被跳过。
--   · 板上对方自报 150 岗；按 {CN,US,SG,Remote} 过滤后 65 岗全过质量门（US 63 + 上海 2，台湾 0），
--     详情页 epicgames.com/careers/jobs/<id>?gh_jid=<id> 实开可见完整 JD。只按 {CN} 也已有 2 个上海岗。
-- 可逆：改回 enabled=false 即可。幂等：重复执行无副作用。只动这一行（id + source_url 双重限定）。
update sources
   set enabled = true,
       regions = '{CN,US,SG,Remote}'
 where id = '2468f836-58c3-4acc-8f2e-63d2992dc099'
   and source_url = 'https://boards-api.greenhouse.io/v1/boards/epicgames/jobs?content=true';

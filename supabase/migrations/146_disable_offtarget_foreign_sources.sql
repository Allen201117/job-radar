-- 146: 下架与目标用户无关、且 0 产出的外企源（MVP 阶段「精 > 量」：砍低质量，见 CLAUDE.md 核心原则 #3）。
-- 这些源面向中国求职者的本产品而言是噪声——抓不到任何在华岗位（live 审计 0 active）。
-- 可逆：仅置 enabled=false，保留行；要复活改回 true 即可。幂等：重复执行无副作用。

-- smartrecruiters 适配器整体 0 产出（6/6 源均无在华岗，且含重复行 Arista×2 / Western Digital×2）。
update sources set enabled = false where adapter_name = 'smartrecruiters';

-- greenhouse 上的纯美企（板在美、无在华岗）；不动其余在产出的 greenhouse 源。
update sources set enabled = false
where adapter_name = 'greenhouse'
  and company in ('Flexport', 'Figma', 'Reddit', 'Scopely', 'Epic Games', 'Airtable');

-- workday 上 0 产出的外企（无在华岗）；不动其余在产出的 workday 源。
update sources set enabled = false
where adapter_name = 'workday'
  and company in ('礼来 Eli Lilly', '帝亚吉欧 Diageo');

-- ashby 上的外企（无在华岗）。
update sources set enabled = false
where adapter_name = 'ashby' and company = 'Snowflake';

-- 108 — 清理外企「中英文双名」重复源(已先在 prod live 执行,此处存档 + 幂等)
-- 背景:同一公司存在两条 source（中英文写法不同）。live 查证每组「英文在前」变体均 0 在华岗
--       （dead / dup 端点），「中文 English」规范源已有岗位 → 停用变体不丢数据,
--       使每家外企只留一个规范源/名,前端按公司筛选不再分裂。
-- 幂等:对已停用行再次执行为 no-op。

update sources set enabled = false
where segment = 'foreign'
  and company in (
    'Airbnb',                  -- 规范源: 爱彼迎 Airbnb
    'Apple（中国区）',          -- 规范源: Apple（且与之同 source_url,真重复）
    'Baxter 百特',             -- 规范源: 百特 Baxter
    'HPE 慧与',                -- 规范源: 慧与 HPE
    'Marsh McLennan 威达信',   -- 规范源: 达信 Marsh McLennan
    'Riot Games',              -- 规范源: 拳头游戏 Riot Games
    'Thermo Fisher 赛默飞'     -- 规范源: 赛默飞 Thermo Fisher
  );

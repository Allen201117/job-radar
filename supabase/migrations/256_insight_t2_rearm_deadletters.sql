-- 256：把 T2 官方事实层的「死信」公司重新放回队列（一次性重置 insight_fail_count）。
--
-- 为什么要重置（证据，2026-09-17 live 实测）：
--   · `insight_fail_count >= 3` 的公司**永久**掉出 T2 队列（idx_company_profiles_insight_queue
--     的部分索引条件 + fetch_queue 的 .lt("insight_fail_count", 3)）。线上 1,383 家画像里
--     **377 家（27%）**卡在这个状态，其中 332 家现在仍有在招岗、是真实需求公司。
--   · 这 377 家**不是**「Wikidata 没有它们」：随机抽 25 家用现有客户端 live 探，
--     9 家（36%）当场查得到，0 报错 —— Nike / TCL / 大疆创新 / Snowflake 都在里面。
--     再抽 30 家用**改名字归一之后**的客户端探，10 家（33%）返回了结构化事实。
--   · 它们当初是怎么死的：`enrich_company` 把**任何**异常都记一次 fail_count，而
--     Wikidata 对我们 4 线程并发返 429「Your bot is making too many requests」。
--     2026-09-09~11 三晚就回了 1,504 次 429，把另外 252 家推到了 1~2 次失败。
--     那是「我们被限流」，不是「对方没这家公司」。
--
-- 同一批已修的代码（不修就是重置完再死一次）：
--   · crawler/wikidata.py：全进程节流 + 尊重 Retry-After 的重试（多线程各自 sleep 等于没节流）；
--     公司名降解（全称 → 品牌短名）+ 名字门 + 实体类型门。
--   · crawler/insight_backlog.py：限流/超时/5xx 不计死信；成功与「查无」都把 fail_count 清零。
--
-- 幂等：重复执行只是把已经是 0 的值再写成 0。不动 insight_checked_at ——
-- 队列按 TTL(90 天) 取，重置后它们会在各自 TTL 到期时自然被取到，不会一夜之间涌进来压垮 Wikidata。
-- ⚠️ 但从没成功过的那批 checked_at 是旧的/为空，会较快入队，这正是我们要的。

update public.company_profiles
   set insight_fail_count = 0,
       updated_at = now()
 where insight_fail_count > 0;

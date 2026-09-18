-- 282 — audit_results 加明细列。
-- SQL 类检查（audit_runner.py）恒不写它（值本身就是全部信息，返回单个数值，没有明细）。
-- watchdog 桥接的规则类检查（ops_watchdog.py 直接写 audit_results，见「链路层」段）会
-- 把该轮命中的具体条目（最多 30 条 title/key）塞进这里，晨报/排查时不用回头翻 GitHub issue。
-- 可空：老的 SQL 类检查行永远是 NULL，不是「查不到」，是「这类检查没有明细」。

alter table public.audit_results add column if not exists detail jsonb;

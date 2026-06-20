-- ============================================================
-- 157 — 给存量 T3 经验洞察补 valid_until（保鲜补漏）
-- ============================================================
-- 设计见 docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md（即时性闸）。
-- 幂等，push 后 migrate.yml 自动应用。
--
-- T3 经验洞察(origin=public_web)早先写入未带 valid_until → 过期下架巡检(insight_sweep)漏网、
-- 永不自动退役。本迁移给存量补 valid_until = last_verified_at + 1 年（与新写入口径一致），
-- 使过期巡检能正常退役老聚合；180 天复核会续期。仅填 null、不动已有值，故幂等。

update insight_items
set valid_until = (last_verified_at + interval '1 year')::date
where origin = 'public_web'
  and valid_until is null
  and last_verified_at is not null;

"use strict";
/**
 * 「刷新公司库」节流 / 幂等判定（纯函数，可单测）。
 *
 * 解决对抗式审查 blocker：一次点击不得无限催生 GitHub Actions job。
 * 给定该用户近期 company_refresh runs（任意顺序）+ now（ms）+ 窗口配置，判定本次点击：
 *   - reuse:    有在飞 run（queued/running 且未 stale）→ 复用其 run_id（挡快速连点 / 重复 dispatch）
 *   - cooldown: 冷却窗口内刚刷过（最近一条已结束/在飞但仍在窗口）→ 拒绝（路由返回 429 + Retry-After）
 *   - dispatch: 放行，新建 + 触发
 *
 * 真正的查 DB / dispatch 留在路由层，本函数只做判定，便于单测不打 DB。
 */

const DEFAULT_COOLDOWN_MS = 10 * 60 * 1000; // 冷却：10min 内不重复刷（防刷爆 Actions 队列）
const DEFAULT_STALE_MS = 20 * 60 * 1000; // 在飞 run 超过此龄视为已死（CI 崩溃），不再复用、放行重刷
const IN_FLIGHT = new Set(["queued", "running"]);

function _ms(value) {
  if (value == null) return NaN;
  if (typeof value === "number") return value;
  const t = Date.parse(String(value));
  return Number.isNaN(t) ? NaN : t;
}

// recentRuns: 该用户近期 company_refresh run 行（需含 status + created_at/started_at）
// nowMs: 当前时间戳(ms)；opts: cooldownMs / staleMs。
// 返回 action: 'reuse'|'cooldown'|'dispatch'（+ run / retryAfterSec）。
function evaluateRefreshThrottle(recentRuns, nowMs, opts = {}) {
  const cooldownMs = opts.cooldownMs != null ? opts.cooldownMs : DEFAULT_COOLDOWN_MS;
  const staleMs = opts.staleMs != null ? opts.staleMs : DEFAULT_STALE_MS;

  const runs = (Array.isArray(recentRuns) ? recentRuns : [])
    .map((r) => ({ run: r, ts: _ms(r && (r.created_at || r.started_at)) }))
    .filter((x) => Number.isFinite(x.ts))
    .sort((a, b) => b.ts - a.ts);

  // 1) 在飞 run（未 stale）→ 复用，挡住快速连点与重复 dispatch。
  const live = runs.find(
    (x) => IN_FLIGHT.has(String(x.run.status || "")) && nowMs - x.ts < staleMs,
  );
  if (live) return { action: "reuse", run: live.run };

  // 2) 冷却窗口内最近有 run（含已死的在飞 run 若仍在冷却窗内）→ 拒绝。
  const last = runs[0];
  if (last && nowMs - last.ts < cooldownMs) {
    const retryAfterSec = Math.max(1, Math.ceil((cooldownMs - (nowMs - last.ts)) / 1000));
    return { action: "cooldown", run: last.run, retryAfterSec };
  }

  // 3) 放行。
  return { action: "dispatch" };
}

module.exports = { evaluateRefreshThrottle, DEFAULT_COOLDOWN_MS, DEFAULT_STALE_MS };

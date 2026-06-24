// 强度推导（04 spec §3）：手动近期优先 > 行为自调 > 默认 active（蜜月期）。纯函数，可测。
// 强度只影响 daily_limit / 分区取舍 / 推送频率 / 入选门槛，**不影响 profile_ready、不裁剪关键提醒**。
import type { RadarIntensity } from "./types";

// 手动设置的尊重窗口（天）：窗口内用手动值，超出转行为自调。
const MANUAL_HONOR_DAYS = 30;
// 行为自调阈值（天）：近 3 天打开过算 active；超 14 天未打开算长期未来 → passive。
const RECENT_OPEN_DAYS = 3;
const STALE_OPEN_DAYS = 14;

export interface ResolveIntensityInput {
  manual: RadarIntensity | null; // user_preferences.radar_intensity（仅当 source='user' 时有意义）
  manualAgeDays: number | null; // 手动设置距今天数（无手动则 null）
  lastOpenedAt: string | null; // user_radar_state.last_opened_at
  recentActionCount14d: number; // job_actions 近 14 天动作数（saved/applied/ignored/opened）
  hasTargetCompanies: boolean; // 是否关注了公司（观望用户的「仍在意」信号）
  now: Date;
}

export function resolveIntensity(
  input: ResolveIntensityInput
): { intensity: RadarIntensity; source: "user" | "auto" | "default" } {
  const { manual, manualAgeDays, lastOpenedAt, recentActionCount14d, hasTargetCompanies, now } = input;

  // 1. 近期手动设过 → 尊重手动值（< 30 天）。30 天及以上转行为自调。
  if (manual !== null && manualAgeDays !== null && manualAgeDays < MANUAL_HONOR_DAYS) {
    return { intensity: manual, source: "user" };
  }

  // 2. 行为自调（存在任何行为信号才走 auto）
  let daysSinceOpen: number | null = null;
  if (lastOpenedAt) {
    const t = new Date(lastOpenedAt).getTime();
    if (!Number.isNaN(t)) daysSinceOpen = (now.getTime() - t) / 86_400_000;
  }
  const hasBehaviorSignal = recentActionCount14d > 0 || daysSinceOpen !== null;
  if (hasBehaviorSignal) {
    if (recentActionCount14d > 0) return { intensity: "active", source: "auto" }; // 有动作 → 回弹 active
    if (daysSinceOpen !== null && daysSinceOpen <= RECENT_OPEN_DAYS) return { intensity: "active", source: "auto" };
    if (daysSinceOpen !== null && daysSinceOpen > STALE_OPEN_DAYS) return { intensity: "passive", source: "auto" };
    // 打开过但 3–14 天、无动作：关注了公司=仍在观望 → active；否则衰减 passive
    return { intensity: hasTargetCompanies ? "active" : "passive", source: "auto" };
  }

  // 3. 无任何信号（新用户）→ 默认 active（蜜月期）
  return { intensity: "active", source: "default" };
}

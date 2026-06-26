// 偏好 PUT 的纯输入校验/归一（§8.1）。单一事实来源：/api/preferences 用它，node --test 直接测它。
// 不接受客户端 user_id；radar_intensity 仅 active/passive；数组 trim/去空/去重 ≤30 项、单项 ≤80 字；daily_limit 5–30。
import type { RadarIntensity } from "./types";

const MAX_ITEMS = 30;
const MAX_LEN = 80;

export function cleanArray(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of v) {
    if (typeof raw !== "string") continue;
    const t = raw.trim().slice(0, MAX_LEN);
    if (!t) continue;
    const k = t.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(t);
    if (out.length >= MAX_ITEMS) break;
  }
  return out;
}

export function clampDailyLimit(v: unknown): number {
  const n = typeof v === "number" && Number.isFinite(v) ? Math.round(v) : 20;
  return Math.max(5, Math.min(30, n));
}

export interface ParsedPreferences {
  prefs: {
    target_locations: string[];
    target_roles: string[];
    target_keywords: string[];
    exclude_keywords: string[];
    target_companies: string[];
    target_industries: string[];
    daily_limit: number;
  };
  // 本次提交是否改强度：null=未改（不动既有值）；否则手动覆盖（写 source='user'）。
  intensity: RadarIntensity | null;
}

export type PreferencesParseError = "invalid_json" | "validation_failed";

export function parsePreferencesInput(
  body: unknown
): { ok: true; value: ParsedPreferences } | { ok: false; error: PreferencesParseError } {
  if (typeof body !== "object" || body === null) return { ok: false, error: "invalid_json" };
  const b = body as Record<string, unknown>;

  // 不接受客户端 user_id：一律用服务端当前用户。
  if ("user_id" in b) return { ok: false, error: "validation_failed" };

  // 强度：undefined=未改；active/passive 合法；其它（含 radar_mode 老值）非法。
  let intensity: RadarIntensity | null = null;
  if (b.radar_intensity !== undefined) {
    if (b.radar_intensity !== "active" && b.radar_intensity !== "passive") {
      return { ok: false, error: "validation_failed" };
    }
    intensity = b.radar_intensity;
  }

  return {
    ok: true,
    value: {
      prefs: {
        target_locations: cleanArray(b.target_locations),
        target_roles: cleanArray(b.target_roles),
        target_keywords: cleanArray(b.target_keywords),
        exclude_keywords: cleanArray(b.exclude_keywords),
        target_companies: cleanArray(b.target_companies),
        target_industries: cleanArray(b.target_industries),
        daily_limit: clampDailyLimit(b.daily_limit),
      },
      intensity,
    },
  };
}

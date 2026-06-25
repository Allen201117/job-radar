// 动作 / radar-open 接口的纯输入校验（§8.1 / §7.2）——抽成纯函数以便 node --test 覆盖（路由本体需 Next 运行时，难单测）。
// 路由在 requireUser() 之后调用这些；鉴权(401)与归属由 requireUser + set_job_primary_action(auth.uid()) + RLS 保证。
import { IGNORE_REASON_CODES } from "./feedback";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PRIMARY = new Set(["saved", "ignored", "applied"]);

export interface ActionInput {
  action: "saved" | "ignored" | "applied" | null;
  reasonCode: string | null;
  reasonText: string | null;
}

export type ParseResult<T> = { ok: true; value: T } | { ok: false; error: string };

export function parseActionInput(jobId: string, body: any): ParseResult<ActionInput> {
  if (!UUID_RE.test(jobId)) return { ok: false, error: "invalid_job_id" };

  // §3.4：客户端不得自带 job_snapshot / user_id —— snapshot 由服务端从权威岗位行生成、归属由 auth.uid() 定。
  // 与 /api/preferences 同口径（preferences-input 拒 user_id），明确 400 而非静默忽略。
  if (body && typeof body === "object" && ("job_snapshot" in body || "user_id" in body)) {
    return { ok: false, error: "validation_failed" };
  }

  const action = body?.action ?? null;
  if (action !== null && !PRIMARY.has(action)) return { ok: false, error: "invalid_action" };

  if (typeof body?.reason_text === "string" && body.reason_text.length > 200) {
    return { ok: false, error: "reason_text_too_long" };
  }

  let reasonCode: string | null = null;
  let reasonText: string | null = null;
  if (action === "ignored") {
    reasonCode = typeof body?.reason_code === "string" ? body.reason_code : null;
    if (!reasonCode || !IGNORE_REASON_CODES.has(reasonCode)) return { ok: false, error: "reason_required" };
    if (reasonCode === "other") reasonText = String(body?.reason_text || "").trim() || null;
  }

  return { ok: true, value: { action, reasonCode, reasonText } };
}

export interface RadarOpenInput {
  lastFeedGeneratedAt: string;
  feedCount: number;
}

export function parseRadarOpenInput(body: any, nowMs: number): ParseResult<RadarOpenInput> {
  const g = body?.generated_at ? new Date(body.generated_at).getTime() : NaN;
  if (Number.isNaN(g) || g > nowMs + 5 * 60 * 1000) return { ok: false, error: "invalid_generated_at" };

  const feedCount = Number(body?.feed_count);
  if (!Number.isFinite(feedCount) || feedCount < 0 || feedCount > 30) {
    return { ok: false, error: "invalid_feed_count" };
  }

  return { ok: true, value: { lastFeedGeneratedAt: new Date(g).toISOString(), feedCount: Math.round(feedCount) } };
}

export function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}

// ============================================================
// 校招洞察 P2 — admin 录入校验（纯函数）。只做结构/枚举门；
// immutable 纪律在 API 写路径（POST 只建、PATCH 只碰可变字段）。
// 只 import 类型（被 transpile 擦除）或本地常量；禁 @/ 别名运行时 import（见 Global Constraints）。
// ============================================================

const SEASONS = ["秋招", "春招"];
const BATCHES = ["提前批", "正式批", "补录", "实习转正"];
const EVENTS = ["开放", "截止", "黄金期", "结束"];
const TIME_TYPES = ["精确日期", "日期范围", "月", "历史规律"];
const CONFIDENCES = ["high", "medium", "low"];

function badMonth(v: any): boolean {
  return v != null && (typeof v !== "number" || v < 1 || v > 12);
}

export function validateCycleInput(
  body: any,
): { ok: true; fields: Record<string, any> } | { ok: false; error: string } {
  const b = body || {};
  const companyId = String(b.company_id || "").trim();
  const gradClass = String(b.grad_class || "").trim();
  const valueText = String(b.value_text || "").trim();
  if (!companyId) return { ok: false, error: "missing_company_id" };
  if (!gradClass) return { ok: false, error: "missing_grad_class" };
  if (!valueText) return { ok: false, error: "missing_value_text" };
  if (!SEASONS.includes(b.season)) return { ok: false, error: "invalid_season" };
  if (!BATCHES.includes(b.batch)) return { ok: false, error: "invalid_batch" };
  if (!EVENTS.includes(b.event)) return { ok: false, error: "invalid_event" };
  if (!TIME_TYPES.includes(b.time_expr_type)) return { ok: false, error: "invalid_time_expr_type" };
  if (badMonth(b.month_start) || badMonth(b.month_end)) return { ok: false, error: "invalid_month" };
  if (b.confidence != null && !CONFIDENCES.includes(b.confidence)) return { ok: false, error: "invalid_confidence" };
  // 精确日期只接受可复查官方证据（P3 门）
  if (b.time_expr_type === "精确日期" && !String(b.evidence_url || "").trim()) {
    return { ok: false, error: "exact_date_requires_evidence" };
  }
  return {
    ok: true,
    fields: {
      company_id: companyId,
      grad_class: gradClass,
      season: b.season,
      batch: b.batch,
      event: b.event,
      time_expr_type: b.time_expr_type,
      value_text: valueText,
      month_start: b.month_start ?? null,
      month_end: b.month_end ?? null,
      date_start: b.date_start || null,
      date_end: b.date_end || null,
      confidence: b.confidence || "medium",
      evidence_url: String(b.evidence_url || "").trim() || null,
      evidence_excerpt: String(b.evidence_excerpt || "").trim() || null,
      source_kind: b.source_kind || "manual_curation",
    },
  };
}

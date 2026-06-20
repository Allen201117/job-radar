// ============================================================
// 轻量自有埋点（零分析 SDK）。
// 纯函数与写入封装同构、无外部依赖，便于在浏览器、API 与 admin 统计间复用。
// 浏览器端 fire-and-forget；服务端可 await 保序。任何失败只 console.warn，不影响业务主流程。
// ============================================================

export const MAX_EVENT_LENGTH = 64;
export const MAX_PAYLOAD_BYTES = 4096;
export const RESUME_RULE_MODEL = "rule-v1";

const LATENCY_BUCKETS = [
  "pending",
  "lt_500ms",
  "500_1499ms",
  "1500_2999ms",
  "3000_9999ms",
  "gte_10000ms",
] as const;

const RESUME_ERROR_CODES = new Set([
  "llm_not_configured",
  "llm_auth_error",
  "llm_insufficient_balance",
  "llm_bad_json",
  "llm_empty",
  "llm_network_error",
  "llm_rate_limited",
  "llm_bad_request",
  "llm_http_error",
  "llm_failed",
]);

type ResumeDiagnostics = {
  source: "llm" | "rule";
  model: string;
  latency_bucket: (typeof LATENCY_BUCKETS)[number];
  error_code: string | null;
  extracted_field_count: number;
};

type EventInsertClient = {
  from(table: string): {
    insert(row: {
      user_id: string;
      event: string;
      payload: Record<string, unknown>;
    }): PromiseLike<{ error?: { message?: string } | null }>;
  };
};

// 校验并规范化事件名：非空字符串、去空白、限长；非法返回 null。
export function normalizeEventName(event: unknown): string | null {
  if (typeof event !== "string") return null;
  const trimmed = event.trim();
  if (!trimmed || trimmed.length > MAX_EVENT_LENGTH) return null;
  return trimmed;
}

// 把任意 payload 收敛成可 JSON 序列化的纯对象：
// 非对象/数组/null → {}；丢弃不可序列化值；超 MAX_PAYLOAD_BYTES → {}（防滥用）。
export function sanitizePayload(payload: unknown): Record<string, unknown> {
  if (payload == null || typeof payload !== "object" || Array.isArray(payload)) {
    return {};
  }
  let safe: unknown;
  try {
    const serialized = JSON.stringify(payload);
    if (serialized.length > MAX_PAYLOAD_BYTES) return {};
    safe = JSON.parse(serialized);
  } catch {
    return {};
  }
  if (safe == null || typeof safe !== "object" || Array.isArray(safe)) return {};
  return safe as Record<string, unknown>;
}

export function bucketLatency(milliseconds: number): ResumeDiagnostics["latency_bucket"] {
  const value = Number.isFinite(milliseconds) ? Math.max(0, milliseconds) : 0;
  if (value < 500) return "lt_500ms";
  if (value < 1500) return "500_1499ms";
  if (value < 3000) return "1500_2999ms";
  if (value < 10000) return "3000_9999ms";
  return "gte_10000ms";
}

export function normalizeResumeErrorCode(error: unknown): string {
  const value = error && typeof error === "object"
    ? (error as { code?: unknown; status?: unknown; detail?: unknown; message?: unknown })
    : {};
  const code = typeof value.code === "string" ? value.code : "";
  const status = Number(value.status || 0);
  const detail = typeof value.detail === "string" ? value.detail : "";

  if (code === "llm_not_configured") return code;
  if (code === "llm_bad_json") return code;
  if (code === "llm_network_error") return code;
  if (code === "llm_empty" || value.message === "llm_empty") return "llm_empty";
  if (status === 401 || status === 403) return "llm_auth_error";
  if (status === 402 || /余额不足|insufficient.{0,20}(balance|credit)/i.test(detail)) {
    return "llm_insufficient_balance";
  }
  if (status === 429) return "llm_rate_limited";
  if (status === 400) return "llm_bad_request";
  if (code === "llm_http_error") return "llm_http_error";
  return "llm_failed";
}

function safeDiagnosticModel(value: unknown): string {
  if (typeof value !== "string") return "unknown";
  const model = value.trim();
  return /^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$/.test(model) ? model : "unknown";
}

function safeResumeErrorCode(value: unknown): string | null {
  if (value == null || value === "") return null;
  return typeof value === "string" && RESUME_ERROR_CODES.has(value) ? value : "llm_failed";
}

export function buildResumeDiagnostics(input: unknown): ResumeDiagnostics {
  const value = input && typeof input === "object"
    ? (input as Record<string, unknown>)
    : {};
  const latency = LATENCY_BUCKETS.includes(value.latency_bucket as ResumeDiagnostics["latency_bucket"])
    ? (value.latency_bucket as ResumeDiagnostics["latency_bucket"])
    : "pending";
  const fieldCount = Number(value.extracted_field_count);

  return {
    source: value.source === "rule" ? "rule" : "llm",
    model: safeDiagnosticModel(value.model),
    latency_bucket: latency,
    error_code: safeResumeErrorCode(value.error_code),
    extracted_field_count: Number.isFinite(fieldCount)
      ? Math.max(0, Math.min(999, Math.floor(fieldCount)))
      : 0,
  };
}

export function countExtractedResumeFields(profile: unknown): number {
  const value = profile && typeof profile === "object"
    ? (profile as Record<string, any>)
    : {};
  let count = 0;
  const addValue = (item: unknown) => {
    if (typeof item === "string" && item.trim()) count += 1;
    else if (typeof item === "number" && Number.isFinite(item)) count += 1;
    else if (typeof item === "boolean") count += 1;
  };
  const addStrings = (items: unknown) => {
    if (!Array.isArray(items)) return;
    for (const item of items) addValue(item);
  };
  const addObjects = (items: unknown, fields: string[]) => {
    if (!Array.isArray(items)) return;
    for (const item of items) {
      if (!item || typeof item !== "object") continue;
      for (const field of fields) addValue((item as Record<string, unknown>)[field]);
    }
  };

  addValue(value.headline);
  if (value.basic_info && typeof value.basic_info === "object") {
    addValue(value.basic_info.name);
    addValue(value.basic_info.city);
    addValue(value.basic_info.contact);
  }
  addStrings(value.target_roles);
  addStrings(value.target_locations);
  addStrings(value.skills);
  addStrings(value.industries);
  addValue(value.experience_stage || value.seniority);
  addObjects(value.education, ["school", "degree", "major", "start", "end"]);
  addObjects(value.internships, ["company", "role", "start", "end", "summary"]);
  addObjects(value.projects, ["name", "role", "stack", "outcome"]);

  return count;
}

// 服务端埋点复用 events 表。写入错误只记日志，永不向业务调用方抛出。
export async function trackServerEvent(
  supabase: EventInsertClient,
  userId: string,
  event: string,
  payload?: Record<string, unknown>,
): Promise<void> {
  const name = normalizeEventName(event);
  if (!name || !userId) return;
  try {
    const { error } = await supabase.from("events").insert({
      user_id: userId,
      event: name,
      payload: sanitizePayload(payload),
    });
    if (error) {
      console.warn("[events] insert failed:", error.message || "unknown");
    }
  } catch (error) {
    console.warn("[events] tracking error:", (error as Error).message);
  }
}

// 简历事件只接受严格白名单 diagnostics，调用方即使误传 profile/原文也不会落库。
export async function trackResumeEvent(
  supabase: EventInsertClient,
  userId: string,
  event: string,
  diagnostics: unknown,
): Promise<void> {
  await trackServerEvent(supabase, userId, event, {
    diagnostics: buildResumeDiagnostics(diagnostics),
  });
}

// 服务端：把 POST body 解析校验成干净的 { event, payload }；不合法返回 null。
export function parseEventInput(
  body: unknown,
): { event: string; payload: Record<string, unknown> } | null {
  if (body == null || typeof body !== "object") return null;
  const event = normalizeEventName((body as { event?: unknown }).event);
  if (!event) return null;
  return { event, payload: sanitizePayload((body as { payload?: unknown }).payload) };
}

// admin 统计：把事件行按 event 分组计数，按计数降序、同计数按名称升序（稳定可读）。
export function aggregateEventCounts(
  rows: Array<{ event?: unknown }>,
): Array<{ event: string; count: number }> {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const name = normalizeEventName(row?.event);
    if (!name) continue;
    counts.set(name, (counts.get(name) || 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([event, count]) => ({ event, count }))
    .sort((a, b) => b.count - a.count || a.event.localeCompare(b.event));
}

// 浏览器 fire-and-forget 埋点：永不抛、永不阻塞主流程；失败仅 console.warn 一行。
export function track(event: string, payload?: Record<string, unknown>): void {
  if (typeof window === "undefined") return;
  const name = normalizeEventName(event);
  if (!name) return;
  try {
    const body = JSON.stringify({ event: name, payload: sanitizePayload(payload) });
    // keepalive：即便用户随后跳转/关闭页面，请求也能送达（job_click 会另开标签页）。
    void fetch("/api/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    }).catch((e) => console.warn("[track] post failed:", (e as Error).message));
  } catch (e) {
    console.warn("[track] failed:", (e as Error).message);
  }
}

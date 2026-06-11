// ============================================================
// 轻量自有埋点（零分析 SDK）。
// 纯函数（normalizeEventName / sanitizePayload / parseEventInput / aggregateEventCounts）
// 同构、无外部依赖，便于单测并在浏览器(track) / API(parseEventInput) / admin(aggregate) 间复用。
// 埋点本身 fire-and-forget：任何失败静默吞掉（仅 console.warn 一行），绝不影响用户主流程。
// ============================================================

export const MAX_EVENT_LENGTH = 64;
export const MAX_PAYLOAD_BYTES = 4096;

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

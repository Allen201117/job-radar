"use client";

// ============================================================
// 企业 logo 浏览器侧拉取：微批（一渲染 tick 攒一批公司）+ 会话缓存 + 并发去重。
// 同一公司在多张卡上只请求一次，避免列表渲染时的请求风暴。
// 照抄 lib/insight-client.ts 的 availability 模式。data 是 data URI（后端已 base64），前端直接 <img src>。
// ============================================================

export interface CompanyLogoState {
  data: string | null;
  status: "found" | "not_found";
}

function keyOf(company: string): string {
  return (company || "").trim().toLowerCase();
}

const cache = new Map<string, CompanyLogoState>();
let queue = new Set<string>();
let timer: ReturnType<typeof setTimeout> | null = null;
const subs = new Set<() => void>();

export function getCachedLogo(company: string): CompanyLogoState | null {
  return cache.get(keyOf(company)) ?? null;
}

export function subscribeLogo(fn: () => void): () => void {
  subs.add(fn);
  return () => {
    subs.delete(fn);
  };
}

// 把公司加入下一批 logo 查询（已缓存 / 已排队则跳过）。一个渲染 tick 攒一批，再合并发一次请求。
export function requestCompanyLogo(company: string): void {
  const key = keyOf(company);
  if (!key || cache.has(key) || queue.has(company)) return;
  queue.add(company);
  if (!timer) timer = setTimeout(flush, 16);
}

// 单请求公司数上限（与 /api/company-logos 服务端 slice 对齐）；超出分块多请求，不静默丢。
const CHUNK = 100;

async function fetchChunk(chunk: string[]): Promise<void> {
  try {
    const qs = encodeURIComponent(chunk.join("|"));
    const res = await fetch(`/api/company-logos?companies=${qs}`);
    const json = await res.json();
    const map = (json?.logos || {}) as Record<string, CompanyLogoState>;
    for (const company of chunk) {
      const v = map[company];
      cache.set(
        keyOf(company),
        v && (v.status === "found" || v.status === "not_found")
          ? { data: v.data ?? null, status: v.status }
          : { data: null, status: "not_found" },
      );
    }
  } catch (e) {
    console.error("[logo-client] 拉取失败", (e as Error).message);
    // 失败也写兜底缓存，避免反复重试同一批
    for (const company of chunk) {
      if (!cache.has(keyOf(company))) {
        cache.set(keyOf(company), { data: null, status: "not_found" });
      }
    }
  }
}

async function flush(): Promise<void> {
  timer = null;
  const batch = Array.from(queue);
  queue = new Set();
  if (batch.length === 0) return;
  const chunks: string[][] = [];
  for (let i = 0; i < batch.length; i += CHUNK) chunks.push(batch.slice(i, i + CHUNK));
  try {
    await Promise.all(chunks.map((c) => fetchChunk(c)));
  } finally {
    subs.forEach((fn) => fn());
  }
}

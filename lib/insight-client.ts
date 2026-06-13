"use client";

// ============================================================
// 模块 B — 浏览器侧洞察拉取（带会话内缓存 + 并发去重）
// 同一公司在多张岗位卡上只请求一次，避免列表渲染时请求风暴。
// ============================================================

import type {
  CompanyProfile,
  InsightDimension,
  InsightItemView,
} from "./types";

export interface CompanyInsightResponse {
  ok: boolean;
  company: CompanyProfile | null;
  query: string;
  dimensions: Record<InsightDimension, InsightItemView[]>;
  failure_reason: string | null;
  error?: string;
}

const EMPTY_DIMENSIONS = (): Record<InsightDimension, InsightItemView[]> => ({
  timing: [],
  hiring: [],
  listing: [],
  compensation_intensity: [],
  path: [],
  culture: [],
});

const cache = new Map<string, CompanyInsightResponse>();
const inflight = new Map<string, Promise<CompanyInsightResponse>>();

function keyOf(company: string): string {
  return (company || "").trim().toLowerCase();
}

export function getCachedInsights(company: string): CompanyInsightResponse | null {
  return cache.get(keyOf(company)) || null;
}

export async function fetchCompanyInsights(
  company: string,
): Promise<CompanyInsightResponse> {
  const key = keyOf(company);
  if (!key) {
    return {
      ok: true,
      company: null,
      query: company,
      dimensions: EMPTY_DIMENSIONS(),
      failure_reason: "insight_unverified",
    };
  }
  const cached = cache.get(key);
  if (cached) return cached;
  const pending = inflight.get(key);
  if (pending) return pending;

  const promise = (async (): Promise<CompanyInsightResponse> => {
    try {
      const res = await fetch(`/api/insights?company=${encodeURIComponent(company)}`);
      const data = (await res.json()) as CompanyInsightResponse;
      // 后端可能只返回部分维度键，这里补齐空数组，前端无需判空
      const normalized: CompanyInsightResponse = {
        ok: data.ok !== false,
        company: data.company ?? null,
        query: data.query ?? company,
        dimensions: { ...EMPTY_DIMENSIONS(), ...(data.dimensions || {}) },
        failure_reason: data.failure_reason ?? null,
        error: data.error,
      };
      cache.set(key, normalized);
      return normalized;
    } catch (e) {
      console.error("[insight-client] 拉取失败", (e as Error).message);
      return {
        ok: false,
        company: null,
        query: company,
        dimensions: EMPTY_DIMENSIONS(),
        failure_reason: "insight_unverified",
        error: (e as Error).message,
      };
    } finally {
      inflight.delete(key);
    }
  })();

  inflight.set(key, promise);
  return promise;
}

// ============================================================
// 洞察「可用性」预告（按钮点击前的状态）：real=实录条数 / derived=是否有岗位聚合派生。
// 微批：同一渲染 tick 内多张卡的公司合并成一次 /api/insights/availability 请求，避免请求风暴。
// ============================================================

export interface InsightAvailability {
  real: number;
  derived: boolean;
}

const availCache = new Map<string, InsightAvailability>();
let availQueue = new Set<string>();
let availTimer: ReturnType<typeof setTimeout> | null = null;
const availSubs = new Set<() => void>();

export function getCachedAvailability(company: string): InsightAvailability | null {
  return availCache.get(keyOf(company)) ?? null;
}

export function subscribeAvailability(fn: () => void): () => void {
  availSubs.add(fn);
  return () => {
    availSubs.delete(fn);
  };
}

// 把公司加入下一批可用性查询（已缓存/已排队则跳过）。一个渲染 tick 攒一批，再合并发一次请求。
export function requestInsightAvailability(company: string): void {
  const key = keyOf(company);
  if (!key || availCache.has(key) || availQueue.has(company)) return;
  availQueue.add(company);
  if (!availTimer) availTimer = setTimeout(flushAvailability, 16);
}

// 单请求公司数上限（与 /api/insights/availability 服务端 slice 对齐）；超出则分块多请求，不静默丢。
const AVAIL_CHUNK = 80;

async function fetchAvailabilityChunk(chunk: string[]): Promise<void> {
  try {
    const qs = encodeURIComponent(chunk.join("|"));
    const res = await fetch(`/api/insights/availability?companies=${qs}`);
    const data = await res.json();
    const map = (data?.availability || {}) as Record<string, InsightAvailability>;
    for (const company of chunk) {
      const a = map[company];
      availCache.set(
        keyOf(company),
        a && typeof a.real === "number"
          ? { real: a.real, derived: Boolean(a.derived) }
          : { real: 0, derived: false },
      );
    }
  } catch (e) {
    console.error("[insight-client] 可用性拉取失败", (e as Error).message);
    // 失败也写入兜底，避免反复重试同一批
    for (const company of chunk) {
      if (!availCache.has(keyOf(company))) {
        availCache.set(keyOf(company), { real: 0, derived: false });
      }
    }
  }
}

async function flushAvailability(): Promise<void> {
  availTimer = null;
  const batch = Array.from(availQueue);
  availQueue = new Set();
  if (batch.length === 0) return;
  const chunks: string[][] = [];
  for (let i = 0; i < batch.length; i += AVAIL_CHUNK) chunks.push(batch.slice(i, i + AVAIL_CHUNK));
  try {
    await Promise.all(chunks.map((c) => fetchAvailabilityChunk(c)));
  } finally {
    availSubs.forEach((fn) => fn());
  }
}

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
import type { FirstPartyAggregate } from "./insight-submission";
import type { RecruitmentObservation } from "./recruitment-cycle";

export interface CompanyInsightResponse {
  ok: boolean;
  company: CompanyProfile | null;
  query: string;
  dimensions: Record<InsightDimension, InsightItemView[]>;
  first_party: FirstPartyAggregate;
  failure_reason: string | null;
  recruitment_cycles: RecruitmentObservation[];
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

const EMPTY_FIRST_PARTY = (): FirstPartyAggregate => ({
  visible: false,
  summary: { count: 0, average_rating: null },
  items: [],
});

// 浏览器端缓存（2026-09-08 加 TTL，修 I5）。
//
// 原实现是一个**永不过期、无版本、无清理入口**的 Map：命中即返回。后果有两条，都在生产路径上——
//   ① 管理员/申诉把某条洞察下架后，**同一个页面会话里**再打开公司抽屉仍然拿到旧对象，
//      HTTP 只发过一次；撤回到不了这个展示出口。
//   ② `{ok:false}` 这类错误响应也被 set 进去（只有 fetch 本身抛异常才不写），
//      于是一次后端 500 会把「这家公司没有洞察」永久钉在这个会话里。
// 修法保持最小：给缓存加 TTL，并且只缓存成功响应。TTL 对齐服务端 unstable_cache 的 600s
// （lib/insight-availability-cache.ts / insight-library-store.ts 都是这个量级），
// 再短只是徒增跨洋请求，再长撤回就传不到。
const CACHE_TTL_MS = 600_000;

const cache = new Map<string, { at: number; value: CompanyInsightResponse }>();
const inflight = new Map<string, Promise<CompanyInsightResponse>>();

function readCache(key: string): CompanyInsightResponse | null {
  const hit = cache.get(key);
  if (!hit) return null;
  if (Date.now() - hit.at > CACHE_TTL_MS) {
    cache.delete(key);
    return null;
  }
  return hit.value;
}

/** 发布/撤回/申诉后由调用方主动失效；不传 company 清空全部。 */
export function invalidateCompanyInsights(company?: string): void {
  if (company === undefined) {
    cache.clear();
    return;
  }
  cache.delete(keyOf(company));
}

function keyOf(company: string): string {
  return (company || "").trim().toLowerCase();
}

export function getCachedInsights(company: string): CompanyInsightResponse | null {
  return readCache(keyOf(company));
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
      first_party: EMPTY_FIRST_PARTY(),
      failure_reason: "insight_unverified",
      recruitment_cycles: [],
    };
  }
  const cached = readCache(key);
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
        first_party: data.first_party || EMPTY_FIRST_PARTY(),
        failure_reason: data.failure_reason ?? null,
        recruitment_cycles: data.recruitment_cycles || [],
        error: data.error,
      };
      // 只缓存成功响应：错误响应缓存下来 = 一次后端抖动把「查无洞察」钉死一整个会话。
      if (normalized.ok) cache.set(key, { at: Date.now(), value: normalized });
      return normalized;
    } catch (e) {
      console.error("[insight-client] 拉取失败", (e as Error).message);
      return {
        ok: false,
        company: null,
        query: company,
        dimensions: EMPTY_DIMENSIONS(),
        first_party: EMPTY_FIRST_PARTY(),
        failure_reason: "insight_unverified",
        recruitment_cycles: [],
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

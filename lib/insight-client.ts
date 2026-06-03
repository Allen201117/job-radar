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

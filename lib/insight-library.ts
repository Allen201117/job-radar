// ============================================================
// 洞察库（/insights）的读模型 —— 纯函数层，不碰网络与 DB。
//
// 单位是「主体」（公司 或 公司×业务线），不是单条洞察：
//   一条「城市分布：北京 32%」单独成卡没有阅读价值，用户真正要比较的是
//   「哪条业务线在扩张 / 门槛多高 / 有没有薪资数据」——这些都是主体的属性。
//   而且验收标准写的就是「筛出**业务线**」，不是「筛出条目」。
//
// ⚠️ 性能红线（/campus 踩过 10.1s / 2.09MB 的坑）：首屏只下发聚合分面 + 一页主体卡，
//    绝不逐条下发全部洞察。展开某个主体时再按 subject_id 取它的条目。
// ============================================================

import {
  evaluateInsight,
  freshnessFromVerifiedAt,
  type FreshnessLevel,
} from "./insight-verification";
import type {
  InsightAssertion,
  InsightDimension,
  InsightItem,
  InsightSource,
} from "./types";

/** 主体卡上直接展示的指标（正文已是人话一句，前端不再拼装）。 */
export interface LibraryMetric {
  metric_key: string;
  metric_value: number | null;
  metric_unit: string | null;
  sample_size: number | null;
  assertion: InsightAssertion;
  dimension: InsightDimension;
  content: string;
  scope: Record<string, unknown>;
}

export interface LibrarySubject {
  id: string;
  company_id: string;
  company: string;
  industry: string | null;
  kind: "company" | "business_unit";
  name: string;
  job_count: number;
  /** 三档承诺各有多少条可展示内容——这是「健康度」的第一眼判据。 */
  assertion_counts: Record<InsightAssertion, number>;
  dimensions: InsightDimension[];
  metrics: LibraryMetric[];
  /** 最近一次核实时间（ISO）。null = 该主体还没有任何可展示洞察。 */
  last_verified_at: string | null;
  freshness: FreshnessLevel | null;
  item_count: number;
}

export type LibrarySort = "fresh" | "sample" | "jobs" | "insights";

export interface LibraryFilters {
  q?: string;
  companyId?: string;
  kind?: "company" | "business_unit";
  dimension?: InsightDimension;
  assertion?: InsightAssertion;
  industry?: string;
  metric?: string;
  metricMin?: number | null;
  metricMax?: number | null;
  /** 主体必须同时拥有这些指标（用于「且有薪资数据」这类组合筛选）。 */
  has?: string[];
  freshness?: FreshnessLevel;
  sort?: LibrarySort;
}

export interface FacetBucket {
  key: string;
  count: number;
}

export interface LibraryFacets {
  kind: FacetBucket[];
  dimension: FacetBucket[];
  assertion: FacetBucket[];
  metric: FacetBucket[];
  industry: FacetBucket[];
  freshness: FacetBucket[];
}

// ── 索引构建 ──────────────────────────────────────────────────────────────

export interface RawSubjectRow {
  id: string;
  company_id: string;
  kind: string;
  name: string;
  job_count: number | null;
  status: string;
}

/** insight_items 行 + 已拍平的来源（来源用于过 claim 的展示门）。 */
export type RawItemRow = InsightItem & { sources?: InsightSource[] };

/**
 * 把「主体 + 已过展示门的条目」压成一份紧凑索引。
 *
 * ⚠️ 计数必须建立在**过门之后**的条目上：拿 status='active' 直接计数会让卡面写着
 * 「9 条洞察」而点进去只有 3 条（无来源的 claim 会被展示门挡掉）——本仓库最忌讳的
 * 「计数与内容对不上」。
 */
export function buildLibraryIndex(
  subjects: RawSubjectRow[],
  items: RawItemRow[],
  companies: Map<string, { company: string; industry: string | null }>,
  now: Date = new Date(),
): LibrarySubject[] {
  const bySubject = new Map<string, RawItemRow[]>();
  for (const item of items || []) {
    if (!item.subject_id) continue;
    const ev = evaluateInsight(item, item.sources || [], now);
    if (!ev.displayable) continue;
    const list = bySubject.get(item.subject_id);
    if (list) list.push(item);
    else bySubject.set(item.subject_id, [item]);
  }

  const out: LibrarySubject[] = [];
  for (const subject of subjects || []) {
    if (subject.status !== "active") continue;
    const company = companies.get(subject.company_id);
    if (!company) continue;
    const own = bySubject.get(subject.id) || [];
    const assertion_counts: Record<InsightAssertion, number> = { fact: 0, signal: 0, claim: 0 };
    const dims = new Set<InsightDimension>();
    let latest: string | null = null;
    const metrics: LibraryMetric[] = [];
    for (const item of own) {
      const assertion = (item.assertion || "claim") as InsightAssertion;
      assertion_counts[assertion] = (assertion_counts[assertion] || 0) + 1;
      dims.add(item.dimension);
      if (!latest || item.last_verified_at > latest) latest = item.last_verified_at;
      if (item.metric_key) {
        metrics.push({
          metric_key: item.metric_key,
          metric_value: item.metric_value ?? null,
          metric_unit: item.metric_unit ?? null,
          sample_size: item.sample_size ?? null,
          assertion,
          dimension: item.dimension,
          content: item.content,
          scope: (item.scope || {}) as Record<string, unknown>,
        });
      }
    }
    out.push({
      id: subject.id,
      company_id: subject.company_id,
      company: company.company,
      industry: company.industry,
      kind: subject.kind === "company" ? "company" : "business_unit",
      name: subject.name,
      job_count: subject.job_count || 0,
      assertion_counts,
      dimensions: [...dims],
      metrics: metrics.sort((a, b) => a.metric_key.localeCompare(b.metric_key)),
      last_verified_at: latest,
      freshness: freshnessFromVerifiedAt(latest, now)?.level ?? null,
      item_count: own.length,
    });
  }
  return out;
}

// ── 筛选与排序 ────────────────────────────────────────────────────────────

function metricOf(subject: LibrarySubject, key: string): LibraryMetric | undefined {
  return subject.metrics.find((m) => m.metric_key === key);
}

/** 单个筛选项是否放行。拆成一条一条，好让分面能「排除自己这一项」重算。 */
const PREDICATES: Record<string, (s: LibrarySubject, f: LibraryFilters) => boolean> = {
  q: (s, f) => {
    const q = (f.q || "").trim().toLowerCase();
    if (!q) return true;
    return s.name.toLowerCase().includes(q) || s.company.toLowerCase().includes(q);
  },
  companyId: (s, f) => !f.companyId || s.company_id === f.companyId,
  kind: (s, f) => !f.kind || s.kind === f.kind,
  dimension: (s, f) => !f.dimension || s.dimensions.includes(f.dimension),
  assertion: (s, f) => !f.assertion || (s.assertion_counts[f.assertion] || 0) > 0,
  industry: (s, f) => !f.industry || s.industry === f.industry,
  freshness: (s, f) => !f.freshness || s.freshness === f.freshness,
  metric: (s, f) => {
    if (!f.metric) return true;
    const m = metricOf(s, f.metric);
    if (!m) return false;
    if (f.metricMin != null && (m.metric_value == null || m.metric_value < f.metricMin)) return false;
    if (f.metricMax != null && (m.metric_value == null || m.metric_value > f.metricMax)) return false;
    return true;
  },
  has: (s, f) => (f.has || []).every((key) => Boolean(metricOf(s, key))),
};

export function filterSubjects(
  subjects: LibrarySubject[],
  filters: LibraryFilters,
  except?: string,
): LibrarySubject[] {
  const keys = Object.keys(PREDICATES).filter((k) => k !== except);
  return subjects.filter((s) => keys.every((k) => PREDICATES[k](s, filters)));
}

const FRESHNESS_RANK: Record<string, number> = { fresh: 0, recent: 1, aging: 2, stale: 3 };

export function sortSubjects(
  subjects: LibrarySubject[],
  sort: LibrarySort = "fresh",
): LibrarySubject[] {
  const rows = [...subjects];
  if (sort === "jobs") {
    rows.sort((a, b) => b.job_count - a.job_count || a.name.localeCompare(b.name));
  } else if (sort === "sample") {
    const maxN = (s: LibrarySubject) =>
      s.metrics.reduce((acc, m) => Math.max(acc, m.sample_size || 0), 0);
    rows.sort((a, b) => maxN(b) - maxN(a) || b.job_count - a.job_count);
  } else if (sort === "insights") {
    rows.sort((a, b) => b.item_count - a.item_count || b.job_count - a.job_count);
  } else {
    rows.sort((a, b) => {
      const fa = FRESHNESS_RANK[a.freshness || "stale"] ?? 9;
      const fb = FRESHNESS_RANK[b.freshness || "stale"] ?? 9;
      if (fa !== fb) return fa - fb;
      const ta = a.last_verified_at ? Date.parse(a.last_verified_at) : 0;
      const tb = b.last_verified_at ? Date.parse(b.last_verified_at) : 0;
      return tb - ta || b.job_count - a.job_count;
    });
  }
  return rows;
}

// ── 分面 ─────────────────────────────────────────────────────────────────

function tally(rows: LibrarySubject[], pick: (s: LibrarySubject) => string[]): FacetBucket[] {
  const counts = new Map<string, number>();
  for (const row of rows) {
    for (const key of pick(row)) {
      if (!key) continue;
      counts.set(key, (counts.get(key) || 0) + 1);
    }
  }
  return [...counts.entries()]
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key));
}

/**
 * 每个分面都在「其它筛选已生效、但本分面自己不生效」的集合上计数。
 * 这样用户看到的每个数字都是「点下去会得到多少个主体」，不会点出 0 结果。
 */
export function computeFacets(
  subjects: LibrarySubject[],
  filters: LibraryFilters,
): LibraryFacets {
  const on = (except: string) => filterSubjects(subjects, filters, except);
  return {
    kind: tally(on("kind"), (s) => [s.kind]),
    dimension: tally(on("dimension"), (s) => s.dimensions),
    assertion: tally(on("assertion"), (s) =>
      (Object.keys(s.assertion_counts) as InsightAssertion[]).filter(
        (k) => (s.assertion_counts[k] || 0) > 0,
      ),
    ),
    metric: tally(on("metric"), (s) => s.metrics.map((m) => m.metric_key)),
    industry: tally(on("industry"), (s) => (s.industry ? [s.industry] : [])),
    freshness: tally(on("freshness"), (s) => (s.freshness ? [s.freshness] : [])),
  };
}

// ── 查询串 → 筛选条件 ────────────────────────────────────────────────────
// 放在 lib 而不是 route：Next.js 的 route 文件只允许导出 GET/POST/runtime 等固定名字，
// 多导出一个纯函数会直接编译失败；而这个解析必须可单测。
function toNumber(value: string | null): number | null {
  if (value == null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

const SORTS: LibrarySort[] = ["fresh", "sample", "jobs", "insights"];
const KINDS = ["company", "business_unit"] as const;
const ASSERTIONS: InsightAssertion[] = ["fact", "signal", "claim"];
const DIMENSIONS: InsightDimension[] = [
  "timing", "hiring", "listing", "compensation_intensity", "path", "culture",
];
const FRESHNESS: FreshnessLevel[] = ["fresh", "recent", "aging", "stale"];

function pick<T extends string>(value: string | null, allowed: readonly T[]): T | undefined {
  return value && (allowed as readonly string[]).includes(value) ? (value as T) : undefined;
}

/** 未知取值一律丢弃而不是原样透传：否则 ?assertion=xxx 会静默筛出 0 条，用户读成「没有数据」。 */
export function parseLibraryFilters(params: URLSearchParams): LibraryFilters {
  return {
    q: params.get("q") || undefined,
    companyId: params.get("company") || undefined,
    kind: pick(params.get("kind"), KINDS),
    dimension: pick(params.get("dimension"), DIMENSIONS),
    assertion: pick(params.get("assertion"), ASSERTIONS),
    industry: params.get("industry") || undefined,
    metric: params.get("metric") || undefined,
    metricMin: toNumber(params.get("metricMin")),
    metricMax: toNumber(params.get("metricMax")),
    has: params.getAll("has").filter(Boolean),
    freshness: pick(params.get("freshness"), FRESHNESS),
    sort: pick(params.get("sort"), SORTS) || "fresh",
  };
}

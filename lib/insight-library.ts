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

/**
 * 主体卡上直接展示的指标。
 *
 * ⚠️ `content` / `scope` **刻意不进缓存索引**：Vercel 数据缓存单条上限 2MB，
 * 带上正文后 1,500 个主体 × 约 7 条指标就顶到上限 → unstable_cache **静默不缓存**，
 * 每个请求都重建索引（2026-09-03 线上实测：index_built_at 每次都变、每次 ~10s）。
 * 正文只为「当前这一页的 24 个主体」按 item id 现取（attachCardContents）。
 */
/**
 * 缓存索引里的指标，**打包成元组**：`[metric_key, metric_value, sample_size, assertion]`。
 *
 * 为什么不用对象（这是量出来的，不是风格偏好）：
 *   1,600 个主体 × 7 条指标时，对象形态实测 1,716KB，顶着 Vercel 数据缓存 2MB 上限 ——
 *   超了就**静默不缓存**，每个请求都重建索引（线上实测 index_built_at 每次都变、每次 ~10s，
 *   而且没有任何报错）。光是 JSON 的键名与 item uuid 就占掉 0.8MB。
 *   元组化后同一组数据 ~560KB，留出 2 倍余量。
 *   同一权衡在 /campus 的分面上已经做过一次（CLAUDE.md「校招专区首屏」）。
 *
 * ⚠️ 打包与读取（下面的 M_* 下标与 metricKey/metricValue 等）**刻意放同一文件**：
 *    下标口径两端一漂，页面就会安静地显示错数字——不报错、不崩，只骗用户。
 */
export type PackedMetric = [string, number | null, number | null, InsightAssertion];

export const M_KEY = 0;
export const M_VALUE = 1;
export const M_SAMPLE = 2;
export const M_ASSERTION = 3;

export const metricKey = (m: PackedMetric): string => m[M_KEY];
export const metricValue = (m: PackedMetric): number | null => m[M_VALUE];
export const metricSample = (m: PackedMetric): number | null => m[M_SAMPLE];
export const metricAssertion = (m: PackedMetric): InsightAssertion => m[M_ASSERTION];

/** 卡面用的可读形态：只为「当前这一页」的主体现取，不进缓存索引。 */
export interface LibraryCardMetric {
  metric_key: string;
  metric_value: number | null;
  metric_unit: string | null;
  sample_size: number | null;
  assertion: InsightAssertion;
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
  metrics: PackedMetric[];
  /** 卡面正文，由 attachCardContents 为当前页补上；缓存索引里没有。 */
  cards?: LibraryCardMetric[];
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

/** 列表每页多少张主体卡。页面与接口共用，避免两处不一致导致「加载更多」错位。 */
export const LIBRARY_PAGE_SIZE = 24;
/** 主体卡上最多展示几条指标；其余在展开时取。 */
export const CARD_METRICS = 6;

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
  // subject_id 为 NULL = **公司级**（迁移 204 的定义），不是「没有主体」。
  // 存量 T2/T3 条目（官方事实 + 公开说法）全都是公司级写入的；照 subject_id 硬筛会把
  // 它们整批排除在洞察库外——线上实测就是这样：筛选器里只剩「数据」一档，
  // 5,958 条「说法」一条都不出现。这里把公司级条目挂到该公司的 company 主体上。
  const companySubjectId = new Map<string, string>();
  for (const subject of subjects || []) {
    if (subject.kind === "company" && subject.status === "active") {
      companySubjectId.set(subject.company_id, subject.id);
    }
  }
  const bySubject = new Map<string, RawItemRow[]>();
  for (const item of items || []) {
    const targetId = item.subject_id || companySubjectId.get(item.company_id);
    if (!targetId) continue;
    const ev = evaluateInsight(item, item.sources || [], now);
    if (!ev.displayable) continue;
    const list = bySubject.get(targetId);
    if (list) list.push(item);
    else bySubject.set(targetId, [item]);
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
    const metrics: PackedMetric[] = [];
    for (const item of own) {
      const assertion = (item.assertion || "claim") as InsightAssertion;
      assertion_counts[assertion] = (assertion_counts[assertion] || 0) + 1;
      dims.add(item.dimension);
      if (!latest || item.last_verified_at > latest) latest = item.last_verified_at;
      if (item.metric_key) {
        // 只留筛选/分面/排序需要的四个值。正文与单位见 PackedMetric 的注释。
        metrics.push([item.metric_key, item.metric_value ?? null, item.sample_size ?? null, assertion]);
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
      metrics: metrics.sort((a, b) => metricKey(a).localeCompare(metricKey(b))),
      last_verified_at: latest,
      freshness: freshnessFromVerifiedAt(latest, now)?.level ?? null,
      item_count: own.length,
    });
  }
  return out;
}

// ── 筛选与排序 ────────────────────────────────────────────────────────────

function metricOf(subject: LibrarySubject, key: string): PackedMetric | undefined {
  return subject.metrics.find((m) => metricKey(m) === key);
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
    const value = metricValue(m);
    if (f.metricMin != null && (value == null || value < f.metricMin)) return false;
    if (f.metricMax != null && (value == null || value > f.metricMax)) return false;
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
      s.metrics.reduce((acc, m) => Math.max(acc, metricSample(m) || 0), 0);
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
    metric: tally(on("metric"), (s) => s.metrics.map(metricKey)),
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

/** 主体卡只带头条指标：signal 在前（第一方最可信），再按样本量。 */
export function trimSubjectForCard(subject: LibrarySubject): LibrarySubject {
  const rank: Record<string, number> = { signal: 0, fact: 1, claim: 2 };
  const metrics = [...subject.metrics]
    .sort(
      (a, b) =>
        (rank[metricAssertion(a)] ?? 9) - (rank[metricAssertion(b)] ?? 9) ||
        (metricSample(b) || 0) - (metricSample(a) || 0),
    )
    .slice(0, CARD_METRICS);
  return { ...subject, metrics };
}

// ── 展示用标签（页面与治理后台共用，别在 UI 里留第二份）──────────────────
export const DIMENSION_LABEL: Record<InsightDimension, string> = {
  timing: "招聘时机",
  hiring: "招聘动态",
  listing: "上市 / 股票",
  compensation_intensity: "薪资 / 强度",
  path: "进入路径",
  culture: "公司文化",
};

/** metric_key → 人话。枚举本身在迁移 204 的 CHECK 里，新增指标两处都要加。 */
export const METRIC_LABEL: Record<string, string> = {
  headcount_total: "员工总数",
  headcount_tech_ratio: "技术人员占比",
  edu_bachelor_plus_ratio: "本科及以上占比",
  edu_master_plus_ratio: "硕士及以上占比",
  bu_count: "业务线条数",
  bu_job_count: "业务线在招岗位数",
  hiring_volume_30d: "近 30 天新挂出",
  hiring_trend_30d_pct: "30 天环比",
  hiring_trend_90d_pct: "90 天环比",
  open_age_days_median: "岗位在架时长",
  city_share: "城市分布",
  function_share: "职能分布",
  bucket_share: "招聘类型分布",
  exp_years_median: "经验年限",
  edu_requirement_mode: "学历要求",
  avg_comp_annual: "人均薪酬",
  salary_range_k: "明写薪资",
  bonus_months: "年终奖",
  overtime_level: "加班强度",
  promotion_pace: "晋升节奏",
  interview_rounds: "面试轮次",
  hiring_freeze_signal: "招聘骤降",
  layoff_mention: "裁员提及",
  listing_status: "上市状态",
  revenue_yoy: "营收同比",
};

export const FRESHNESS_LABEL: Record<string, string> = {
  fresh: "近期核实",
  recent: "数月前核实",
  aging: "较久未更新",
  stale: "久未更新",
};

/**
 * 岗位库只能答「稳定性」和「好不好进」。强度 / 晋升 / 面试完全不在岗位数据里，
 * 薪资明写覆盖仅 1.8% —— 这几栏没内容时不显示「暂无数据」，而是给贡献入口。
 * （spec §1.5 + 任务卡 §2.3 互惠墙）
 */
export const CONTRIBUTION_GAPS: Array<{ key: string; label: string; topic: string }> = [
  { key: "overtime_level", label: "工作强度 / 加班", topic: "culture" },
  { key: "bonus_months", label: "年终奖", topic: "compensation" },
  { key: "promotion_pace", label: "晋升节奏", topic: "career" },
  { key: "interview_rounds", label: "面试流程", topic: "interview" },
];

/** 该主体还缺哪几类「我们给不了、只有待过的人知道」的内容。 */
export function missingContributionTopics(subject: LibrarySubject): typeof CONTRIBUTION_GAPS {
  const have = new Set(subject.metrics.map(metricKey));
  return CONTRIBUTION_GAPS.filter((gap) => !have.has(gap.key));
}

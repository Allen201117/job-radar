type Numeric = number | string | null | undefined;

function toNumber(value: Numeric): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

export function formatPercent(numerator: Numeric, denominator: Numeric): string {
  const total = toNumber(denominator);
  if (total <= 0) return "—";
  return `${((toNumber(numerator) / total) * 100).toFixed(1)}%`;
}

export function formatDuration(seconds: Numeric): string {
  if (seconds == null || seconds === "") return "—";
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value < 1) return "<1 秒";
  const rounded = Math.round(value);
  if (rounded < 60) return `${rounded} 秒`;
  const minutes = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`;
}

export type CrawlSourceRow = {
  source_id?: string | null;
  company?: string | null;
  adapter_name?: string | null;
  runs?: Numeric;
  success?: Numeric;
  partial_success?: Numeric;
  failed?: Numeric;
  skipped?: Numeric;
};

export type CrawlSourceMetric = {
  sourceId: string;
  company: string;
  adapterName: string;
  runs: number;
  successRate: string;
  partialRate: string;
  failed: number;
  skipped: number;
};

export function normalizeCrawlSources(rows: CrawlSourceRow[] | null | undefined): CrawlSourceMetric[] {
  return (rows || []).map((row) => {
    const success = toNumber(row.success);
    const partial = toNumber(row.partial_success);
    const failed = toNumber(row.failed);
    const terminal = success + partial + failed;
    return {
      sourceId: String(row.source_id || ""),
      company: String(row.company || "未知来源"),
      adapterName: String(row.adapter_name || "unknown"),
      runs: toNumber(row.runs),
      successRate: formatPercent(success, terminal),
      partialRate: formatPercent(partial, terminal),
      failed,
      skipped: toNumber(row.skipped),
    };
  });
}

export type DiscoveryModeRow = {
  mode?: string | null;
  runs?: Numeric;
  completed_runs?: Numeric;
  avg_duration_seconds?: Numeric;
};

export type DiscoveryFailureRow = {
  mode?: string | null;
  reason?: string | null;
  count?: Numeric;
};

const DISCOVERY_LABELS: Record<string, string> = {
  company_refresh: "公司库刷新",
  official_job_discovery: "官方源发现",
  web_search: "官方源发现",
  browser_discovery: "浏览器发现",
  discovery: "浏览器发现",
};

export type DiscoveryModeMetric = {
  mode: string;
  label: string;
  runs: number;
  completedRuns: number;
  averageDuration: string;
  failures: Array<{ reason: string; count: number }>;
};

export function normalizeDiscoveryModes(
  modes: DiscoveryModeRow[] | null | undefined,
  failures: DiscoveryFailureRow[] | null | undefined,
): DiscoveryModeMetric[] {
  return (modes || []).map((row) => {
    const mode = String(row.mode || "unknown");
    return {
      mode,
      label: DISCOVERY_LABELS[mode] || mode,
      runs: toNumber(row.runs),
      completedRuns: toNumber(row.completed_runs),
      averageDuration: formatDuration(row.avg_duration_seconds),
      failures: (failures || [])
        .filter((failure) => String(failure.mode || "unknown") === mode)
        .map((failure) => ({
          reason: String(failure.reason || "unknown"),
          count: toNumber(failure.count),
        })),
    };
  });
}

export type InsightDimensionRow = {
  dimension?: string | null;
  count?: Numeric;
};

const INSIGHT_DIMENSIONS = [
  ["timing", "时机"],
  ["hiring", "招聘热度"],
  ["listing", "上市信息"],
  ["compensation_intensity", "薪酬强度"],
  ["path", "路径"],
  ["culture", "文化"],
] as const;

const INSIGHT_LABELS = Object.fromEntries(INSIGHT_DIMENSIONS) as Record<string, string>;
const INSIGHT_ORDER = new Map<string, number>(
  INSIGHT_DIMENSIONS.map(([dimension], index) => [dimension, index]),
);

export function normalizeInsightDimensions(
  rows: InsightDimensionRow[] | null | undefined,
): Array<{ dimension: string; label: string; count: number }> {
  return (rows || [])
    .map((row) => {
      const dimension = String(row.dimension || "unknown");
      return {
        dimension,
        label: INSIGHT_LABELS[dimension] || dimension,
        count: toNumber(row.count),
      };
    })
    .sort((a, b) => {
      const ai = INSIGHT_ORDER.get(a.dimension) ?? Number.MAX_SAFE_INTEGER;
      const bi = INSIGHT_ORDER.get(b.dimension) ?? Number.MAX_SAFE_INTEGER;
      return ai - bi || a.dimension.localeCompare(b.dimension);
    });
}

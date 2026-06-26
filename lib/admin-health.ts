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

// ── 点击有效率四护栏（01 spec §5.3 / 05 §5.3）──────────────────────────────
// ⚠️「可探源点击有效率 ≥99%」会偷窄分母（最难的 SPA 不进分母）。所以**四个数一起报**，缺一不可：
//   ① 可探源点击有效率 = alive / (alive+dead)，只在可探源上算（分母排除 unknown）；
//   ② 点击核验覆盖率   = (alive+dead) / 总点击数（太低说明 ① 没代表性）；
//   ③ unknown 占比     = unknown / 总核验数（越高说明越多源探不动）；
//   ④ SPA 死岗抽检率   = 审计抽样，不来自这两个事件，admin 单独展示。
// 事件：opportunity_official_opened（总点击）+ job_liveness_at_click（payload.result ∈ alive/dead/unknown, payload.adapter）。
export type ClickEventRow = { event?: unknown; payload?: unknown };

export interface ClickValidityAdapter {
  adapter: string;
  alive: number;
  dead: number;
  unknown: number;
  validityRate: number | null; // alive/(alive+dead)，分母 0 → null
}

export interface ClickValidityMetrics {
  totalOpens: number; // opportunity_official_opened 数
  livenessTotal: number; // job_liveness_at_click 数（含 unknown）
  alive: number;
  dead: number;
  unknown: number;
  probeValidityRate: number | null; // ① alive/(alive+dead)
  coverageRate: number | null; // ② (alive+dead)/totalOpens
  unknownRate: number | null; // ③ unknown/livenessTotal
  byAdapter: ClickValidityAdapter[]; // 按 adapter 拆分（①）
}

function ratio(num: number, den: number): number | null {
  return den > 0 ? num / den : null;
}

export function computeClickValidityMetrics(rows: ClickEventRow[] | null | undefined): ClickValidityMetrics {
  let totalOpens = 0;
  let alive = 0;
  let dead = 0;
  let unknown = 0;
  const perAdapter = new Map<string, { alive: number; dead: number; unknown: number }>();

  for (const row of rows || []) {
    const event = typeof row?.event === "string" ? row.event : "";
    if (event === "opportunity_official_opened") {
      totalOpens += 1;
      continue;
    }
    if (event !== "job_liveness_at_click") continue;
    const payload = row?.payload && typeof row.payload === "object" ? (row.payload as Record<string, unknown>) : {};
    const result = payload.result;
    const adapter = typeof payload.adapter === "string" && payload.adapter ? payload.adapter : "unknown";
    const bucket = perAdapter.get(adapter) || { alive: 0, dead: 0, unknown: 0 };
    if (result === "alive") {
      alive += 1;
      bucket.alive += 1;
    } else if (result === "dead") {
      dead += 1;
      bucket.dead += 1;
    } else {
      unknown += 1;
      bucket.unknown += 1;
    }
    perAdapter.set(adapter, bucket);
  }

  const livenessTotal = alive + dead + unknown;
  const byAdapter: ClickValidityAdapter[] = Array.from(perAdapter.entries())
    .map(([adapter, b]) => ({
      adapter,
      alive: b.alive,
      dead: b.dead,
      unknown: b.unknown,
      validityRate: ratio(b.alive, b.alive + b.dead),
    }))
    .sort((a, b) => b.alive + b.dead + b.unknown - (a.alive + a.dead + a.unknown) || a.adapter.localeCompare(b.adapter));

  return {
    totalOpens,
    livenessTotal,
    alive,
    dead,
    unknown,
    probeValidityRate: ratio(alive, alive + dead),
    coverageRate: ratio(alive + dead, totalOpens),
    unknownRate: ratio(unknown, livenessTotal),
    byAdapter,
  };
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

export type TodayCrawlRow = {
  runs?: Numeric;
  jobs_found?: Numeric;
  jobs_created?: Numeric;
  jobs_updated?: Numeric;
  failed_runs?: Numeric;
  failed_sources?: Numeric;
  last_run_at?: string | null;
};

export type TodayDiscoveryRow = {
  runs?: Numeric;
  jobs_created?: Numeric;
  jobs_updated?: Numeric;
  failed_runs?: Numeric;
  last_run_at?: string | null;
};

export type OpsRunAggregateRow = {
  module?: string | null;
  runs?: Numeric;
  success?: Numeric;
  partial?: Numeric;
  failed?: Numeric;
  checked?: Numeric;
  expired?: Numeric;
  deleted?: Numeric;
  enriched?: Numeric;
  companies_enriched?: Numeric;
  retired?: Numeric;
  last_run_at?: string | null;
};

export type DailyReportStatus = "success" | "idle" | "failed";

export type DailyReport = {
  key: "crawl" | "enrichment" | "dead_jobs" | "insights" | "discovery";
  title: string;
  description: string;
  status: DailyReportStatus;
  statusLabel: string;
  lastRunAt: string | null;
  metrics: Array<{ label: string; value: number | null }>;
};

type DailyReportInput = {
  crawl?: TodayCrawlRow | null;
  discovery?: TodayDiscoveryRow | null;
  insight?: { today_created?: Numeric } | null;
  opsRuns?: OpsRunAggregateRow[] | null;
};

const OPERATIONAL_TERMS: Record<string, string> = {
  active: "在招",
  expired: "已确认撤岗",
  removed: "暂时下线",
  success: "完成",
  partial: "部分完成",
  partial_success: "部分完成",
  failed: "失败",
  skipped: "未执行",
  queued: "等待运行",
  running: "运行中",
};

export function translateOperationalTerm(value: string | null | undefined): string {
  return OPERATIONAL_TERMS[String(value || "")] || "未知状态";
}

function latestTimestamp(values: Array<string | null | undefined>): string | null {
  const valid = values.filter((value): value is string => Boolean(value));
  if (!valid.length) return null;
  return valid.sort((a, b) => Date.parse(b) - Date.parse(a))[0] || null;
}

function summarizeOps(rows: OpsRunAggregateRow[], modules: string[]) {
  const selected = rows.filter((row) => modules.includes(String(row.module || "")));
  if (!selected.length) {
    return {
      available: false,
      runs: 0,
      failed: 0,
      checked: 0,
      expired: 0,
      deleted: 0,
      enriched: 0,
      companiesEnriched: 0,
      retired: 0,
      lastRunAt: null as string | null,
    };
  }
  return {
    available: true,
    runs: selected.reduce((sum, row) => sum + toNumber(row.runs), 0),
    failed: selected.reduce((sum, row) => sum + toNumber(row.failed), 0),
    checked: selected.reduce((sum, row) => sum + toNumber(row.checked), 0),
    expired: selected.reduce((sum, row) => sum + toNumber(row.expired), 0),
    deleted: selected.reduce((sum, row) => sum + toNumber(row.deleted), 0),
    enriched: selected.reduce((sum, row) => sum + toNumber(row.enriched), 0),
    companiesEnriched: selected.reduce((sum, row) => sum + toNumber(row.companies_enriched), 0),
    retired: selected.reduce((sum, row) => sum + toNumber(row.retired), 0),
    lastRunAt: latestTimestamp(selected.map((row) => row.last_run_at)),
  };
}

function reportStatus(runs: number, failed: number): DailyReportStatus {
  if (runs <= 0) return "idle";
  if (failed >= runs) return "failed";
  return "success";
}

function statusLabel(status: DailyReportStatus): string {
  if (status === "success") return "今天已运行";
  if (status === "failed") return "运行失败";
  return "今天没记录";
}

export function buildDailyReports(input: DailyReportInput): DailyReport[] {
  const opsRows = input.opsRuns || [];
  const enrichment = summarizeOps(opsRows, ["enrich_backlog"]);
  const liveness = summarizeOps(opsRows, ["liveness_sweep", "dead_link_audit"]);
  const purge = summarizeOps(opsRows, ["purge_expired"]);
  const insights = summarizeOps(opsRows, ["insight_backlog"]);
  const staleness = summarizeOps(opsRows, ["insight_staleness"]);

  const crawlRuns = toNumber(input.crawl?.runs);
  const crawlFailed = toNumber(input.crawl?.failed_runs);
  const discoveryRuns = toNumber(input.discovery?.runs);
  const discoveryFailed = toNumber(input.discovery?.failed_runs);
  const enrichmentStatus = reportStatus(enrichment.runs, enrichment.failed);
  const deadRuns = liveness.runs + purge.runs;
  const deadFailed = liveness.failed + purge.failed;
  const deadStatus = reportStatus(deadRuns, deadFailed);
  const insightRuns = insights.runs + staleness.runs;
  const insightFailed = insights.failed + staleness.failed;
  const insightStatus = reportStatus(insightRuns, insightFailed);
  const crawlStatus = reportStatus(crawlRuns, crawlFailed);
  const discoveryStatus = reportStatus(discoveryRuns, discoveryFailed);

  return [
    {
      key: "crawl",
      title: "岗位抓取",
      description: "每天去各企业官网抓新发布的岗位",
      status: crawlStatus,
      statusLabel: statusLabel(crawlStatus),
      lastRunAt: input.crawl?.last_run_at || null,
      metrics: [
        { label: "运行次数", value: input.crawl ? crawlRuns : null },
        { label: "抓到岗位", value: input.crawl ? toNumber(input.crawl.jobs_found) : null },
        { label: "新增岗位", value: input.crawl ? toNumber(input.crawl.jobs_created) : null },
        { label: "失败来源", value: input.crawl ? toNumber(input.crawl.failed_sources) : null },
      ],
    },
    {
      key: "enrichment",
      title: "详情补全",
      description: "给只有标题的空壳岗补上职位描述正文",
      status: enrichmentStatus,
      statusLabel: statusLabel(enrichmentStatus),
      lastRunAt: enrichment.lastRunAt,
      metrics: [
        { label: "检查岗位", value: enrichment.available ? enrichment.checked : null },
        { label: "补全正文", value: enrichment.available ? enrichment.enriched : null },
      ],
    },
    {
      key: "dead_jobs",
      title: "死岗治理",
      description: "核查岗位还在不在招，撤掉的清理回收",
      status: deadStatus,
      statusLabel: statusLabel(deadStatus),
      lastRunAt: latestTimestamp([liveness.lastRunAt, purge.lastRunAt]),
      metrics: [
        { label: "核查", value: liveness.available ? liveness.checked : null },
        { label: "判死", value: liveness.available ? liveness.expired : null },
        { label: "清除", value: purge.available ? purge.deleted : null },
      ],
    },
    {
      key: "insights",
      title: "职业洞察",
      description: "给公司补职业洞察，过期的自动下架",
      status: insightStatus,
      statusLabel: statusLabel(insightStatus),
      lastRunAt: latestTimestamp([insights.lastRunAt, staleness.lastRunAt]),
      metrics: [
        { label: "新增洞察", value: toNumber(input.insight?.today_created) },
        { label: "富化公司", value: insights.available ? insights.companiesEnriched : null },
        { label: "过期下架", value: staleness.available ? staleness.retired : null },
      ],
    },
    {
      key: "discovery",
      title: "刷新 / 发现",
      description: "用户点按钮临时找新公司、新岗位",
      status: discoveryStatus,
      statusLabel: statusLabel(discoveryStatus),
      lastRunAt: input.discovery?.last_run_at || null,
      metrics: [
        { label: "运行次数", value: input.discovery ? discoveryRuns : null },
        {
          label: "产出岗位",
          value: input.discovery
            ? toNumber(input.discovery.jobs_created) + toNumber(input.discovery.jobs_updated)
            : null,
        },
      ],
    },
  ];
}

export type TodayHealth = {
  level: "healthy" | "warning" | "critical";
  label: "健康" | "注意" | "出事";
  message: string;
};

export function evaluateTodayHealth(input: {
  validActive: Numeric;
  crawlRuns: Numeric;
  crawlFailedRuns: Numeric;
  previousValidActive?: Numeric;
}): TodayHealth {
  const validActive = toNumber(input.validActive);
  const crawlRuns = toNumber(input.crawlRuns);
  const failedRuns = toNumber(input.crawlFailedRuns);
  const previous = input.previousValidActive == null ? null : toNumber(input.previousValidActive);

  if (validActive <= 0) {
    return { level: "critical", label: "出事", message: "当前没有可确认能投的岗位，请立即检查岗位库。" };
  }
  if (crawlRuns > 0 && failedRuns >= crawlRuns) {
    return { level: "critical", label: "出事", message: "今天的岗位抓取全部失败，请立即检查。" };
  }
  if (crawlRuns <= 0) {
    return { level: "warning", label: "注意", message: "今天还没有岗位抓取记录，请确认定时任务是否已到运行时间。" };
  }
  if (previous && previous > 0 && validActive / previous < 0.8) {
    return { level: "warning", label: "注意", message: "能投岗位较历史基线明显下降，请检查下架和抓取情况。" };
  }
  return {
    level: "healthy",
    label: "健康",
    message: "今天抓取已运行，当前有可投岗位；历史波动基线仍在积累。",
  };
}

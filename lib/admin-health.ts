import {
  MUST_APPLY_LIST,
  MUST_APPLY_BY_INDUSTRY,
  industriesForPattern,
  mustApplyByIndustry,
  mustApplyUnion,
  type MustApplyScope,
} from "./must-apply-list";

type Numeric = number | string | null | undefined;
export type HealthBand = "good" | "warn" | "bad" | "empty";
export type BandDirection = "higher" | "lower";
export type BandTone = "success" | "warning" | "danger" | "muted";

export const HEALTH_THRESHOLDS = {
  clickValidity: { good: 0.99, warn: 0.9 },
  validActiveShare: { good: 0.85, warn: 0.7 },
  coveragePct: { good: 90, warn: 60 },
  mustApplyHealthyCompanies: { good: 28, warn: 24 },
  mustApplyZeroHealthyCompanies: { warn: 1, bad: 5 },
  thinActiveShare: { good: 0.1, warn: 0.25 },
  neverCheckedShare: { good: 0.15, warn: 0.35 },
} as const;

const MUST_APPLY_COMPANIES = MUST_APPLY_LIST;

function toNumber(value: Numeric): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function toNullableNumber(value: Numeric): number | null {
  if (value == null) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function band(value: Numeric, threshold: { good: number; warn: number }, direction: BandDirection): HealthBand {
  const n = toNullableNumber(value);
  if (n === null) return "empty";
  if (direction === "higher") {
    if (n >= threshold.good) return "good";
    if (n >= threshold.warn) return "warn";
    return "bad";
  }
  if (n < threshold.good) return "good";
  if (n <= threshold.warn) return "warn";
  return "bad";
}

export function coverageBand(value: Numeric): HealthBand {
  return band(value, HEALTH_THRESHOLDS.coveragePct, "higher");
}

export function bandTone(value: HealthBand): BandTone {
  if (value === "good") return "success";
  if (value === "warn") return "warning";
  if (value === "bad") return "danger";
  return "muted";
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

export type CoverageUnderSourceRow = {
  company?: string | null;
  adapter?: string | null;
  reported_total?: Numeric;
  fetched?: Numeric;
  coverage_pct?: Numeric;
  last_run_at?: string | null;
};

export type CoverageSnapshotRow = {
  measurable?: Numeric;
  blind?: Numeric;
  avg_coverage_pct?: Numeric;
  under_count?: Numeric;
  under_sources?: CoverageUnderSourceRow[] | null;
};

export type CoverageUnderSource = {
  company: string;
  adapter: string;
  reportedTotal: number;
  fetched: number;
  coveragePct: number | null;
  lastRunAt: string | null;
};

export type CoverageSnapshot = {
  measurable: number;
  blind: number;
  avgCoveragePct: number | null;
  underCount: number;
  underSources: CoverageUnderSource[];
};

function emptyCoverageSnapshot(): CoverageSnapshot {
  return {
    measurable: 0,
    blind: 0,
    avgCoveragePct: null,
    underCount: 0,
    underSources: [],
  };
}

function toClampedPercent(value: Numeric): number | null {
  if (value == null) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.min(100, Math.round(n)));
}

export function normalizeCoverageSnapshot(row: CoverageSnapshotRow | null | undefined): CoverageSnapshot {
  if (!row) return emptyCoverageSnapshot();
  return {
    measurable: toNumber(row.measurable),
    blind: toNumber(row.blind),
    avgCoveragePct: toClampedPercent(row.avg_coverage_pct),
    underCount: toNumber(row.under_count),
    underSources: (Array.isArray(row.under_sources) ? row.under_sources : []).map((source) => {
      const reportedTotal = toNumber(source.reported_total);
      return {
        company: String(source.company || "未知公司"),
        adapter: String(source.adapter || "unknown"),
        reportedTotal,
        fetched: toNumber(source.fetched),
        coveragePct: reportedTotal > 0 ? toClampedPercent(source.coverage_pct) : null,
        lastRunAt: source.last_run_at || null,
      };
    }),
  };
}

export type MustApplyFetchCoverageCompanyRow = {
  name?: string | null;
  pattern?: string | null;
  reported_total?: Numeric;
  fetched?: Numeric;
  coverage_pct?: Numeric;
  measurable?: boolean | null;
  last_run_at?: string | null;
};

export type MustApplyFetchCoverageRow = {
  measurable?: Numeric;
  blind?: Numeric;
  fully_fetched?: Numeric;
  avg_pct?: Numeric;
  companies?: MustApplyFetchCoverageCompanyRow[] | null;
};

export type MustApplyFetchCoverageCompany = {
  name: string;
  pattern: string;
  reportedTotal: number | null;
  fetched: number;
  coveragePct: number | null;
  measurable: boolean;
  lastRunAt: string | null;
};

export type MustApplyFetchCoverage = {
  total: number;
  measurable: number;
  blind: number;
  fullyFetched: number;
  avgPct: number | null;
  companies: MustApplyFetchCoverageCompany[];
};

function emptyMustApplyFetchCoverage(scope: MustApplyScope = "domestic"): MustApplyFetchCoverage {
  const total = mustApplyUnion(scope).length;
  return {
    total,
    measurable: 0,
    blind: total,
    fullyFetched: 0,
    avgPct: null,
    companies: [],
  };
}

function mustApplyDisplayName(row: MustApplyFetchCoverageCompanyRow, scope: MustApplyScope = "domestic"): string {
  const pattern = typeof row.pattern === "string" ? row.pattern : "";
  const rawName = typeof row.name === "string" ? row.name : "";
  const matched = mustApplyUnion(scope).find((company) => company.pattern === pattern || company.pattern === rawName);
  return matched?.name || rawName || pattern || "未知公司";
}

export function normalizeMustApplyFetchCoverage(
  row: MustApplyFetchCoverageRow | null | undefined,
  scope: MustApplyScope = "domestic",
): MustApplyFetchCoverage {
  if (!row) return emptyMustApplyFetchCoverage(scope);

  const companies = (Array.isArray(row.companies) ? row.companies : [])
    .map((company) => {
      const pattern = String(company.pattern || company.name || "");
      const reported = toNullableNumber(company.reported_total);
      const measurable = typeof company.measurable === "boolean" ? company.measurable : reported !== null;
      const reportedTotal = measurable ? reported : null;
      const coveragePct = reportedTotal !== null && reportedTotal > 0 ? toClampedPercent(company.coverage_pct) : null;
      return {
        name: mustApplyDisplayName(company, scope),
        pattern,
        reportedTotal,
        fetched: toNumber(company.fetched),
        coveragePct,
        measurable,
        lastRunAt: company.last_run_at || null,
      };
    })
    .sort((a, b) => {
      const aPct = a.coveragePct == null ? Number.POSITIVE_INFINITY : a.coveragePct;
      const bPct = b.coveragePct == null ? Number.POSITIVE_INFINITY : b.coveragePct;
      return aPct - bPct || a.name.localeCompare(b.name, "zh-CN");
    });

  const measurable = companies.length ? companies.filter((company) => company.measurable).length : toNumber(row.measurable);
  const blind = companies.length ? companies.filter((company) => !company.measurable).length : toNumber(row.blind);
  const fullyFetched = companies.length
    ? companies.filter((company) => company.coveragePct !== null && company.coveragePct >= 90).length
    : toNumber(row.fully_fetched);
  const measuredCoverage = companies
    .map((company) => company.coveragePct)
    .filter((value): value is number => value !== null);
  const avgFromCompanies = measuredCoverage.length
    ? Math.round(measuredCoverage.reduce((sum, value) => sum + value, 0) / measuredCoverage.length)
    : null;

  return {
    total: companies.length || mustApplyUnion(scope).length,
    measurable,
    blind,
    fullyFetched,
    avgPct: toClampedPercent(row.avg_pct) ?? avgFromCompanies,
    companies,
  };
}

export function groupFetchCoverageByIndustry(
  coverage: MustApplyFetchCoverage,
  industries = Object.keys(MUST_APPLY_BY_INDUSTRY),
  scope: MustApplyScope = "domestic",
): Record<string, MustApplyFetchCoverage> {
  const byIndustry = mustApplyByIndustry(scope);
  const grouped: Record<string, MustApplyFetchCoverage> = {};
  for (const industry of industries) {
    const companies = coverage.companies.filter((company) => industriesForPattern(company.pattern, scope).includes(industry));
    const measuredCoverage = companies
      .map((company) => company.coveragePct)
      .filter((value): value is number => value !== null);
    grouped[industry] = {
      total: byIndustry[industry]?.length || 0,
      measurable: companies.filter((company) => company.measurable).length,
      blind: companies.filter((company) => !company.measurable).length,
      fullyFetched: companies.filter((company) => company.coveragePct !== null && company.coveragePct >= 90).length,
      avgPct: measuredCoverage.length
        ? Math.round(measuredCoverage.reduce((sum, value) => sum + value, 0) / measuredCoverage.length)
        : null,
      companies,
    };
  }
  return grouped;
}

type SupabaseRpcClient = {
  rpc: (
    fn: string,
    args?: Record<string, unknown>,
  ) => PromiseLike<{ data: unknown; error: { message?: string } | null }>;
};

export async function getMustApplyFetchCoverage(
  supabase: SupabaseRpcClient,
  scope: MustApplyScope = "domestic",
): Promise<MustApplyFetchCoverage> {
  try {
    const patterns = mustApplyUnion(scope).map((company) => company.pattern);
    const { data, error } = await supabase.rpc("must_apply_coverage", { patterns });
    if (error) {
      console.error("[admin-health] must-apply fetch coverage failed:", error.message || error);
      return emptyMustApplyFetchCoverage(scope);
    }
    return normalizeMustApplyFetchCoverage(data as MustApplyFetchCoverageRow | null, scope);
  } catch (error) {
    console.error("[admin-health] must-apply fetch coverage failed:", error);
    return emptyMustApplyFetchCoverage(scope);
  }
}

export async function getCoverageSnapshot(supabase: SupabaseRpcClient): Promise<CoverageSnapshot> {
  try {
    const { data, error } = await supabase.rpc("crawl_coverage_snapshot");
    if (error) {
      console.error("[admin-health] crawl coverage snapshot failed:", error.message || error);
      return emptyCoverageSnapshot();
    }
    return normalizeCoverageSnapshot(data as CoverageSnapshotRow | null);
  } catch (error) {
    console.error("[admin-health] crawl coverage snapshot failed:", error);
    return emptyCoverageSnapshot();
  }
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

export type GapFunnelOpsRow = {
  module?: string | null;
  run_date?: string | null;
  finished_at?: string | null;
  metrics?: Record<string, unknown> | null;
};

export type MustApplyGapAttemptRow = {
  company?: string | null;
  industries?: string[] | null;
  state?: string | null;
  fail_reason?: string | null;
  attempts?: Numeric;
  rounds_no_entry?: Numeric;
  last_attempt_at?: string | null;
  next_retry_at?: string | null;
  evidence?: Record<string, unknown> | null;
};

export type MustApplyGapSummary = {
  stateCounts: Record<string, number>;
  recentFailures: Array<{ company: string; reason: string; at: string | null }>;
  manualReviewCompanies: string[];
};

export type MustApplyGovernanceItem = {
  company: string;
  industries: string[];
  blocker: string;
  attempts: number;
  lastAttemptAt: string | null;
  suggestedAction: string;
};

const GAP_BLOCKERS: Record<string, string> = {
  governance_candidate: "连续多轮未找到公开招聘入口，已暂停自动重试",
  anti_bot: "招聘页面设置了访问限制，暂时无法核验",
  no_official_entry: "暂未找到可信的官方招聘入口",
  wrong_platform: "找到的招聘入口与该公司不匹配",
  no_active_jobs: "招聘入口暂未发现可验收的在招岗位",
  no_stable_jd: "招聘页未提供稳定的职位详情链接",
  login_wall: "招聘页面需要登录，暂时无法核验",
  manual_review: "招聘入口需要人工确认",
};

function plainGapFailReason(value: string | null | undefined): string | null {
  const reason = String(value || "").trim().toLowerCase();
  if (!reason) return null;
  if (/search.*(quota|cap)|额度|无可用.*(provider|查询)|查询资源/.test(reason)) return "本轮查询资源不足";
  if (/anti.?bot|captcha|验证码|访问限制/.test(reason)) return "招聘页面设置了访问限制，暂时无法核验";
  if (/login|登录/.test(reason)) return "招聘页面需要登录，暂时无法核验";
  if (/稳定.*(jd|链接)|no.*stable|逐岗/.test(reason)) return "招聘页未提供稳定的职位详情链接";
  if (/官方.*入口|no.*official/.test(reason)) return "暂未找到可信的官方招聘入口";
  if (/没有岗位|无在招|no.*active/.test(reason)) return "招聘入口暂未发现可验收的在招岗位";
  return null;
}

export function buildMustApplyGovernanceItems(
  rows: MustApplyGapAttemptRow[] | null | undefined,
): MustApplyGovernanceItem[] {
  const visibleStates = new Set(Object.keys(GAP_BLOCKERS));
  return [...(rows || [])]
    .filter((row) => {
      const state = String(row.state || "unknown");
      return visibleStates.has(state) || (state === "unknown" && Boolean(String(row.fail_reason || "").trim()));
    })
    .map((row) => {
      const state = String(row.state || "unknown");
      const roundsNoEntry = toNumber(row.rounds_no_entry);
      const shouldReplace = state === "governance_candidate"
        || state === "anti_bot"
        || (state === "no_official_entry" && roundsNoEntry >= 2);
      return {
        company: String(row.company || "未知公司"),
        industries: (Array.isArray(row.industries) ? row.industries : [])
          .map((industry) => String(industry || "").trim())
          .filter(Boolean),
        blocker: plainGapFailReason(row.fail_reason) || GAP_BLOCKERS[state] || "本轮未能完成招聘入口核验",
        attempts: toNumber(row.attempts),
        lastAttemptAt: row.last_attempt_at || null,
        suggestedAction: shouldReplace ? "考虑换成同行业其他公司" : "等下轮自动重试",
      };
    })
    .sort((a, b) =>
      (a.suggestedAction === "考虑换成同行业其他公司" ? 0 : 1)
      - (b.suggestedAction === "考虑换成同行业其他公司" ? 0 : 1)
      || Date.parse(String(b.lastAttemptAt || 0)) - Date.parse(String(a.lastAttemptAt || 0))
      || a.company.localeCompare(b.company),
    );
}

export function computeMustApplySupplyLedger(
  opsRows: GapFunnelOpsRow[] | null | undefined,
  coverageRows: Array<{
    directHealthy?: Numeric;
    coveredViaParentPortal?: boolean;
  }> | null | undefined,
): { realExpansion: number | null; definitionChange: number } {
  const modules = new Set(["gap_funnel", "gap_funnel_browser"]);
  const eligible = (opsRows || []).filter((row) => modules.has(String(row.module || "")));
  const dates = eligible
    .map((row) => String(row.run_date || ""))
    .filter(Boolean)
    .sort();
  const latestDate = dates[dates.length - 1];
  const latestByModule = new Map<string, GapFunnelOpsRow>();
  for (const row of eligible.filter((item) => item.run_date === latestDate)) {
    // 变量名不能叫 module：Next 的 @next/next/no-assign-module-variable 会把 build 判失败
    // （本地 next build 跳过 lint、Vercel 会跑 → 本地绿线上红，2026-07-27 实锤）。
    const moduleName = String(row.module);
    const previous = latestByModule.get(moduleName);
    if (!previous || Date.parse(String(row.finished_at || 0)) > Date.parse(String(previous.finished_at || 0))) {
      latestByModule.set(moduleName, row);
    }
  }
  const latestRows = Array.from(latestByModule.values());
  const hasExpansionEvidence = latestRows.some(
    (row) => typeof row.metrics?.sources_added === "number"
      && Number.isFinite(row.metrics.sources_added),
  );
  const realExpansion = hasExpansionEvidence
    ? latestRows.reduce(
      (sum, row) => sum + toNumber(row.metrics?.sources_added as Numeric),
      0,
    )
    : null;
  const definitionChange = (coverageRows || []).filter(
    (row) => row.coveredViaParentPortal && toNumber(row.directHealthy) === 0,
  ).length;
  return { realExpansion, definitionChange };
}

export function summarizeMustApplyGapAttempts(
  rows: MustApplyGapAttemptRow[] | null | undefined,
): MustApplyGapSummary {
  const stateCounts: Record<string, number> = {};
  for (const row of rows || []) {
    const state = String(row.state || "unknown");
    stateCounts[state] = (stateCounts[state] || 0) + 1;
  }
  const sortedStateCounts = Object.fromEntries(
    Object.entries(stateCounts).sort(([a], [b]) => a.localeCompare(b)),
  );
  const recentFailures = [...(rows || [])]
    .filter((row) => String(row.fail_reason || "").trim())
    .sort(
      (a, b) =>
        Date.parse(String(b.last_attempt_at || 0)) - Date.parse(String(a.last_attempt_at || 0))
        || String(a.company || "").localeCompare(String(b.company || "")),
    )
    .slice(0, 5)
    .map((row) => ({
      company: String(row.company || "未知公司"),
      reason: String(row.fail_reason),
      at: row.last_attempt_at || null,
    }));
  const manualStates = new Set(["manual_review", "anti_bot", "login_wall", "no_stable_jd"]);
  const manualReviewCompanies = [...(rows || [])]
    .filter((row) => manualStates.has(String(row.state || "")) && row.next_retry_at == null)
    .sort(
      (a, b) =>
        Date.parse(String(b.last_attempt_at || 0)) - Date.parse(String(a.last_attempt_at || 0))
        || String(a.company || "").localeCompare(String(b.company || "")),
    )
    .map((row) => String(row.company || ""))
    .filter(Boolean);
  return { stateCounts: sortedStateCounts, recentFailures, manualReviewCompanies };
}

// 全站唯一的模块判据。热力图和模块卡都调它 —— 两处曾各写一套且方向相反
// （热力图「任一失败即红」vs 模块卡「全挂才算失败」），同一天同一份数据一个判红一个判绿。
// 产出量必须进判据：只看「跑没跑」会把「跑了但一个都没产出」说成正常。
export type ModuleVerdict = "healthy" | "attention" | "broken" | "idle";

export function moduleVerdict(input: {
  runs: Numeric;
  failed: Numeric;
  produced: number | null;
  expectsOutput: boolean;
}): ModuleVerdict {
  const runs = Math.max(0, toNumber(input.runs));
  const failed = Math.max(0, toNumber(input.failed));
  if (runs <= 0) return "idle";
  if (failed >= runs) return "broken";
  // 「产出 0」排在「有失败」之前：跑了一整天一件事没产出，比「跑了 10 次挂了 1 次」严重得多，
  // 而这正是这块看板存在的理由（旧判据里产出量根本不是入参 → 线上出现过「产出岗位 0 · ● 正常」）。
  // produced 为 null = 该模块今天没有台账，不臆断；只有实测到 0 才判死。
  if (input.expectsOutput && input.produced === 0) return "broken";
  if (failed > 0) return "attention";
  return "healthy";
}

export function verdictTone(verdict: ModuleVerdict): BandTone {
  if (verdict === "healthy") return "success";
  if (verdict === "attention") return "warning";
  if (verdict === "broken") return "danger";
  return "muted";
}

export function verdictLabel(verdict: ModuleVerdict): string {
  if (verdict === "healthy") return "正常";
  if (verdict === "attention") return "有失败，但仍有产出";
  if (verdict === "broken") return "没跑通或一条都没产出";
  return "今天还没有运行记录";
}

// 「跑没跑」与「产出多少」是两件事，各自上色，不合并成一个词。
export function runSignalTone(runs: Numeric, failed: Numeric): BandTone {
  return verdictTone(moduleVerdict({ runs, failed, produced: null, expectsOutput: false }));
}

export function outputSignalTone(produced: number | null, expectsOutput: boolean): BandTone {
  if (produced == null) return "muted";
  if (produced > 0) return "success";
  return expectsOutput ? "danger" : "muted";
}

export type DailyRunSeriesPoint = { runs?: Numeric; failed?: Numeric; partial?: Numeric } | null | undefined;

// 热力图一格 = 当天所有后台任务合起来的结论，与模块卡走同一个 moduleVerdict；
// partial 只在没有失败时才降级成关注，不能把「无记录」伪装成 0 或成功。
export function dailyRunVerdict(run: DailyRunSeriesPoint): ModuleVerdict {
  if (!run || run.runs == null) return "idle";
  const verdict = moduleVerdict({ runs: run.runs, failed: run.failed, produced: null, expectsOutput: false });
  if (verdict === "healthy" && toNumber(run.partial) > 0) return "attention";
  return verdict;
}

export function dailyRunTone(run: DailyRunSeriesPoint): BandTone {
  return verdictTone(dailyRunVerdict(run));
}

export type DailyReport = {
  key: "crawl" | "enrichment" | "dead_jobs" | "insights" | "auto_discover" | "discovery" | "gap_funnel" | "campus_supply";
  title: string;
  description: string;
  verdict: ModuleVerdict;
  verdictLabel: string;
  runs: number;
  failed: number;
  runTone: BandTone;
  produced: number | null;
  producedLabel: string;
  producedCaption: string;
  producedTone: BandTone;
  expectsOutput: boolean;
  lastRunAt: string | null;
  metrics: Array<{ label: string; value: number | null }>;
};

export type OpsRunRow = {
  module?: string | null;
  status?: string | null;
  metrics?: Record<string, unknown> | null;
  started_at?: string | null;
  finished_at?: string | null;
};

type DailyReportInput = {
  crawl?: TodayCrawlRow | null;
  discovery?: TodayDiscoveryRow | null;
  insight?: { today_created?: Numeric } | null;
  opsRuns?: OpsRunAggregateRow[] | null;
  /** 原始 ops_runs 行：admin_health_snapshot 只抽了 6 个指标键，缺口漏斗 / 校招供给的产出口径不在其中。 */
  opsRunRows?: OpsRunRow[] | null;
  /** 必投清单的校招供给覆盖（lib/campus-supply-coverage.summarizeCampusSupply 的产物）。
   *  台账只能回答「任务跑没跑」，回答不了「30 家打通了几家」—— 那要查岗位库，故由页面算好传入。 */
  campusSupply?: { healthy: number; total: number; ourGap: number; theirGap: number; reachablePct: number | null } | null;
};

export const OPERATIONAL_TERMS: Record<string, string> = {
  active: "在招",
  expired: "已确认撤岗",
  removed: "暂时下线",
  today_removed: "今日下架",
  thin_active: "空壳岗",
  never_checked: "待核查",
  unknown: "探不动",
  success: "完成",
  partial: "部分完成",
  partial_success: "部分完成",
  failed: "失败",
  skipped: "未执行",
  queued: "等待运行",
  running: "运行中",
  entry_found: "已找到招聘入口",
  platform_known: "已识别招聘平台",
  source_added: "已加入招聘源",
  healthy: "已覆盖",
  thin_only: "岗位信息不足",
  no_official_entry: "未找到官方招聘入口",
  wrong_platform: "入口不匹配",
  no_active_jobs: "暂未发现在招岗位",
  no_stable_jd: "职位链接不稳定",
  anti_bot: "访问受限",
  login_wall: "需要登录",
  manual_review: "需要人工确认",
  governance_candidate: "建议治理",
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

// 原始 ops_runs 行聚合：快照 RPC 只抽固定 6 个指标键，缺口漏斗的 sources_added、
// 校招车道的 snapshots/surged 都不在里面，所以这些模块的产出只能从原始行里取。
function summarizeOpsRows(rows: OpsRunRow[], modules: string[]) {
  const selected = rows.filter((row) => modules.includes(String(row.module || "")));
  const metrics: Record<string, number> = {};
  for (const row of selected) {
    for (const [key, value] of Object.entries(row.metrics || {})) {
      if (typeof value === "number" && Number.isFinite(value)) metrics[key] = (metrics[key] || 0) + value;
    }
  }
  return {
    available: selected.length > 0,
    runs: selected.length,
    failed: selected.filter((row) => String(row.status || "") === "failed").length,
    metrics,
    lastRunAt: latestTimestamp(selected.map((row) => row.finished_at || row.started_at)),
  };
}

function buildReport(input: {
  key: DailyReport["key"];
  title: string;
  description: string;
  runs: number;
  failed: number;
  produced: number | null;
  producedLabel: string;
  producedCaption: string;
  expectsOutput: boolean;
  lastRunAt: string | null;
  metrics: DailyReport["metrics"];
}): DailyReport {
  const verdict = moduleVerdict({
    runs: input.runs,
    failed: input.failed,
    produced: input.produced,
    expectsOutput: input.expectsOutput,
  });
  return {
    key: input.key,
    title: input.title,
    description: input.description,
    verdict,
    verdictLabel: verdictLabel(verdict),
    runs: input.runs,
    failed: input.failed,
    runTone: runSignalTone(input.runs, input.failed),
    produced: input.produced,
    producedLabel: input.producedLabel,
    producedCaption: input.producedCaption,
    producedTone: outputSignalTone(input.produced, input.expectsOutput),
    expectsOutput: input.expectsOutput,
    lastRunAt: input.lastRunAt,
    metrics: input.metrics,
  };
}

export function buildDailyReports(input: DailyReportInput): DailyReport[] {
  const opsRows = input.opsRuns || [];
  const rawRows = input.opsRunRows || [];
  const enrichment = summarizeOps(opsRows, ["enrich_backlog"]);
  const liveness = summarizeOps(opsRows, ["liveness_sweep", "dead_link_audit"]);
  const purge = summarizeOps(opsRows, ["purge_expired"]);
  const insights = summarizeOps(opsRows, ["insight_backlog"]);
  const staleness = summarizeOps(opsRows, ["insight_staleness"]);
  const autoDiscover = summarizeOps(opsRows, ["auto_discover", "auto_discover_browser", "auto_discover_overseas"]);
  const gapFunnel = summarizeOpsRows(rawRows, ["gap_funnel", "gap_funnel_browser"]);
  const campus = summarizeOpsRows(rawRows, ["campus_lane", "campus_cycle_backlog", "campus_official_backlog"]);

  const crawlRuns = toNumber(input.crawl?.runs);
  const crawlFailed = toNumber(input.crawl?.failed_runs);
  const discoveryRuns = toNumber(input.discovery?.runs);
  const discoveryFailed = toNumber(input.discovery?.failed_runs);

  return [
    buildReport({
      key: "crawl",
      title: "岗位抓取",
      description: "每天去各家企业官网，把新发布的岗位抓回来",
      runs: crawlRuns,
      failed: crawlFailed,
      produced: input.crawl ? toNumber(input.crawl.jobs_created) : null,
      producedLabel: "今日新增岗位",
      producedCaption: "今天真正入库的新岗位数",
      expectsOutput: true,
      lastRunAt: input.crawl?.last_run_at || null,
      metrics: [
        { label: "运行次数", value: input.crawl ? crawlRuns : null },
        { label: "抓到岗位", value: input.crawl ? toNumber(input.crawl.jobs_found) : null },
        { label: "新增岗位", value: input.crawl ? toNumber(input.crawl.jobs_created) : null },
        { label: "抓失败的公司数", value: input.crawl ? toNumber(input.crawl.failed_sources) : null },
      ],
    }),
    buildReport({
      key: "enrichment",
      title: "详情补全",
      description: "给只有标题、没有职位描述的「空壳岗」补上正文",
      runs: enrichment.runs,
      failed: enrichment.failed,
      produced: enrichment.available ? enrichment.enriched : null,
      producedLabel: "今日补全正文",
      producedCaption: "今天补上职位描述的岗位数",
      expectsOutput: true,
      lastRunAt: enrichment.lastRunAt,
      metrics: [
        { label: "检查岗位", value: enrichment.available ? enrichment.checked : null },
        { label: "补全正文", value: enrichment.available ? enrichment.enriched : null },
      ],
    }),
    buildReport({
      key: "dead_jobs",
      title: "下架岗位清理",
      description: "逐个去看岗位还在不在招，已经撤下的清理掉、把空间还回来",
      runs: liveness.runs + purge.runs,
      failed: liveness.failed + purge.failed,
      produced: liveness.available ? liveness.checked : null,
      producedLabel: "今日核查岗位",
      producedCaption: "今天逐个查过「还在不在」的岗位数",
      expectsOutput: true,
      lastRunAt: latestTimestamp([liveness.lastRunAt, purge.lastRunAt]),
      metrics: [
        { label: "查过", value: liveness.available ? liveness.checked : null },
        { label: "确认已下架", value: liveness.available ? liveness.expired : null },
        { label: "清理掉", value: purge.available ? purge.deleted : null },
      ],
    }),
    buildReport({
      key: "insights",
      title: "职业洞察",
      description: "给公司补职业洞察，过期的自动下架",
      runs: insights.runs + staleness.runs,
      failed: insights.failed + staleness.failed,
      produced: input.insight ? toNumber(input.insight.today_created) : null,
      producedLabel: "今日新增洞察",
      producedCaption: "今天新写入的洞察条数",
      expectsOutput: true,
      lastRunAt: latestTimestamp([insights.lastRunAt, staleness.lastRunAt]),
      metrics: [
        { label: "新增洞察", value: toNumber(input.insight?.today_created) },
        { label: "补齐资料的公司", value: insights.available ? insights.companiesEnriched : null },
        { label: "过期下架", value: staleness.available ? staleness.retired : null },
      ],
    }),
    buildReport({
      key: "auto_discover",
      title: "自动新增公司",
      description: "每天自动去试目标公司的官方招聘页（候选名单里有一部分是 AI 每天新生成的）。试通了、而且确认真有岗在招，才会正式接入",
      runs: autoDiscover.runs,
      failed: autoDiscover.failed,
      produced: autoDiscover.available ? autoDiscover.companiesEnriched : null,
      producedLabel: "今日新增源",
      producedCaption: "今天真加进招聘源的公司数",
      expectsOutput: true,
      lastRunAt: autoDiscover.lastRunAt,
      metrics: [
        { label: "探查公司", value: autoDiscover.available ? autoDiscover.checked : null },
        { label: "新增源", value: autoDiscover.available ? autoDiscover.companiesEnriched : null },
      ],
    }),
    buildReport({
      key: "gap_funnel",
      title: "补公司流水线",
      description: "给必投清单里还没接上的公司找官方招聘入口，真抓到岗位才正式接入",
      runs: gapFunnel.runs,
      failed: gapFunnel.failed,
      produced: gapFunnel.available ? toNumber(gapFunnel.metrics.sources_added) : null,
      producedLabel: "今日新增源",
      producedCaption: "今天补进招聘源的缺口公司数",
      expectsOutput: true,
      lastRunAt: gapFunnel.lastRunAt,
      metrics: [
        { label: "处理公司", value: gapFunnel.available ? toNumber(gapFunnel.metrics.checked) : null },
        { label: "新增源", value: gapFunnel.available ? toNumber(gapFunnel.metrics.sources_added) : null },
        {
          label: "已覆盖",
          value: gapFunnel.available
            ? toNumber(gapFunnel.metrics.healthy) + toNumber(gapFunnel.metrics.thin_only)
            : null,
        },
      ],
    }),
    buildReport({
      key: "campus_supply",
      title: "校招供给",
      description: "每小时盯着必投公司的校招板块，一开始放岗就立刻加急重抓。「已打通」= 这家公司的校招岗位量相对它的社招体量是正常的；不正常的多半是我们漏了它的校招板块，不是对方没招人",
      runs: campus.runs,
      failed: campus.failed,
      // 台账没有「今日入库校招岗」这个口径，不硬编造：用真实存在的 snapshots
      // （今天校招岗位数发生变化的公司数），caption 如实说明它是什么。
      produced: campus.available ? toNumber(campus.metrics.snapshots) : null,
      producedLabel: "今天校招岗有变化的公司",
      producedCaption: "今天校招岗位数发生变化的公司数",
      expectsOutput: true,
      lastRunAt: campus.lastRunAt,
      metrics: [
        // 覆盖口径放最前：这是「打通了没有」的答案，比「今天跑了几次」更该先看到。
        { label: "必投清单已打通", value: input.campusSupply ? input.campusSupply.healthy : null },
        { label: "还差几家（我们能修的）", value: input.campusSupply ? input.campusSupply.ourGap : null },
        { label: "对方还没开校招", value: input.campusSupply ? input.campusSupply.theirGap : null },
        { label: "开始放岗的公司", value: campus.available ? toNumber(campus.metrics.surged) : null },
        { label: "校招岗位总数", value: campus.available ? toNumber(campus.metrics.campus_jobs_total) : null },
        { label: "新增校招洞察", value: campus.available ? toNumber(campus.metrics.verified) : null },
      ],
    }),
    buildReport({
      key: "discovery",
      title: "刷新 / 发现",
      description: "用户点按钮临时找新公司、新岗位",
      runs: discoveryRuns,
      failed: discoveryFailed,
      produced: input.discovery
        ? toNumber(input.discovery.jobs_created) + toNumber(input.discovery.jobs_updated)
        : null,
      producedLabel: "今日产出岗位",
      producedCaption: "用户点刷新后新增或更新的岗位数",
      expectsOutput: true,
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
    }),
  ];
}

export type TodayHealth = {
  level: "healthy" | "warning" | "critical";
  label: "健康" | "注意" | "出事";
  message: string;
};

export type CombinedHealthVerdict = TodayHealth & {
  actions: string[];
  bands: {
    clickValidity: HealthBand;
    mustApply: HealthBand;
    coverage: HealthBand;
  };
};

function capList(names: string[]): string {
  const clean = names.filter(Boolean);
  const head = clean.slice(0, 3).join("、");
  return clean.length > 3 ? `${head}等 ${clean.length} 家` : head;
}

function formatRateForAction(value: number | null): string {
  return value == null ? "暂无数据" : `${(value * 100).toFixed(1)}%`;
}

function mustApplyBand(healthyCompanies: number | null, zeroHealthyCount: number): HealthBand {
  let result = band(healthyCompanies, HEALTH_THRESHOLDS.mustApplyHealthyCompanies, "higher");
  if (zeroHealthyCount >= HEALTH_THRESHOLDS.mustApplyZeroHealthyCompanies.bad) return "bad";
  if (zeroHealthyCount >= HEALTH_THRESHOLDS.mustApplyZeroHealthyCompanies.warn && result === "good") return "warn";
  return result;
}

export function evaluateCombinedHealth(input: {
  validActive: Numeric;
  crawlRuns: Numeric;
  crawlFailedRuns: Numeric;
  clickProbeValidityRate?: Numeric;
  mustApplyHealthyCompanies?: Numeric;
  mustApplyTotalCompanies?: Numeric;
  mustApplyZeroHealthyCompanies?: string[] | Numeric;
  mustApplyBlindCompanies?: string[];
  mustApplyIndustries?: Array<{
    scope?: MustApplyScope;
    industry: string;
    healthy: number | null;
    total: number;
    zeroHealthyCompanies: string[];
    blindCompanies: string[];
    userCount: number;
  }>;
  coverageAvgPct?: Numeric;
  coverageBlindSources?: Numeric;
  previousValidActive?: Numeric;
}): CombinedHealthVerdict {
  void input.previousValidActive;
  const validActive = toNullableNumber(input.validActive);
  const crawlRuns = toNumber(input.crawlRuns);
  const failedRuns = toNumber(input.crawlFailedRuns);
  const clickRate = toNullableNumber(input.clickProbeValidityRate);
  const clickValidity = band(clickRate, HEALTH_THRESHOLDS.clickValidity, "higher");
  let healthyCompanies = toNullableNumber(input.mustApplyHealthyCompanies);
  let mustApplyTotal = toNumber(input.mustApplyTotalCompanies) || MUST_APPLY_COMPANIES.length;
  let zeroCompanies = Array.isArray(input.mustApplyZeroHealthyCompanies)
    ? input.mustApplyZeroHealthyCompanies
    : [];
  let zeroCount = Array.isArray(input.mustApplyZeroHealthyCompanies)
    ? zeroCompanies.length
    : toNumber(input.mustApplyZeroHealthyCompanies);
  let blindCompanies = input.mustApplyBlindCompanies || [];
  let worstIndustry: NonNullable<typeof input.mustApplyIndustries>[number] | undefined;
  let mustApply = mustApplyBand(healthyCompanies, zeroCount);
  if (input.mustApplyIndustries) {
    const rank: Record<HealthBand, number> = { empty: 0, good: 1, warn: 2, bad: 3 };
    for (const industry of input.mustApplyIndustries) {
      const industryBand = mustApplyBand(industry.healthy, industry.zeroHealthyCompanies.length);
      if (!worstIndustry || rank[industryBand] > rank[mustApplyBand(worstIndustry.healthy, worstIndustry.zeroHealthyCompanies.length)]) {
        worstIndustry = industry;
        mustApply = industryBand;
      }
    }
    if (worstIndustry) {
      healthyCompanies = worstIndustry.healthy;
      mustApplyTotal = worstIndustry.total;
      zeroCompanies = worstIndustry.zeroHealthyCompanies;
      zeroCount = zeroCompanies.length;
      blindCompanies = worstIndustry.blindCompanies;
    }
  }
  const coverage = coverageBand(input.coverageAvgPct);
  const coverageBlindSources = toNumber(input.coverageBlindSources);
  const allCrawlsFailed = crawlRuns > 0 && failedRuns >= crawlRuns;

  const actions: string[] = [];
  if (worstIndustry && mustApply !== "good" && healthyCompanies !== null) {
    const scopePrefix = worstIndustry.scope === "overseas" ? "海外·" : "";
    actions.push(
      `${scopePrefix}${worstIndustry.industry}行业必投覆盖 ${healthyCompanies}/${mustApplyTotal}（目标≥${HEALTH_THRESHOLDS.mustApplyHealthyCompanies.good}/30）`,
    );
  }
  if (zeroCount > 0) {
    const label = zeroCompanies.length ? capList(zeroCompanies) : `${zeroCount} 家`;
    actions.push(`${label}：必投公司零健康岗`);
  }
  if (healthyCompanies === null) {
    actions.push("必投清单覆盖率读不出来，岗位库这次没查通，先看这里。");
  }
  if (clickValidity === "bad" || clickValidity === "warn") {
    actions.push(`点击有效率 ${formatRateForAction(clickRate)}（目标≥99%）`);
  }
  if (validActive === null) {
    actions.push("岗位库统计读不出来，先确认岗位库连得上。");
  } else if (validActive <= 0) {
    actions.push("当前没有能投岗位，请立即检查岗位库。");
  }
  if (allCrawlsFailed) {
    actions.push("今天岗位抓取全部失败，请检查抓取任务。");
  } else if (crawlRuns <= 0) {
    actions.push("今天还没有抓取记录，可能是每天的定时抓取还没到点。");
  }
  if (!worstIndustry && mustApply === "warn" && zeroCount === 0 && healthyCompanies !== null) {
    actions.push(`必投清单健康覆盖 ${healthyCompanies}/${mustApplyTotal}（目标≥28/30）`);
  }
  if (blindCompanies.length > 0) {
    actions.push(`${capList(blindCompanies)}：有岗但 72h 未核验`);
  }
  if (coverage === "bad" || coverage === "warn") {
    actions.push(`全库抓全率 ${input.coverageAvgPct == null ? "暂无数据" : `${toNumber(input.coverageAvgPct)}%`}（目标≥90%）`);
  }
  if (coverageBlindSources > 0) {
    actions.push(`${coverageBlindSources} 个招聘源算不出抓全率，先看可测源。`);
  }

  const critical =
    (validActive !== null && validActive <= 0) ||
    allCrawlsFailed ||
    clickValidity === "bad" ||
    mustApply === "bad";
  const warning =
    !critical &&
    (validActive === null ||
      crawlRuns <= 0 ||
      mustApply === "empty" ||
      mustApply === "warn" ||
      zeroCount > 0 ||
      blindCompanies.length > 0 ||
      coverage === "bad" ||
      coverage === "warn" ||
      clickValidity === "warn");

  if (critical) {
    return {
      level: "critical",
      label: "出事",
      message: "核心承诺有红线，请先处理下方最靠前的问题。",
      actions: actions.slice(0, 3),
      bands: { clickValidity, mustApply, coverage },
    };
  }
  if (warning) {
    return {
      level: "warning",
      label: "注意",
      message: "产品可用，但有会影响信任或覆盖的风险点。",
      actions: actions.slice(0, 3),
      bands: { clickValidity, mustApply, coverage },
    };
  }
  return {
    level: "healthy",
    label: "健康",
    message: "必投清单、点击有效率和今日抓取都在阈值内。",
    actions: ["核心承诺正常：必投清单、点击有效率、今日抓取都在阈值内。"],
    bands: { clickValidity, mustApply, coverage },
  };
}

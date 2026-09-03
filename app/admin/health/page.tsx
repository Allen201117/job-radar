import AdminNav from "@/components/AdminNav";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import UserBehaviorReport from "@/components/admin/UserBehaviorReport";
import { getUserAnalytics, type UserAnalytics } from "@/lib/admin-user-analytics";
import { AnimatedStat } from "@/components/ui/animated-stat";
import { BarList, Callout, HEALTH_STATUS_META, KpiCard, StatRing, StatusBadge, StatusDot, Tracker, type TrackerItem } from "@/components/health-viz";
import { cn } from "@/lib/utils";
import {
  band,
  bandTone,
  buildMustApplyGovernanceItems,
  buildDailyReports,
  computeMustApplySupplyLedger,
  computeClickValidityMetrics,
  coverageBand,
  dailyRunTone,
  evaluateCombinedHealth,
  formatPercent,
  getCoverageSnapshot,
  getMustApplyFetchCoverage,
  groupFetchCoverageByIndustry,
  HEALTH_THRESHOLDS,
  normalizeCrawlSources,
  summarizeMustApplyGapAttempts,
  translateOperationalTerm,
  verdictTone,
  type ClickValidityMetrics,
  type CoverageSnapshot,
  type CrawlSourceRow,
  type DailyReport,
  type BandTone,
  type HealthBand,
  type MustApplyFetchCoverage,
  type MustApplyFetchCoverageCompany,
  type OpsRunAggregateRow,
  type OpsRunRow,
  type GapFunnelOpsRow,
  type MustApplyGapAttemptRow,
  type MustApplyGovernanceItem,
  type MustApplyGapSummary,
  type TodayCrawlRow,
  type TodayDiscoveryRow,
} from "@/lib/admin-health";
import { isAdmin } from "@/lib/auth";
import { getJobsHealthSnapshot, getMustApplyCoverage, type JobsHealthSnapshot, type MustApplyCoverageRow } from "@/lib/jobs-store/read";
import {
  DEFAULT_MUST_APPLY_INDUSTRY,
  industriesForPattern,
  mustApplyByIndustry,
  MUST_APPLY_BY_INDUSTRY,
  MUST_APPLY_INDUSTRIES,
  MUST_APPLY_VERSION,
  mustApplyUnion,
  resolveMustApplyIndustries,
  resolveMustApplyScopes,
  type MustApplyScope,
} from "@/lib/must-apply-list";
import { canonicalizeUserIndustry } from "@/lib/company-industry";
import { createServiceClient } from "@/lib/supabaseService";
import { fetchAllPages, fetchAllSources } from "@/lib/supabase-paginate";
import { nullableShare } from "@/lib/admin-health-tracker";
import { Clock, ShieldCheck } from "@phosphor-icons/react/ssr";
import { redirect } from "next/navigation";
import { unstable_cache } from "next/cache";

export const dynamic = "force-dynamic";

type SupabaseHealthSnapshot = {
  window_days?: number;
  crawl_sources?: CrawlSourceRow[];
  insight?: {
    active_total?: number;
    disputes_total?: number;
    disputes_open?: number;
    today_created?: number;
  };
  today?: {
    crawl?: TodayCrawlRow;
    discovery?: TodayDiscoveryRow;
    ops_runs?: OpsRunAggregateRow[];
    users?: {
      total_users?: number;
      today_users?: number;
      users_with_preferences?: number;
      saved_users?: number;
      applied_users?: number;
      saved_total?: number;
      saved_today?: number;
      applied_total?: number;
      applied_today?: number;
    };
    resume?: {
      started?: number;
      succeeded?: number;
      llm?: number;
      rule?: number;
    };
  };
};

type HealthDailySeries = {
  days?: Array<{
    day?: string;
    ops?: { runs?: number; failed?: number; partial?: number };
    crawl?: { runs?: number; failed?: number; partial?: number };
    north_star?: { healthy?: number; total?: number; written_at?: string } | null;
  }>;
};

// ── 跨实例缓存 ────────────────────────────────────────────────────────────
// 运营看板是「看今天跑得怎么样」，不需要秒级实时；但此前整页 force-dynamic + 零缓存，
// 每有人打开一次就把下面这些重查询全部重算一遍。2026-09-03 线上实测：
// 总览 5.6s / 必投供给 6.2s（首字节只要 ~55ms，慢的全在服务端算数据这一段），
// 且几条重查询并发时会互相抢资源，越并发越慢（单跑 0.8s 的 RPC 三条并发涨到 2.6s）。
//
// ⚠️ 缓存函数体内不得读 cookies()/headers()（unstable_cache 的限制）。
// 下面全部走 service-role 客户端，与请求身份无关，天然满足。
// ⚠️ 缓存的是「取数结果」，红黄绿判定与文案仍每请求现算——阈值调整能立刻生效。
const ADMIN_DATA_TTL_SECONDS = 180;

function cachedLoader<T>(key: string, loader: () => Promise<T>): () => Promise<T> {
  const cached = unstable_cache(loader, ["admin-health", key], {
    revalidate: ADMIN_DATA_TTL_SECONDS,
    tags: ["admin-health"],
  });
  // unstable_cache 只在 Next 请求上下文里可用，单测/脚本里调用会抛
  // 「Invariant: incrementalCache missing」→ 退回直查，别让缓存变成新的失败点。
  // 只吞这一种错，其余原样抛出。
  return async () => {
    try {
      return await cached();
    } catch (error) {
      if (!(error instanceof Error) || !/incrementalCache missing/i.test(error.message)) throw error;
      return loader();
    }
  };
}

const loadSupabaseHealth = cachedLoader<SupabaseHealthSnapshot>("supabase-health", async () => {
  const service = createServiceClient();
  const { data, error } = await service.rpc("admin_health_snapshot", { p_window: "7 days" });
  if (error) throw new Error(error.message);
  return (data || {}) as SupabaseHealthSnapshot;
});

const loadHealthDailySeries = cachedLoader<HealthDailySeries>("daily-series", async () => {
  const service = createServiceClient();
  const { data, error } = await service.rpc("admin_health_daily_series", { p_days: 30 });
  if (error) throw new Error(error.message);
  return (data || {}) as HealthDailySeries;
});

// 缺口漏斗 / 校招供给这 5 个模块每天都在写 ops_runs，却一直没进看板；
// 而 admin_health_snapshot 只抽了固定 6 个指标键，它们的产出口径（sources_added / snapshots …）不在里面
// → 直接读今天的原始台账行，产出数字才有真实来源。
const EXTRA_OPS_MODULES = ["gap_funnel", "gap_funnel_browser", "campus_lane", "campus_cycle_backlog", "campus_official_backlog"];

function shanghaiToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

const loadExtraOpsRuns = cachedLoader<OpsRunRow[]>("extra-ops-runs", async () => {
  const service = createServiceClient();
  return fetchAllPages<OpsRunRow>((from, to) =>
    service
      .from("ops_runs")
      .select("id,module,status,metrics,started_at,finished_at")
      .in("module", EXTRA_OPS_MODULES)
      .eq("run_date", shanghaiToday())
      .order("id", { ascending: true })
      .range(from, to),
  );
});

// 北极星：必投清单健康覆盖。jobs 在香港库、sources 在 Supabase，无法单条 SQL join → Node 层按公司名 needle 合并。
type MustApplyRow = MustApplyCoverageRow & { pattern: string; hasSource: boolean; sourceEnabled: boolean };
type MustApplyRowsByIndustry = Record<string, MustApplyRow[]>;
type MustApplyRowsByScope = Record<MustApplyScope, MustApplyRowsByIndustry>;
type UserIndustryDistribution = { counts: Record<MustApplyScope, Record<string, number>>; scopeUsers: Record<MustApplyScope, number>; unset: number };
const MUST_APPLY_SCOPES: MustApplyScope[] = ["domestic", "overseas"];
const MUST_APPLY_SCOPE_LABEL: Record<MustApplyScope, string> = { domestic: "国内", overseas: "海外" };

type SourceRow = { company: string | null; enabled: boolean };
type MustApplyGapAdminData = {
  attempts: MustApplyGapAttemptRow[];
  opsRuns: GapFunnelOpsRow[];
};

/** 库里全部源（含 disabled），用于判断必投公司「有没有接过源」。
 * ⚠️ 必须分页拉全量：PostgREST 单次 select 默认最多返回 1000 行，而 sources 已越过 1000
 * （2026-07-20 实测 1121）→ 不分页拿到的是**残缺**集合，尾部公司被误判「从未接入」
 * → 北极星「必投清单健康覆盖」的 hasSource 残缺、覆盖率虚低。
 * 分页语义（含为何必须带稳定排序键）见 lib/supabase-paginate.ts。 */
const loadAllSources = cachedLoader<SourceRow[]>("all-sources", () =>
  fetchAllSources<SourceRow>(createServiceClient(), "company, enabled"));

function buildMustApplyRowsForScope(
  scope: MustApplyScope,
  sources: SourceRow[],
  coverage: MustApplyCoverageRow[],
): MustApplyRowsByIndustry {
  const union = mustApplyUnion(scope);
  const rows = union.map((c, i) => {
    const needle = c.pattern.replace(/%/g, "").toLowerCase();
    const matched = sources.filter((s) => (s.company || "").toLowerCase().includes(needle));
    return {
      ...coverage[i],
      pattern: c.pattern,
      hasSource: matched.length > 0,
      sourceEnabled: matched.some((s) => s.enabled),
    };
  });
  return Object.fromEntries(
    MUST_APPLY_INDUSTRIES.map((industry) => [
      industry,
      rows.filter((row) => industriesForPattern(row.pattern, scope).includes(industry)),
    ]),
  );
}

async function loadMustApplyCoverage(): Promise<MustApplyRowsByScope> {
  // sources（Supabase 全量分页 ~560ms）与 coverage（香港库聚合 ~1.1s）互不依赖 → 并行，
  // 别退回「先 await sources 再查 coverage」，那是白白把两者串起来。
  // sources 与 scope 无关，两个 scope 共用一份，省掉一次全量分页拉取；
  // getMustApplyCoverage 内部共用同一份公司聚合（in-flight 合并），两个 scope 只查一次库。
  const [sources, coverages] = await Promise.all([
    loadAllSources(),
    Promise.all(MUST_APPLY_SCOPES.map((scope) => getMustApplyCoverage(mustApplyUnion(scope)))),
  ]);
  return Object.fromEntries(
    MUST_APPLY_SCOPES.map((scope, i) => [scope, buildMustApplyRowsForScope(scope, sources, coverages[i])]),
  ) as MustApplyRowsByScope;
}

async function loadMustApplyGapAdminData(): Promise<MustApplyGapAdminData> {
  const service = createServiceClient();
  const [attempts, opsResult] = await Promise.all([
    fetchAllPages<MustApplyGapAttemptRow>((from, to) =>
      service
        .from("must_apply_gap_attempts")
        .select("id,company,industries,state,fail_reason,attempts,rounds_no_entry,last_attempt_at,next_retry_at,evidence")
        .eq("scope", "domestic")
        .order("id", { ascending: true })
        .range(from, to),
    ),
    service
      .from("ops_runs")
      .select("module,run_date,finished_at,metrics")
      .in("module", ["gap_funnel", "gap_funnel_browser"])
      .order("finished_at", { ascending: false })
      .limit(20),
  ]);
  if (opsResult.error) throw new Error(opsResult.error.message);
  return {
    attempts,
    opsRuns: (opsResult.data || []) as GapFunnelOpsRow[],
  };
}

async function loadUserIndustryDistribution(): Promise<UserIndustryDistribution> {
  const { data, error } = await createServiceClient().from("user_preferences").select("target_industries, job_scope");
  if (error) throw new Error(error.message);
  const counts: Record<MustApplyScope, Record<string, number>> = { domestic: {}, overseas: {} };
  const scopeUsers: Record<MustApplyScope, number> = { domestic: 0, overseas: 0 };
  let unset = 0;
  for (const row of (data || []) as Array<{ target_industries?: unknown; job_scope?: unknown }>) {
    const raw = Array.isArray(row.target_industries) ? row.target_industries : [];
    const normalized = raw.map((value) => canonicalizeUserIndustry(String(value))).filter((value): value is string => Boolean(value));
    if (!normalized.length) unset += 1;
    const industries = resolveMustApplyIndustries(normalized);
    for (const scope of resolveMustApplyScopes(typeof row.job_scope === "string" ? row.job_scope : null)) {
      scopeUsers[scope] += 1;
      for (const industry of industries) counts[scope][industry] = (counts[scope][industry] || 0) + 1;
    }
  }
  return { counts, scopeUsers, unset };
}

// 点击有效率四护栏（01 spec §5）：近 7 天 opportunity_official_opened + job_liveness_at_click 聚合。
async function loadClickValidity(): Promise<ClickValidityMetrics> {
  const service = createServiceClient();
  const since = new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString();
  const { data, error } = await service
    .from("events")
    .select("event, payload")
    .in("event", ["opportunity_official_opened", "job_liveness_at_click"])
    .gte("created_at", since)
    .limit(10000);
  if (error) throw new Error(error.message);
  return computeClickValidityMetrics((data || []) as Array<{ event?: unknown; payload?: unknown }>);
}

async function loadCoverageSnapshot(): Promise<CoverageSnapshot> {
  return getCoverageSnapshot(createServiceClient());
}

function formatRate(rate: number | null): string {
  return rate == null ? "—" : `${(rate * 100).toFixed(1)}%`;
}

const share = nullableShare;

function sectionStatusFromBand(value: HealthBand): BandTone {
  return bandTone(value);
}

function worstBand(values: HealthBand[]): HealthBand {
  if (values.includes("bad")) return "bad";
  if (values.includes("warn")) return "warn";
  if (values.includes("good")) return "good";
  return "empty";
}

function ErrorPanel({ label }: { label: string }) {
  return (
    <div
      role="alert"
      className="rounded-2xl border border-[#e0b4ac] bg-[#f7e6e1] px-4 py-3 text-sm text-[#9c4a3c] dark:border-[#7a392e]/60 dark:bg-[#3a201a] dark:text-[#e6a99f]"
    >
      {label}暂不可用。其他数据区仍可正常查看，请稍后重试。
    </div>
  );
}

function formatCount(value: number | null | undefined): string {
  return value == null ? "—" : value.toLocaleString("zh-CN");
}

function formatRunTime(value: string | null): string {
  if (!value) return "今日暂无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "今日暂无记录";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatRunDateTime(value: string | null): string {
  if (!value) return "暂无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "暂无记录";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function displayEmptyRate(value: string): string {
  return value;
}

function percentToRatio(value: number | null): number | null {
  return value == null ? null : value / 100;
}

function parsePercentRatio(value: string): number | null {
  if (value === "—") return null;
  const n = Number(value.replace("%", ""));
  return Number.isFinite(n) ? n / 100 : null;
}

function sourceStatusLabel(row: Pick<MustApplyRow, "hasSource" | "sourceEnabled">): string {
  if (!row.hasSource) return "从未接入";
  return row.sourceEnabled ? "已接入" : "源已禁用";
}

function actionAnchor(action: string): string {
  if (/必投|覆盖|补源|行业|公司|供给/.test(action)) return "/admin/health?tab=supply";
  if (/探活|失效|过期|空壳|岗位|官网|质量|核验/.test(action)) return "/admin/health?tab=jobs";
  if (/投递|机会|点击|回访|用户/.test(action)) return "/admin/health?tab=users";
  return "/admin/health?tab=system";
}

function displayOperationMetricLabel(label: string): string {
  if (label === "判死") return translateOperationalTerm("today_removed");
  return label;
}

// 「跑没跑」是一句话，「产出多少」是另一句话，分开写、各自上色。
// 合并成一个「● 正常」正是看板说谎的来源（10 个挂 9 个也叫正常、产出 0 也叫正常）。
function runSignalText(report: DailyReport): string {
  if (report.runs <= 0) return "今天没有运行记录";
  if (report.failed <= 0) return `今天跑了 ${formatCount(report.runs)} 次 · 全部成功`;
  return `今天跑了 ${formatCount(report.runs)} 次 · 失败 ${formatCount(report.failed)} 次（${formatPercent(report.failed, report.runs)}）`;
}

function outputSignalText(report: DailyReport): string {
  if (report.produced == null) return "产出暂无数据";
  if (report.produced > 0) return "有产出";
  return report.expectsOutput ? "产出为 0" : "产出为 0（不计入判断）";
}

function OperationCard({ report }: { report: DailyReport }) {
  return (
    <article className="surface-soft flex h-full flex-col p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold ink-1 ">{report.title}</h3>
          <p className="mt-1 text-pretty text-xs leading-5 ink-3 ">
            {report.description}
          </p>
        </div>
        <StatusBadge tone={verdictTone(report.verdict)} label={report.verdictLabel} />
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        <KpiCard
          title="运行情况"
          value={report.runs <= 0 ? "—" : `${formatCount(report.runs)} 次`}
          tone={report.runTone}
          detail={runSignalText(report)}
          className="min-h-0 p-3"
        />
        <KpiCard
          title={report.producedLabel}
          value={report.produced == null ? "—" : formatCount(report.produced)}
          tone={report.producedTone}
          detail={report.producedCaption}
          className="min-h-0 p-3"
        />
      </div>

      <div className={`mt-2 grid grid-cols-2 gap-2 ${report.metrics.length >= 3 ? "sm:grid-cols-3" : ""}`}>
        {report.metrics.map((metric) => (
          <KpiCard
            key={metric.label}
            title={displayOperationMetricLabel(metric.label)}
            value={metric.value == null ? "—" : formatCount(metric.value)}
            tone="muted"
            detail={metric.value == null ? "该指标仍在积累" : "今日台账"}
            className="min-h-0 p-3"
          />
        ))}
      </div>

      <p className="mt-auto flex items-center gap-1.5 pt-4 text-xs ink-3 ">
        <Clock size={14} aria-hidden="true" />
        上次运行：{formatRunTime(report.lastRunAt)}
      </p>
    </article>
  );
}

function AccumulatingMetric({ title, description, items = [] }: { title: string; description: string; items?: TrackerItem[] }) {
  return (
    <div className="rounded-2xl border border-dashed border-black/10 bg-white/35 p-4 dark:border-white/10 dark:bg-white/[0.03]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium ink-2 ">{title}</p>
          <p className="mt-2 text-pretty text-xs leading-5 ink-3 ">{description}</p>
        </div>
        <span className="shrink-0 rounded-full bg-[#ece7dd] px-2.5 py-1 text-[11px] font-semibold ink-2 dark:bg-white/[0.08] ">
          积累中
        </span>
      </div>
      {items.length > 0 && <Tracker className="mt-4" items={items} ariaLabel={`${title}最近 30 天积累情况`} />}
    </div>
  );
}

function shortDay(value: string | undefined): string {
  return value ? value.slice(5) : "未知日期";
}

function northStarTrackerItems(series: HealthDailySeries | null): TrackerItem[] {
  return (series?.days || []).map((day) => {
    const snapshot = day.north_star;
    const healthy = snapshot?.healthy ?? null;
    return {
      label: snapshot ? `${shortDay(day.day)}：${formatCount(snapshot.healthy)}/${formatCount(snapshot.total)} 家有健康岗` : `${shortDay(day.day)}：暂无快照`,
      tone: healthy == null ? "muted" : bandTone(band(healthy, HEALTH_THRESHOLDS.mustApplyHealthyCompanies, "higher")),
    };
  });
}

// 热力图与模块卡共用 lib/admin-health 的 moduleVerdict（dailyRunTone 是它的日序列包装），
// 不再各写一套 —— 曾经热力图「任一失败即红」而模块卡「全挂才算失败」，同一天一个红一个绿。
function processTrackerItems(series: HealthDailySeries | null, key: "ops" | "crawl"): TrackerItem[] {
  return (series?.days || []).map((day) => {
    const run = day[key];
    const tone = dailyRunTone(run);
    const label = run?.runs == null
      ? `${shortDay(day.day)}：暂无记录`
      : `${shortDay(day.day)}：运行 ${formatCount(run.runs)} 次，失败 ${formatCount(run.failed)} 次，部分完成 ${formatCount(run.partial)} 次`;
    return { label, tone };
  });
}

function CoverageBarList({
  items,
  emptyLabel,
}: {
  items: Array<{
    key: string;
    label: string;
    pct: number | null;
    fetched?: number | null;
    total?: number | null;
    caption?: string;
  }>;
  emptyLabel: string;
}) {
  if (items.length === 0) {
    return (
      <p className="rounded-2xl border border-dashed border-black/10 bg-white/35 px-4 py-5 text-sm ink-3 dark:border-white/10 dark:bg-white/[0.03] ">
        {emptyLabel}
      </p>
    );
  }

  return <BarList ariaLabel="逐家公司抓全比例" items={items.map((item) => ({
    key: item.key,
    label: item.label,
    ratio: item.pct == null ? null : item.pct / 100,
    tone: bandTone(coverageBand(item.pct)),
    caption: item.caption,
    value: item.pct == null ? "—" : `${item.pct}%`,
    valueDetail: item.fetched != null && item.total != null ? `${formatCount(item.fetched)}/${formatCount(item.total)}` : undefined,
  }))} />;
}

function CoverageSection({
  snapshot,
}: {
  snapshot: CoverageSnapshot | null;
}) {
  if (!snapshot) {
    return <ErrorPanel label="抓全比例" />;
  }

  const hasCoverageData =
    snapshot.measurable > 0 ||
    snapshot.blind > 0 ||
    snapshot.avgCoveragePct != null ||
    snapshot.underCount > 0 ||
    snapshot.underSources.length > 0;
  const averageTone = bandTone(coverageBand(snapshot.avgCoveragePct));

  return (
    <>
      {!hasCoverageData ? (
        <AccumulatingMetric title="抓得全不全" description="要先有一次抓取填入「官网一共挂了多少个岗」，才算得出这个数。" />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard
              title="平均抓到几成"
              value={snapshot.avgCoveragePct == null ? "—" : `${snapshot.avgCoveragePct}%`}
              tone={averageTone}
              detail={`官网挂出来的岗位，我们平均抓到了几成。目标 ${HEALTH_THRESHOLDS.coveragePct.good}%。`}
              footnote="有些公司官网不写「共几个岗」，那种算不出来，不计入平均"
            />
            <KpiCard title="算得出的公司" value={formatCount(snapshot.measurable)} tone="muted" detail="官网明写「共有 N 个岗」，才能跟我们抓到的数对账" />
            <KpiCard title="没抓全的公司（不到 90%）" value={formatCount(snapshot.underCount)} tone={snapshot.underCount > 0 ? "warning" : "success"} detail="具体是哪几家列在下面" />
            <KpiCard title="算不出的公司" value={formatCount(snapshot.blind)} tone="muted" detail="官网不写总数，所以无从判断抓没抓全——不能当成「抓漏了」" />
          </div>
          <p className="mt-3 text-xs leading-5 ink-3 ">
            盲区=官网接口不报总数，算不出，非抓漏。
          </p>

          <div className="mt-5">
            <CoverageBarList
              emptyLabel="暂无抓全率低于 90% 的公司。"
              items={snapshot.underSources.map((source) => ({
                key: `${source.company}-${source.adapter}-${source.lastRunAt || "none"}`,
                label: source.company,
                pct: source.coveragePct,
                fetched: source.fetched,
                total: source.reportedTotal,
                caption: `${source.adapter} · 上次 ${formatRunDateTime(source.lastRunAt)}`,
              }))}
            />
          </div>
        </>
      )}
    </>
  );
}

// 北极星卡：必投清单健康覆盖。回答「目标用户最想投的头部公司，我们到底罩住了几家」——
// 这是产品对用户承诺的真实覆盖率，掉了要优先修它，别被库存总量的大数字安慰。
function MustApplyFetchCoverageBlock({ coverage }: { coverage: MustApplyFetchCoverage | null }) {
  if (!coverage) {
    return (
      <div className="mt-5 border-t border-black/[0.06] pt-5 dark:border-white/[0.08]">
        <ErrorPanel label="必投 30 家抓到几成" />
      </div>
    );
  }

  const total = coverage.total;
  const leaking = coverage.companies.filter(
    (company): company is MustApplyFetchCoverageCompany & { coveragePct: number } =>
      company.coveragePct !== null && company.coveragePct < 90,
  );
  const averageTone = bandTone(coverageBand(coverage.avgPct));

  return (
    <div className="mt-5 border-t border-black/[0.06] pt-5 dark:border-white/[0.08]">
      <div className="mb-3">
        <h3 className="font-semibold ink-1 ">必投 30 家抓到几成</h3>
        <p className="mt-1 text-xs leading-5 ink-3 ">
          官网总数 vs 我们抓到；抓全率低于 90% 的公司排在前面。
        </p>
      </div>

      {coverage.measurable === 0 && coverage.companies.length === 0 ? (
        <AccumulatingMetric title="必投 30 家抓到几成" description="还没有一次抓取填入「官网共几个岗」，暂时算不出抓到几成。" />
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-[8.5rem_1fr] lg:items-center">
            <StatRing pct={percentToRatio(coverage.avgPct)} tone={averageTone} size="section" target={0.9}>
              <span className="text-lg font-semibold tabular-nums ink-1 ">
                {coverage.avgPct == null ? "积累中" : `${coverage.avgPct}%`}
              </span>
              <span className="mt-0.5 text-[10px] ink-3 ">平均抓到几成</span>
            </StatRing>
            <div className="grid gap-3 sm:grid-cols-3">
              <KpiCard title="抓全家数" value={`${coverage.fullyFetched}/${total}`} tone="muted" detail="≥90% 才算抓全" className="min-h-0" />
              <KpiCard title="算不出的公司" value={formatCount(coverage.blind)} tone="muted" detail="官网不报总数" className="min-h-0" />
              <KpiCard title="可测公司" value={formatCount(coverage.measurable)} tone="muted" detail="只用「官网写了总数」的公司算平均" className="min-h-0" />
            </div>
          </div>

          {coverage.measurable === 0 ? (
            <p className="mt-4 rounded-2xl border border-dashed border-black/10 bg-white/35 px-4 py-5 text-sm ink-3 dark:border-white/10 dark:bg-white/[0.03] ">
              必投清单还没有可计算官网总数的数据，等下一轮抓取填入后展示明细。
            </p>
          ) : (
            <div className="mt-4">
              <CoverageBarList
                emptyLabel="暂无抓全率低于 90% 的必投公司。"
                items={leaking.map((company) => ({
                  key: company.pattern || company.name,
                  label: company.name,
                  pct: company.coveragePct,
                  fetched: company.fetched,
                  total: company.reportedTotal,
                }))}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MustApplyIndustryBlock({
  rows,
  fetchCoverage,
  healthBand = "empty",
  summary,
  scope,
  industry,
  userCount,
  embedded = false,
}: {
  rows: MustApplyRow[] | null;
  fetchCoverage: MustApplyFetchCoverage | null;
  healthBand?: HealthBand;
  summary?: string;
  scope: MustApplyScope;
  industry: string;
  userCount: number;
  // 嵌在折叠列表里时，标题与状态已经写在折叠条上了，再套一层卡片+标题就是重复噪音。
  embedded?: boolean;
}) {
  const status = sectionStatusFromBand(healthBand);
  if (!rows) {
    return (
      <div className={embedded ? "" : "surface-soft p-5 sm:p-6"}>
        {!embedded && (
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="t-h2 ink-1">{MUST_APPLY_SCOPE_LABEL[scope]}必投清单健康覆盖 · {industry}（{userCount} 位用户）</h2>
              <p className="t-body-sm mt-1 ink-2">目标用户最常投的头部公司逐家对账。</p>
            </div>
            <StatusBadge tone="muted" />
          </div>
        )}
        <ErrorPanel label="必投清单覆盖" />
        <MustApplyFetchCoverageBlock coverage={fetchCoverage} />
      </div>
    );
  }
  const n = rows.length;
  const healthyCount = rows.filter((r) => r.healthy > 0).length;
  const freshCount = rows.filter((r) => r.new7d > 0).length;
  const checkedCount = rows.filter((r) => r.checked72h > 0).length;
  const gaps = rows.filter((r) => r.healthy === 0);
  const blind = rows.filter((r) => r.healthy > 0 && r.checked72h === 0);
  const parentCovered = rows.filter((r) => r.coveredViaParentPortal);
  const gridCells = rows.map((r) => {
    const tone: BandTone = r.healthy === 0 ? "danger" : r.checked72h === 0 ? "warning" : "success";
    return {
      tone,
      label: `${r.name}｜健康岗 ${r.healthy}·近7天新 ${r.new7d}·72h核验 ${r.checked72h}｜${sourceStatusLabel(r)}${r.coveredViaParentPortal ? "｜通过母公司的招聘页覆盖到" : ""}`,
    };
  });
  return (
    <div className={embedded ? "" : "surface-soft p-5 sm:p-6"}>
      {!embedded && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="t-h2 ink-1">{MUST_APPLY_SCOPE_LABEL[scope]}必投清单健康覆盖 · {industry}（{userCount} 位用户）</h2>
            <p className="t-body-sm mt-1 max-w-3xl leading-6 ink-2">
              30 家目标公司一家家对账：有没有能投的岗、最近 7 天有没有新岗、72 小时内有没有查过这些岗还在不在。这里掉了，岗位总量再大也不算健康。
            </p>
          </div>
          <StatusBadge tone={status} />
        </div>
      )}
      {!embedded && summary && <p className="t-body-sm mb-4 ink-2">{summary}</p>}

      <div className="grid gap-5 lg:grid-cols-[11rem_1fr] lg:items-center">
        <div className="flex justify-center lg:justify-start">
          <StatRing pct={share(healthyCount, n)} tone={bandTone(healthBand)} size="section" target={28 / 30}>
            <span className="inline-flex items-baseline gap-0.5 text-3xl font-semibold tabular-nums ink-1 ">
              <AnimatedStat value={healthyCount} />
              <span className="text-sm">/30</span>
            </span>
            <span className="mt-1 text-[11px] leading-4 ink-2 ">家有健康岗</span>
          </StatRing>
        </div>
        <div className="min-w-0">
          <Tracker items={gridCells} ariaLabel="必投清单逐家公司状态" />
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard title="最近 7 天有新岗" value={`${freshCount}/${n}`} tone="muted" detail="说明这家还在持续放岗，但不用它判断健康与否" className="min-h-0" />
        <KpiCard title="72 小时内查过" value={`${checkedCount}/${n}`} tone={blind.length > 0 ? "warning" : "success"} detail="有岗但没查过的公司，会在下面点名" className="min-h-0" />
        <KpiCard title="健康覆盖目标" value={`≥${HEALTH_THRESHOLDS.mustApplyHealthyCompanies.good}/30`} tone={bandTone(healthBand)} detail="24 至 27 家为关注，低于 24 家需处理" className="min-h-0" />
      </div>

      {(gaps.length > 0 || blind.length > 0) && (
        <div className="mt-4 space-y-2 text-sm leading-6">
          {gaps.length > 0 && (
            <p className="rounded-2xl border border-[#e0b4ac] bg-[#f7e6e1] px-3.5 py-2.5 text-[#9c4a3c] dark:border-[#7a392e]/60 dark:bg-[#3a201a] dark:text-[#e6a99f]">
              零健康岗：{gaps.map((r) => `${r.name}${r.hasSource ? (r.sourceEnabled ? "（有源不产出）" : "（源已禁用）") : "（从未接入）"}`).join("、")}
            </p>
          )}
          {blind.length > 0 && (
            <p className="rounded-2xl border border-[#edc995] bg-[#fbecd7] px-3.5 py-2.5 text-[#8f6225] dark:border-[#825d28]/60 dark:bg-[#392a17] dark:text-[#e0b15a]">
              有岗、但 72 小时内没查过还在不在：{blind.map((r) => r.name).join("、")}
            </p>
          )}
        </div>
      )}
      {parentCovered.length > 0 && (
        <p className="mt-4 rounded-2xl border border-[#b8c9b8] bg-[#edf3e8] px-3.5 py-2.5 text-sm text-[#476047] dark:border-[#557055]/60 dark:bg-[#1d2b1d] dark:text-[#b9d2b5]">
          通过母公司的招聘页覆盖到：{parentCovered.map((row) => `${row.name}（${row.parentPortalHealthy} 条健康岗）`).join("、")}。这些不是独立接入的子品牌招聘页。
        </p>
      )}
      <MustApplyFetchCoverageBlock coverage={fetchCoverage} />
    </div>
  );
}

function mustApplyIndustryBand(rows: MustApplyRow[] | null): HealthBand {
  if (!rows) return "empty";
  const healthy = rows.filter((row) => row.healthy > 0).length;
  const zeroHealthy = rows.length - healthy;
  if (zeroHealthy >= HEALTH_THRESHOLDS.mustApplyZeroHealthyCompanies.bad) return "bad";
  if (healthy >= HEALTH_THRESHOLDS.mustApplyHealthyCompanies.good) {
    return zeroHealthy >= HEALTH_THRESHOLDS.mustApplyZeroHealthyCompanies.warn ? "warn" : "good";
  }
  return healthy >= HEALTH_THRESHOLDS.mustApplyHealthyCompanies.warn ? "warn" : "bad";
}

// 必投清单：一行一个行业的折叠列表。
//
// 改造前的形态是「国内一大段 + 海外一大段，每个活跃行业展开成一张巨卡」——
// 11 个行业 × 2 个范围最多 22 张巨卡叠在一页，既没法横向比、也分不清哪个最该修。
// 现在：范围用切换器分开（不再揉一起），行业收成一行、按严重程度排序，点开才看细节。
function MustApplyIndustryRow({
  scope,
  industry,
  rows,
  fetchCoverage,
  userCount,
  isReserve,
}: {
  scope: MustApplyScope;
  industry: string;
  rows: MustApplyRow[] | null;
  fetchCoverage: MustApplyFetchCoverage | null;
  userCount: number;
  isReserve: boolean;
}) {
  const total = rows?.length || mustApplyByIndustry(scope)[industry]?.length || 30;
  const healthy = rows ? rows.filter((row) => row.healthy > 0).length : null;
  const withSource = rows ? rows.filter((row) => row.hasSource).length : null;
  const gaps = rows ? rows.filter((row) => row.healthy === 0).length : 0;
  const blind = rows ? rows.filter((row) => row.healthy > 0 && row.checked72h === 0).length : 0;
  const healthBand = mustApplyIndustryBand(rows);
  const tone = rows ? bandTone(healthBand) : "muted";
  const ratio = healthy != null && total > 0 ? healthy / total : null;

  return (
    <details className="group border-t border-black/[0.06] first:border-t-0 dark:border-white/[0.08]">
      <summary className="grid cursor-pointer list-none grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-1 py-3.5 transition hover:bg-black/[0.025] sm:px-2 dark:hover:bg-white/[0.04]">
        <span aria-hidden="true" className="t-caption w-4 shrink-0 text-center ink-3 transition group-open:rotate-90">▸</span>
        <div className="grid min-w-0 gap-2 sm:grid-cols-[13rem_minmax(0,1fr)] sm:items-center sm:gap-4">
          <div className="flex min-w-0 items-center gap-2">
            <span className="t-body truncate font-semibold ink-1">{industry}</span>
            {isReserve
              ? <span className="t-micro shrink-0 rounded-full bg-black/[0.05] px-1.5 py-0.5 ink-3 dark:bg-white/[0.08]">储备</span>
              : <span className="t-micro shrink-0 rounded-full bg-[#dbe9fa] px-1.5 py-0.5 text-[#2f6299] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]">{userCount} 人在找</span>}
          </div>
          {/* 进度条 = 30 家里有几家真的有可投岗位。条越短越该修。 */}
          <div className="flex items-center gap-2.5">
            <span className="relative h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-black/[0.06] dark:bg-white/[0.08]">
              <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 rounded-full", HEALTH_STATUS_META[tone].fill)} style={{ width: ratio == null ? "0%" : `${Math.max(2, ratio * 100)}%` }} />
            </span>
            <span className="t-caption shrink-0 tabular-nums ink-2">
              {healthy == null ? "读取失败" : `${healthy}/${total} 家有岗`}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="t-caption hidden tabular-nums ink-3 sm:inline">已接入 {withSource == null ? "—" : `${withSource}/${total}`}</span>
          <StatusBadge tone={tone} label={rows ? (gaps > 0 ? `${gaps} 家没岗` : blind > 0 ? `${blind} 家没查过` : "都有岗") : "读取失败"} />
        </div>
      </summary>
      <div className="border-t border-black/[0.06] px-1 pb-5 pt-4 sm:px-2 dark:border-white/[0.08]">
        <MustApplyIndustryBlock
          embedded
          rows={rows}
          fetchCoverage={fetchCoverage}
          healthBand={healthBand}
          scope={scope}
          industry={industry}
          userCount={userCount}
        />
      </div>
    </details>
  );
}

function MustApplySection({
  rowsByIndustry,
  fetchCoverageByIndustry,
  activeIndustries,
  userDistribution,
  scope,
}: {
  rowsByIndustry: MustApplyRowsByScope | null;
  fetchCoverageByIndustry: Record<MustApplyScope, Record<string, MustApplyFetchCoverage>> | null;
  activeIndustries: Record<MustApplyScope, string[]>;
  userDistribution: UserIndustryDistribution;
  scope: MustApplyScope;
}) {
  const active = activeIndustries[scope];
  // 排序：先「有用户在找的行业」，各自内部按严重程度（差的在上）。
  // 储备行业排在后面——没有用户在找它，修它不是当务之急，但也不该藏起来。
  const severity: Record<HealthBand, number> = { bad: 0, warn: 1, good: 2, empty: 3 };
  const ordered = [...MUST_APPLY_INDUSTRIES].sort((a, b) => {
    const aActive = active.includes(a) ? 0 : 1;
    const bActive = active.includes(b) ? 0 : 1;
    if (aActive !== bActive) return aActive - bActive;
    const aBand = severity[mustApplyIndustryBand(rowsByIndustry?.[scope]?.[a] || null)];
    const bBand = severity[mustApplyIndustryBand(rowsByIndustry?.[scope]?.[b] || null)];
    if (aBand !== bBand) return aBand - bBand;
    return a.localeCompare(b, "zh-CN");
  });

  const activeCount = active.length;
  const worstActive = ordered.find((industry) => active.includes(industry));

  return (
    <div className="grid gap-4">
      <section className="surface-soft p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="max-w-2xl">
            <h2 className="t-h2 ink-1">必投清单健康覆盖</h2>
            <p className="t-body-sm mt-1 leading-6 ink-2">
              每个行业挑 30 家目标用户最想投的头部公司，逐家核对「我们现在有没有它的可投岗位」。
              这是产品对用户的真实承诺，比库存总量重要得多。
            </p>
          </div>
          <StatusBadge tone="muted" label={`${activeCount} 个行业有人在找`} />
        </div>

        {/* 国内 / 海外切换：改造前两者堆在同一页，现在一次只看一边 */}
        <div className="mt-4 inline-flex rounded-full border border-black/[0.1] p-1 dark:border-white/[0.14]">
          {MUST_APPLY_SCOPES.map((s) => (
            <a
              key={s}
              href={`/admin/health?tab=supply${s === "domestic" ? "" : "&scope=" + s}`}
              aria-current={scope === s ? "page" : undefined}
              className={cn(
                "t-label rounded-full px-4 py-1.5 transition",
                scope === s
                  ? "bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                  : "ink-2 hover:bg-black/[0.05] dark:hover:bg-white/[0.07]",
              )}
            >
              {MUST_APPLY_SCOPE_LABEL[s]}必投
              <span className="ml-1.5 tabular-nums opacity-70">{userDistribution.scopeUsers[s]} 人</span>
            </a>
          ))}
        </div>
        {scope === "overseas" && userDistribution.scopeUsers.overseas === 0 && (
          <Callout tone="muted" className="mt-3">
            目前没有用户在找海外岗位。下面这份只是储备，不计入北极星，掉了也不拖红整体。
          </Callout>
        )}
        {worstActive && (
          <Callout tone={bandTone(mustApplyIndustryBand(rowsByIndustry?.[scope]?.[worstActive] || null))} className="mt-3">
            当前最该补的是 <span className="font-semibold">{worstActive}</span>。列表已按严重程度排好，从上往下修。
          </Callout>
        )}

        {/* 折叠列表：一行一个行业，点开看这个行业 30 家公司的逐家状态 */}
        <div className="mt-4 overflow-hidden rounded-2xl border border-black/[0.07] dark:border-white/[0.1]">
          {ordered.map((industry) => (
            <MustApplyIndustryRow
              key={`${scope}-${industry}`}
              scope={scope}
              industry={industry}
              rows={rowsByIndustry?.[scope]?.[industry] || null}
              fetchCoverage={fetchCoverageByIndustry?.[scope]?.[industry] || null}
              userCount={userDistribution.counts[scope][industry] || 0}
              isReserve={!active.includes(industry)}
            />
          ))}
        </div>
        <p className="t-caption mt-3 ink-3">
          「有岗」= 这家公司当前有至少 1 个能投的岗位（有正文、近期核验过）。
          「已接入」= 我们已经接上了它的官方招聘页，接上了不等于现在有岗在招。
        </p>
      </section>

      <section className="surface-soft p-5 sm:p-6">
        <h2 className="t-h2 ink-1">用户都在找哪些行业</h2>
        <p className="t-body-sm mt-1 ink-2">按用户填的求职行业统计，决定上面哪些行业算「有人在找」。</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {MUST_APPLY_SCOPES.map((s) => (
            <StatusBadge key={s} tone="muted" label={`${MUST_APPLY_SCOPE_LABEL[s]} ${userDistribution.scopeUsers[s]} 人`} />
          ))}
          <StatusBadge tone="muted" label={`还没填 ${userDistribution.unset} 人`} />
        </div>
      </section>
    </div>
  );
}

function ClickValiditySection({
  clickValidity,
  status,
  summary,
}: {
  clickValidity: ClickValidityMetrics | null;
  status: BandTone;
  summary: string;
}) {
  const clickBand = band(clickValidity?.probeValidityRate, HEALTH_THRESHOLDS.clickValidity, "higher");
  const clickTone = bandTone(clickBand);
  const sample = clickValidity ? clickValidity.alive + clickValidity.dead : 0;
  return (
    <section className="surface-soft p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold ink-1 ">岗位还在不在（系统自动查，不是用户点击统计）</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 ink-2 ">
            系统自动去打开看板上这些岗位的链接，看还打不打得开。目标是「能查的岗位里 ≥99% 还正常」；没有数据时显示“—”，不当作 0。
          </p>
        </div>
        <StatusBadge tone={status} />
      </div>
      <p className="mb-4 text-sm ink-2 ">{summary}</p>
      {!clickValidity ? (
        <ErrorPanel label="点击有效率" />
      ) : (
        <>
          <div className="grid gap-5 lg:grid-cols-[11rem_1fr] lg:items-center">
            <div className="flex justify-center lg:justify-start">
              <StatRing pct={clickValidity.probeValidityRate} tone={clickTone} size="section" target={0.99}>
                {clickValidity.probeValidityRate == null ? (
                  <>
                    <span className="text-lg font-semibold ink-3 ">—</span>
                    <span className="mt-1 text-[11px] ink-3 ">目标 99%</span>
                  </>
                ) : (
                  <>
                    <span className="inline-flex items-baseline gap-0.5 text-3xl font-semibold tabular-nums ink-1 ">
                      <AnimatedStat value={Math.round(clickValidity.probeValidityRate * 100)} />
                      <span className="text-sm">%</span>
                    </span>
                    <span className="mt-1 text-[11px] leading-4 ink-2 ">未发现失效</span>
                  </>
                )}
              </StatRing>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KpiCard
                value={formatRate(clickValidity.coverageRate)}
                tone={clickValidity.coverageRate == null ? "muted" : "success"}
                detail={`展示岗位 ${formatCount(clickValidity.totalOpens)}`}
                title="查过的比例"
              />
              <KpiCard
                title="查不了的占比"
                value={formatRate(clickValidity.unknownRate)}
                tone={clickValidity.unknownRate == null ? "muted" : clickValidity.unknownRate > 0 ? "warning" : "success"}
                detail={`一共查了 ${formatCount(clickValidity.livenessTotal)}`}
              />
              <KpiCard
                title="样本"
                value={formatCount(sample)}
                tone={sample > 0 ? "success" : "muted"}
                detail={`未发现失效 ${formatCount(clickValidity.alive)} · 已关闭 ${formatCount(clickValidity.dead)}`}
              />
              <KpiCard
                title="需要开浏览器才能抓的公司，抽查到的失效比例"
                value="待采集"
                tone="muted"
                detail="这类公司的抽查还没接上"
              />
            </div>
          </div>

          <p className="mt-3 text-xs leading-5 ink-3 ">
            目标 99%。「能查的」和「查不了的」分开报，不把查不了的岗位混进成功率里充数。
          </p>

          {clickValidity.byAdapter.length > 0 && (
            <details className="mt-5 rounded-2xl border border-black/[0.07] bg-white/35 dark:border-white/[0.1] dark:bg-white/[0.03]">
              <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold ink-1 [&::-webkit-details-marker]:hidden">
                按抓取方式分开看
              </summary>
              <div className="border-t border-black/[0.06] p-4 dark:border-white/[0.08]">
                <BarList ariaLabel="按抓取方式分别看：查过之后还在的比例" items={clickValidity.byAdapter.map((adapter) => ({
                  key: adapter.adapter,
                  label: adapter.adapter,
                  ratio: adapter.validityRate,
                  tone: bandTone(band(adapter.validityRate, HEALTH_THRESHOLDS.clickValidity, "higher")),
                  value: formatRate(adapter.validityRate),
                  valueDetail: `正常 ${formatCount(adapter.alive)} · 关闭 ${formatCount(adapter.dead)} · 探不动 ${formatCount(adapter.unknown)}`,
                }))} />
                <p className="mt-3 text-xs ink-3 ">这里的名字是抓取方式的内部代号，写出来是为了排查问题时能直接定位。</p>
              </div>
            </details>
          )}
        </>
      )}
    </section>
  );
}

function sourceSuccessTone(value: string): BandTone {
  const ratio = parsePercentRatio(value);
  if (ratio == null) return "muted";
  if (ratio >= 0.9) return "success";
  if (ratio >= 0.6) return "warning";
  return "danger";
}

function JobsLibrarySection({
  jobs,
  operations,
  crawlSources,
  todayRemoved,
  validActiveShareBand,
  thinShareBand,
  neverCheckedShareBand,
  showHealthSummary = true,
}: {
  jobs: JobsHealthSnapshot | null;
  operations: SupabaseHealthSnapshot | null;
  crawlSources: ReturnType<typeof normalizeCrawlSources>;
  todayRemoved: number | null;
  validActiveShareBand: HealthBand;
  thinShareBand: HealthBand;
  neverCheckedShareBand: HealthBand;
  showHealthSummary?: boolean;
}) {
  return (
    <>
      {!jobs && showHealthSummary ? (
        <ErrorPanel label="岗位库体检" />
      ) : jobs ? (
        <>
          <div className="grid gap-5 lg:grid-cols-[12rem_1fr] lg:items-center">
            <div className="flex justify-center lg:justify-start">
              <StatRing pct={share(jobs.validActive, jobs.activeTotal)} tone={bandTone(validActiveShareBand)} size="section">
                <span className="inline-flex items-baseline gap-0.5 text-3xl font-semibold tabular-nums ink-1 ">
                  <AnimatedStat value={jobs.validActive} />
                </span>
                <span className="mt-1 text-[11px] leading-4 ink-2 ">
                  能投岗位 / 在招 {formatCount(jobs.activeTotal)}
                </span>
              </StatRing>
            </div>
            <div className="space-y-4">
              <BarList ariaLabel="岗位库存构成" items={[
                { key: "valid", label: "能投岗位", ratio: share(jobs.validActive, jobs.activeTotal), tone: "success", value: formatCount(jobs.validActive), valueDetail: `在招 ${formatCount(jobs.activeTotal)} 中可投` },
                { key: "thin", label: "空壳岗", ratio: share(jobs.thinActive, jobs.activeTotal), tone: "warning", value: formatCount(jobs.thinActive), valueDetail: "有链接但没有岗位正文" },
                { key: "unchecked", label: "待核查", ratio: share(jobs.neverChecked, jobs.activeTotal), tone: bandTone(neverCheckedShareBand), value: displayEmptyRate(formatPercent(jobs.neverChecked, jobs.activeTotal)), valueDetail: "与在招岗位可能重叠" },
              ]} />
            </div>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard title="今日新进" value={formatCount(jobs.todayNew)} tone="success" detail="今天新入库的岗位" className="min-h-0" />
            <KpiCard title={translateOperationalTerm("today_removed")} value={formatCount(todayRemoved)} tone={todayRemoved == null ? "muted" : todayRemoved > 0 ? "warning" : "success"} detail="今天新判定失效的岗位" className="min-h-0" />
            <KpiCard title={translateOperationalTerm("expired")} value={formatCount(jobs.expired)} tone="muted" detail="逐个查过、确认岗位已经撤下，永久删除" className="min-h-0" />
            <KpiCard title={translateOperationalTerm("removed")} value={formatCount(jobs.removed)} tone="muted" detail="疑似下线，后续可能恢复" className="min-h-0" />
          </div>

          <p className="mt-3 text-xs leading-5 ink-3 ">
            今日下架（今天新判定失效） · 已确认撤岗（探活确认永久移除） · 暂时下线（疑似下线，可能恢复） · 空壳岗（有链接但没岗位正文，质量差） · 待核查（还没探活验证）
          </p>
        </>
      ) : null}

      <details className="mt-5 rounded-2xl border border-black/[0.07] bg-white/35 dark:border-white/[0.1] dark:bg-white/[0.03]">
        <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold ink-1 [&::-webkit-details-marker]:hidden">
          招聘源近 7 天表现
        </summary>
        <div className="border-t border-black/[0.06] p-4 dark:border-white/[0.08]">
          <p className="mb-3 text-xs leading-5 ink-3 ">
            成功率按完成、部分完成、失败三类运行计算；没运行过的招聘源显示“—”。
          </p>
          {!operations ? (
            <ErrorPanel label="招聘源统计" />
          ) : crawlSources.length === 0 ? (
            <p className="text-sm ink-3 ">暂无启用的招聘源。</p>
          ) : (
            <BarList className="max-h-[34rem] overflow-auto" ariaLabel="招聘源近七天表现" items={crawlSources.map((source) => ({
              key: source.sourceId,
              label: source.company,
              caption: `${source.adapterName} · 运行 ${formatCount(source.runs)} 次 · 部分完成 ${displayEmptyRate(source.partialRate)}`,
              ratio: parsePercentRatio(source.successRate),
              tone: sourceSuccessTone(source.successRate),
              value: displayEmptyRate(source.successRate),
              valueDetail: `失败 ${formatCount(source.failed)} / 跳过 ${formatCount(source.skipped)}`,
            }))} />
          )}
        </div>
      </details>
    </>
  );
}

function DailyReportsSection({
  operations,
  reports,
  extraOpsUnavailable,
}: {
  operations: SupabaseHealthSnapshot | null;
  reports: DailyReport[];
  extraOpsUnavailable: boolean;
}) {
  return (
    <>
      {!operations ? (
        <ErrorPanel label="每日战报" />
      ) : (
        <>
          {/* 台账读失败时要说读失败，不能让缺口漏斗 / 校招供给显示成「今天没记录」——那是另一种说谎。 */}
          {extraOpsUnavailable && (
            <Callout tone="warning" className="mb-3">「补公司流水线」和「校招供给」的运行记录这次没读到，这两张卡的数字暂时不可信——但不代表它们今天没跑。</Callout>
          )}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {reports.map((report) => (
              <KpiCard
                key={report.key}
                title={report.title}
                value={report.produced == null ? "—" : formatCount(report.produced)}
                tone={report.producedTone}
                status={
                  <span className="flex flex-wrap items-center gap-1.5">
                    <StatusBadge tone={report.producedTone} label={outputSignalText(report)} />
                    <StatusBadge tone={report.runTone} label={report.runs <= 0 ? "没运行" : `跑 ${formatCount(report.runs)} · 挂 ${formatCount(report.failed)}`} />
                  </span>
                }
                detail={report.producedLabel}
                footnote={`${runSignalText(report)} · 上次运行 ${formatRunTime(report.lastRunAt)}`}
                className="min-h-0 p-3"
              />
            ))}
          </div>

          <details className="mt-5 rounded-2xl border border-black/[0.07] bg-white/35 dark:border-white/[0.1] dark:bg-white/[0.03]">
            <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold ink-1 [&::-webkit-details-marker]:hidden">
              展开明细
            </summary>
            <div className="grid gap-3 border-t border-black/[0.06] p-4 lg:grid-cols-2 dark:border-white/[0.08]">
              {reports.map((report) => (
                <OperationCard key={report.key} report={report} />
              ))}
            </div>
          </details>
        </>
      )}
    </>
  );
}

function SprintCards({ users }: { users: NonNullable<SupabaseHealthSnapshot["today"]>["users"] | null }) {
  const pending = [
    ["收到有效机会", "行为埋点上线后可见"],
    ["点击官网", "行为埋点上线后可见"],
    ["7日回访", "埋点上线后开始积累"],
  ];
  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold ink-1 ">两周冲刺 · 用户闭环</h2>
        <StatusBadge tone="muted" label="埋点准备中" />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard title="标已投" value={users ? formatCount(users.applied_total) : "—"} tone="muted" detail="全部用户累计" href="/admin/health?tab=users" className="min-h-0" />
        {pending.map(([label, detail]) => (
          <KpiCard key={label} title={label} value="待采集" tone="muted" detail={detail} className="min-h-0" />
        ))}
      </div>
    </section>
  );
}

function DataNotes({ refreshedAt }: { refreshedAt: string }) {
  return (
    <div className="text-[11px] leading-5 ink-3 ">
      <p>页面打开时间：<span className="tabular-nums">{refreshedAt}</span> 北京时间</p>
      {/* 缓存了就必须说出来。写「数据更新时间 = 现在」而实际是 3 分钟前算的，是另一种说谎。 */}
      <p className="mt-0.5">数据每 {Math.round(ADMIN_DATA_TTL_SECONDS / 60)} 分钟重算一次，所以可能比此刻晚几分钟——运营看板看的是「今天跑得怎么样」，不追秒级实时。</p>
      <details className="mt-2">
        <summary className="cursor-pointer">这些数字怎么来的</summary>
        <ul className="mt-2 list-disc space-y-1 pl-4">
          <li>未接入显示「待采集」，真实 0 保持 0，读取失败显示「—」。</li>
          <li>这是系统自动去查「岗位链接还打不打得开」，不是用户真实点击的统计。</li>
          <li>官网不写总数的公司算不出抓全比例，不计入平均，也不按 0% 算。</li>
        </ul>
      </details>
    </div>
  );
}

function OverviewTab({
  health,
  heroStatus,
  heroDataMissing,
  jobs,
  users,
  supplyStatus,
  systemStatus,
  worst,
  rowsByScope,
  reports,
  refreshedAt,
  disputesOpen,
  dailySeries,
  dailySeriesUnavailable,
}: {
  health: ReturnType<typeof evaluateCombinedHealth>;
  heroStatus: BandTone;
  heroDataMissing: boolean;
  jobs: JobsHealthSnapshot | null;
  users: NonNullable<SupabaseHealthSnapshot["today"]>["users"] | null;
  supplyStatus: BandTone;
  systemStatus: BandTone;
  worst: { scope: MustApplyScope; industry: string; healthy: number | null; total: number };
  rowsByScope: MustApplyRowsByScope | null;
  reports: DailyReport[];
  refreshedAt: string;
  disputesOpen: number | undefined;
  dailySeries: HealthDailySeries | null;
  dailySeriesUnavailable: boolean;
}) {
  const healthyReports = reports.filter((report) => report.verdict === "healthy");
  const brokenReports = reports.filter((report) => report.verdict === "broken");
  const attentionReports = reports.filter((report) => report.verdict === "attention");
  const idleReports = reports.filter((report) => report.verdict === "idle");
  const systemDetail = brokenReports.length
    ? `${brokenReports.length} 个出问题：${brokenReports.map((report) => report.title).join("、")}`
    : attentionReports.length
      ? `${attentionReports.length} 个有失败：${attentionReports.map((report) => report.title).join("、")}`
      : idleReports.length
        ? `${idleReports.length} 个今天还没记录`
        : "全部模块今天都有产出";
  const cards: Array<[string, string, BandTone, string, string, string]> = [
    ["岗位库", "jobs", jobs ? sectionStatusFromBand(band(share(jobs.validActive, jobs.activeTotal), HEALTH_THRESHOLDS.validActiveShare, "higher")) : "muted", jobs ? formatCount(jobs.activeTotal) : "—", jobs ? "有效率 " + formatPercent(jobs.validActive, jobs.activeTotal) + " · 空壳 " + formatCount(jobs.thinActive) : "数据暂不可用", "在招、有效率与空壳岗均来自岗位库快照"],
    ["必投供给", "supply", supplyStatus, rowsByScope ? `${formatCount(worst.healthy)}/${formatCount(worst.total)}` : "—", "最需处理：" + MUST_APPLY_SCOPE_LABEL[worst.scope] + "·" + worst.industry, "按当前用户行业的必投公司逐家计算"],
    ["用户行为", "users", users ? "success" : "muted", users ? formatCount(users.total_users) : "—", users ? "累计投递 " + formatCount(users.applied_total) + " 次" : "数据暂不可用", "今日汇总，不含未接入的行为埋点"],
    // 口径从「今天跑没跑」换成「今天产出正不正常」，与热力图、模块卡走同一个 moduleVerdict。
    ["后台产出", "system", systemStatus, String(healthyReports.length) + "/" + reports.length, systemDetail, "今日产出正常的后台模块数 / 全部模块数"],
  ];
  const northStarItems = northStarTrackerItems(dailySeries);
  const snapshotDays = northStarItems.filter((item) => item.tone !== "muted").length;
  const firstSnapshot = dailySeries?.days?.find((day) => day.north_star)?.day;
  return (
    <div className="grid gap-5">
      <section className="surface p-5 sm:p-7">
        <p className="text-sm font-medium text-[#625c51] dark:text-[#c5bbaa]">北极星 · 必投健康覆盖</p>
        <div className="mt-4 flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="max-w-2xl text-lg font-semibold leading-7 ink-1 ">{rowsByScope ? `${MUST_APPLY_SCOPE_LABEL[worst.scope]}·${worst.industry} 是现在最需要补齐的行业。` : "必投清单数据暂不可用，不能判断今天该补哪一处。"}</p>
            <p className="mt-4 inline-flex items-baseline gap-2 tabular-nums ink-1 "><span className="text-[4rem] font-semibold leading-none tracking-[-0.05em] sm:text-[4.75rem]">{rowsByScope ? formatCount(worst.healthy) : "—"}</span><span className="text-lg text-[#625c51] dark:text-[#c5bbaa]">/ {formatCount(worst.total)} 家有健康岗</span></p>
          </div>
          <div className="text-sm ink-3"><StatusBadge tone={rowsByScope ? supplyStatus : "muted"} /><p className="mt-3">本页读取于 <span className="tabular-nums">{refreshedAt}</span> 北京时间</p></div>
        </div>
      </section>
      <div className="border-t border-black/[0.10] dark:border-white/[0.12]" />
      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{cards.map(([name, key, status, number, detail, footnote]) => <KpiCard key={key} title={name} value={number} tone={status} detail={detail} footnote={footnote} href={`/admin/health?tab=${key}`} weight="strong" />)}</section>
      <Callout tone={heroStatus} className="surface">{heroDataMissing ? "今日结论暂不可用，请先查看系统运行。" : health.actions.length ? `今天有 ${health.actions.length} 项需要处理，先做：${health.actions[0]}` : "今日没有系统侧红线，可以按计划推进两周冲刺。"}</Callout>
      <section className="surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h2 className="font-semibold ink-1 ">今日行动</h2><p className="mt-1 text-xs ink-3">只列今天可以直接处理的事项。</p></div>
          <StatusBadge tone={heroStatus} />
        </div>
        {health.actions.length || (disputesOpen || 0) > 0 ? <div className="mt-3 space-y-2">{health.actions.slice(0, 3).map((action, index) => <a key={action} href={actionAnchor(action)} className="flex items-start gap-2 rounded-xl px-2 py-1.5 text-sm leading-5 ink-2 hover:bg-white/55 dark:hover:bg-white/[0.06]"><StatusDot tone={health.level === "critical" && index === 0 ? "danger" : "warning"} /><span>{action}</span></a>)}{health.actions.length > 3 && <p className="px-2 text-xs ink-3 ">另有 {health.actions.length - 3} 项，见下方各板块</p>}{(disputesOpen || 0) > 0 && <a href="/admin/insights" className="flex items-start gap-2 rounded-xl px-2 py-1.5 text-sm font-medium leading-5 text-[#8f6225] hover:bg-[#fbecd7] dark:text-[#e0b15a] dark:hover:bg-[#825d28]/20"><StatusDot tone="warning" /><span>待处理申诉：{formatCount(disputesOpen)} 条</span></a>}</div> : <p className="mt-3 flex items-center gap-2 text-sm ink-2 "><StatusDot tone="success" />今日无系统侧紧急行动，继续推进两周冲刺。</p>}
      </section>
      <AccumulatingMetric title="北极星趋势" description={dailySeriesUnavailable ? "趋势序列暂不可用，今天不展示走势。" : firstSnapshot ? `趋势数据从 ${firstSnapshot} 开始积累，目前已有 ${snapshotDays} 天；样本不足时不展示涨跌或折线。` : "每日写入已接入，首条快照将在每日抓取完成后出现。"} items={northStarItems} />
      <SprintCards users={users} />
      <DataNotes refreshedAt={refreshedAt} />
    </div>
  );
}

function JobsTab({ jobs, clickValidity, clickStatus, coverage, operations, todayRemoved, validBand, checkedBand, dailySeries, dailySeriesUnavailable }: { jobs: JobsHealthSnapshot | null; clickValidity: ClickValidityMetrics | null; clickStatus: BandTone; coverage: CoverageSnapshot | null; operations: SupabaseHealthSnapshot | null; todayRemoved: number | null; validBand: HealthBand; checkedBand: HealthBand; dailySeries: HealthDailySeries | null; dailySeriesUnavailable: boolean }) {
  return <div className="grid gap-5">
    {jobs ? <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <KpiCard title="在招总量" value={formatCount(jobs.activeTotal)} tone="success" detail="岗位库当前仍在招聘的岗位" />
      <KpiCard title="今日新进" value={formatCount(jobs.todayNew)} tone="success" detail="今天新入库的岗位" />
      <KpiCard title="今日下架" value={formatCount(todayRemoved)} tone={todayRemoved == null ? "muted" : todayRemoved > 0 ? "warning" : "success"} detail="今天新判定失效的岗位" />
      <KpiCard title="空壳岗" value={formatCount(jobs.thinActive)} tone="warning" detail="有链接，但没有岗位正文" />
      <KpiCard title="还没查过" value={formatCount(jobs.neverChecked)} tone={bandTone(checkedBand)} detail="还没查过这些岗位现在还在不在" />
    </section> : <ErrorPanel label="岗位库体检" />}
    {jobs && <section className="surface-soft p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold ink-1 ">库存结构</h2><p className="mt-1 text-xs ink-3">同一个岗位可能既算「在招」、又算「还没查过」，别把这两个数相加。</p></div><StatRing pct={share(jobs.validActive, jobs.activeTotal)} tone={bandTone(validBand)} size="section"><span className="text-lg font-semibold tabular-nums">{formatPercent(jobs.validActive, jobs.activeTotal)}</span><span className="text-[10px] ink-3">能投有效率</span></StatRing></div><BarList className="mt-4" ariaLabel="岗位库存构成" items={[{ key: "valid", label: "能投岗位", ratio: share(jobs.validActive, jobs.activeTotal), tone: "success", value: formatCount(jobs.validActive) }, { key: "thin", label: "空壳岗", ratio: share(jobs.thinActive, jobs.activeTotal), tone: "warning", value: formatCount(jobs.thinActive) }, { key: "unchecked", label: "待核查", ratio: share(jobs.neverChecked, jobs.activeTotal), tone: bandTone(checkedBand), value: formatCount(jobs.neverChecked) }]} /><p className="mt-3 text-[10px] ink-3 ">按今天读到的岗位库现状计算。同一个岗位可能既算「在招」、又算「还没查过」，别把这两个数相加。</p></section>}
    <section className="surface-soft p-5"><h2 className="font-semibold ink-1 ">抓取运行近 30 天</h2><p className="mt-1 text-xs ink-3">每格一天。一天全挂了显示「得处理」，有挂的或只跑完一半显示「要注意」。与下面每张模块卡用的是同一套标准。</p>{dailySeriesUnavailable ? <div className="mt-4"><ErrorPanel label="每天的抓取记录" /></div> : <Tracker className="mt-4" items={processTrackerItems(dailySeries, "crawl")} ariaLabel="抓取运行近 30 天" />}</section>
    <ClickValiditySection clickValidity={clickValidity} status={clickStatus} summary="系统自动查看板上这些岗位还在不在，不是用户真实点击的统计。" />
    <section className="surface-soft p-5"><h2 className="t-h2 mb-4 ink-1">抓得全不全</h2><CoverageSection snapshot={coverage} /><p className="mt-4 text-[10px] ink-3 ">只算「官网明写共有几个岗」的公司。官网不写的算不出来，不按 0% 处理。</p></section>
    <CrawlSourceBreakdown operations={operations} todayRemoved={todayRemoved} validBand={validBand} checkedBand={checkedBand} />
  </div>;
}

// 分源状态（默认折叠）。只渲染最该看的前 CRAWL_SOURCE_DISPLAY_LIMIT 个。
// 背景：这块虽然折叠着，服务端仍会把它整份塞进首屏数据——线上实测让本页膨胀到 2.6MB，
// 其中 1.47MB 是它，而用户多数时候根本不会点开。截断后诚实说明「一共多少个」，
// 不做那种「悄悄少几行、页面上却像是全部」的事。
function CrawlSourceBreakdown({
  operations,
  todayRemoved,
  validBand,
  checkedBand,
}: {
  operations: SupabaseHealthSnapshot | null;
  todayRemoved: number | null;
  validBand: HealthBand;
  checkedBand: HealthBand;
}) {
  const all = operations?.crawl_sources || [];
  const shown = normalizeCrawlSources(all);
  const omitted = Math.max(0, all.length - shown.length);
  return (
    <details className="surface-soft p-5">
      <summary className="t-h2 cursor-pointer ink-1">分源状态</summary>
      <div className="mt-5">
        <JobsLibrarySection jobs={null} operations={operations} crawlSources={shown} todayRemoved={todayRemoved} validActiveShareBand={validBand} thinShareBand="empty" neverCheckedShareBand={checkedBand} showHealthSummary={false} />
        {omitted > 0 && (
          <p className="t-caption mt-3 ink-3">
            只列了最需要关注的前 {shown.length} 个（一共 {all.length} 个）。排序是「失败最多的排最前」，
            所以没列出来的都是表现更好的。
          </p>
        )}
      </div>
    </details>
  );
}

function MustApplyGapLedger({
  summary,
  ledger,
}: {
  summary: MustApplyGapSummary | null;
  ledger: { realExpansion: number | null; definitionChange: number } | null;
}) {
  return (
    <section className="surface-soft p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">补公司流水线 · 运行记录</h2>
          <p className="mt-1 text-sm ink-2 ">国内清单版本 {MUST_APPLY_VERSION}；「真的新接入了公司」和「统计规则变了」分开记，不混为一谈。</p>
        </div>
        <StatusBadge tone="muted" label={`清单版本 ${MUST_APPLY_VERSION}`} />
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <KpiCard title="这一轮真的新接入" value={ledger?.realExpansion == null ? "—" : `+${ledger.realExpansion}`} tone="success" detail="取国内流水线最近有记录的那一天，只算验收通过、最终留下来的新公司" className="min-h-0" />
        <KpiCard title="统计规则变动" value={ledger ? `${ledger.definitionChange >= 0 ? "+" : ""}${ledger.definitionChange}` : "—"} tone="muted" detail="只是改了统计规则后多算进来的（比如通过母公司招聘页覆盖到），不能冒充成新接入" className="min-h-0" />
      </div>
      {!summary ? <div className="mt-4"><ErrorPanel label="补公司流水线 · 运行记录" /></div> : (
        <div className="mt-5 grid gap-4 lg:grid-cols-3">
          <div>
            <h3 className="text-sm font-semibold">国内各状态</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {Object.entries(summary.stateCounts).map(([state, count]) => (
                <StatusBadge key={state} tone="muted" label={`${translateOperationalTerm(state)} ${formatCount(count)}`} />
              ))}
            </div>
          </div>
          <div>
            <h3 className="text-sm font-semibold">最近失败原因 Top 5</h3>
            <ul className="mt-2 space-y-1.5 text-xs ink-2 ">
              {summary.recentFailures.map((failure) => <li key={`${failure.company}-${failure.at}`}>{failure.company}：{failure.reason}</li>)}
              {!summary.recentFailures.length && <li>暂无失败</li>}
            </ul>
          </div>
          <div>
            <h3 className="text-sm font-semibold">需要人工确认的公司</h3>
            <p className="mt-2 text-xs leading-5 ink-2 ">
              {summary.manualReviewCompanies.join("、") || "暂无"}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}

function MustApplyGovernanceList({ items }: { items: MustApplyGovernanceItem[] | null }) {
  return <section className="surface-soft p-5 sm:p-6"><div><h2 className="text-xl font-semibold">必投清单待治理</h2><p className="mt-1 text-sm ink-2 ">只列出需要你人工拿主意的公司，不会自动改动必投清单。</p></div>{!items ? <div className="mt-4"><ErrorPanel label="必投清单待治理" /></div> : !items.length ? <p className="mt-4 text-sm ink-2 ">当前没有待治理公司。</p> : <div className="mt-4 max-h-[34rem] overflow-auto rounded-2xl border border-black/[0.07] dark:border-white/[0.1]"><table className="w-full min-w-[780px] text-left text-sm"><thead className="sticky top-0 z-10 bg-[#f4efe6] text-xs ink-3 dark:bg-[#1c1813] "><tr><th className="px-4 py-3 font-medium">公司</th><th className="px-4 py-3 font-medium">所属行业</th><th className="px-4 py-3 font-medium">卡在哪</th><th className="px-4 py-3 text-right font-medium">尝试次数</th><th className="px-4 py-3 font-medium">最后一次</th><th className="px-4 py-3 font-medium">建议动作</th></tr></thead><tbody>{items.map((item) => <tr key={item.company} className="border-t border-black/[0.05] ink-2 dark:border-white/[0.08] "><td className="px-4 py-3 font-medium">{item.company}</td><td className="px-4 py-3 text-xs">{item.industries.join("、") || "未标注"}</td><td className="max-w-xs px-4 py-3 text-xs leading-5">{item.blocker}</td><td className="px-4 py-3 text-right tabular-nums">{item.attempts}</td><td className="px-4 py-3 text-xs">{formatRunTime(item.lastAttemptAt)}</td><td className="px-4 py-3 text-xs font-medium">{item.suggestedAction}</td></tr>)}</tbody></table></div>}</section>;
}

function SupplyTab({ rowsByScope, fetchByIndustry, activeIndustries, userDistribution, worst, gapSummary, governanceItems, ledger, mustApplyScope }: { rowsByScope: MustApplyRowsByScope | null; fetchByIndustry: Record<MustApplyScope, Record<string, MustApplyFetchCoverage>> | null; activeIndustries: Record<MustApplyScope, string[]>; userDistribution: UserIndustryDistribution; worst: { scope: MustApplyScope; industry: string; healthy: number | null; total: number; zeroHealthyCompanies: string[] }; gapSummary: MustApplyGapSummary | null; governanceItems: MustApplyGovernanceItem[] | null; ledger: { realExpansion: number | null; definitionChange: number } | null; mustApplyScope: MustApplyScope }) {
  const tone = bandTone(mustApplyIndustryBand(rowsByScope?.[worst.scope]?.[worst.industry] || null));
  return <div className="grid gap-5">
    <section className="surface p-5 sm:p-7"><div className="grid gap-5 lg:grid-cols-[auto_1fr] lg:items-center"><div className="flex justify-center"><StatRing pct={rowsByScope ? share(worst.healthy, worst.total) : null} tone={tone} size="northstar" target={28 / 30}><span className="text-3xl font-semibold tabular-nums">{rowsByScope ? `${formatCount(worst.healthy)}/${formatCount(worst.total)}` : "—"}</span><span className="mt-1 text-[10px] ink-3">家有健康岗</span></StatRing></div><div><p className="text-sm font-medium text-[#625c51] dark:text-[#c5bbaa]">北极星 · 必投健康覆盖</p><h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] ink-1 ">{rowsByScope ? `${MUST_APPLY_SCOPE_LABEL[worst.scope]}·${worst.industry} 现在最需要补齐。` : "必投清单数据暂不可用，不能判断今天该补哪一处。"}</h1><p className="mt-3 max-w-2xl text-sm leading-6 ink-3">先保证目标用户最常投的那些公司有岗可投，再去管「怎么接进来的」和运行记录。</p><div className="mt-4"><StatusBadge tone={rowsByScope ? tone : "muted"} /></div></div></div></section>
    <section className="grid gap-3 md:grid-cols-2"><KpiCard title="最差行业" value={`${MUST_APPLY_SCOPE_LABEL[worst.scope]}·${worst.industry}`} tone={rowsByScope ? tone : "muted"} detail={rowsByScope ? `${formatCount(worst.healthy)}/${formatCount(worst.total)} 家有健康岗` : "当前无法读取必投覆盖"} footnote="按当前有求职用户的行业计算" /><KpiCard title="零健康岗公司" value={rowsByScope ? formatCount(worst.zeroHealthyCompanies.length) : "—"} tone={worst.zeroHealthyCompanies.length > 0 ? "danger" : rowsByScope ? "success" : "muted"} detail={rowsByScope ? (worst.zeroHealthyCompanies.slice(0, 3).join("、") || "真实 0 家缺口") : "读取失败时不把它当作 0"} footnote="只列当前最差行业中的公司" /></section>
    <MustApplySection rowsByIndustry={rowsByScope} fetchCoverageByIndustry={fetchByIndustry} activeIndustries={activeIndustries} userDistribution={userDistribution} scope={mustApplyScope} />
    <section className="grid gap-5 border-t border-black/[0.10] pt-5 dark:border-white/[0.12]"><Callout tone={worst.zeroHealthyCompanies.length > 0 ? "warning" : "success"}>{rowsByScope ? (worst.zeroHealthyCompanies.length > 0 ? `优先处理：${worst.zeroHealthyCompanies.slice(0, 10).join("、")}${worst.zeroHealthyCompanies.length > 10 ? ` 等 ${worst.zeroHealthyCompanies.length} 家` : ""}。` : "当前最差行业没有零健康岗公司。") : "必投清单读取失败，暂不生成缺口结论。"}</Callout><MustApplyGapLedger summary={gapSummary} ledger={ledger} /><MustApplyGovernanceList items={governanceItems} /></section>
  </div>;
}

// 「用户行为」模块。真正的内容在 components/admin/UserBehaviorReport，
// 这里只负责把「今日新增 / 简历解析 / 两周冲刺」这几个原有小指标接在报告后面——
// 它们与四问报告不同源（走 admin_health_snapshot），分开摆才不会让人以为是同一套口径。
function UserTab({
  analytics,
  includeStaff,
  users,
  resume,
}: {
  analytics: UserAnalytics | null;
  includeStaff: boolean;
  users: NonNullable<SupabaseHealthSnapshot["today"]>["users"] | null;
  resume: NonNullable<SupabaseHealthSnapshot["today"]>["resume"] | null;
}) {
  return (
    <div className="grid gap-5">
      <UserBehaviorReport analytics={analytics} includeStaff={includeStaff} />
      <section className="surface-soft p-5 sm:p-6">
        <h2 className="t-h2 ink-1">今天的动静</h2>
        <p className="t-body-sm mt-1 ink-2">这几个数看「今天」，上面的四问报告看「最近 30 天」，别把两边的数字对着减。</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard title="今天新注册" value={users ? formatCount(users.today_users) : "—"} tone="muted" detail="今天完成注册的人数" />
          <KpiCard title="收藏（累计 + 今天）" value={users ? `${formatCount(users.saved_total)} + ${formatCount(users.saved_today)}` : "—"} tone="muted" detail="用户点「值得投」的次数" />
          <KpiCard title="标记投递（累计 + 今天）" value={users ? `${formatCount(users.applied_total)} + ${formatCount(users.applied_today)}` : "—"} tone="muted" detail="用户自己标记为已投递的次数" />
          <KpiCard title="简历解析（今天）" value={resume ? `${formatCount(resume.succeeded)}/${formatCount(resume.started)}` : "—"} tone="muted" detail="解析成功 / 发起次数" />
        </div>
      </section>
      {users && <SprintCards users={users} />}
    </div>
  );
}

// 顶栏只放天天要看的五个模块（创始人定的）。洞察管理 / 招聘源管理是偶尔才进一次的
// 维护页，放在「系统运行」底部——不占顶栏，也不至于让站内彻底没有入口、只能手打网址。
function MaintenanceLinks() {
  return (
    <section className="surface-soft p-5">
      <h2 className="t-h3 ink-1">维护入口</h2>
      <p className="t-caption mt-1 ink-3">不常用，所以没放在顶栏。</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <a href="/sources" className="t-label inline-flex items-center rounded-full border border-black/[0.12] px-3.5 py-1.5 ink-2 transition hover:bg-black/[0.04] dark:border-white/[0.15] dark:hover:bg-white/[0.06]">招聘源管理</a>
        <a href="/admin/insights" className="t-label inline-flex items-center rounded-full border border-black/[0.12] px-3.5 py-1.5 ink-2 transition hover:bg-black/[0.04] dark:border-white/[0.15] dark:hover:bg-white/[0.06]">洞察管理</a>
      </div>
    </section>
  );
}

function SystemTab({ operations, reports, refreshedAt, dailySeries, dailySeriesUnavailable, extraOpsUnavailable }: { operations: SupabaseHealthSnapshot | null; reports: DailyReport[]; refreshedAt: string; dailySeries: HealthDailySeries | null; dailySeriesUnavailable: boolean; extraOpsUnavailable: boolean }) {
  return <div className="grid gap-5"><section className="surface-soft p-5"><h2 className="font-semibold ink-1 ">后台任务近 30 天</h2><p className="mt-1 text-xs ink-3">每格一天。一天全挂了显示「得处理」，有挂的或只跑完一半显示「要注意」，没有记录的单独标出来不伪装成 0。与下面每张模块卡同一套标准。</p>{dailySeriesUnavailable ? <div className="mt-4"><ErrorPanel label="每天的后台任务记录" /></div> : <Tracker className="mt-4" items={processTrackerItems(dailySeries, "ops")} ariaLabel="后台任务近 30 天" />}<p className="mt-3 text-[10px] ink-3 ">按每天的后台运行记录汇总。没有记录就显示「没有记录」，不会伪装成成功或 0；跑完了但一条产出都没有，一律不算正常。</p></section><section className="surface-soft p-5"><DailyReportsSection operations={operations} reports={reports} extraOpsUnavailable={extraOpsUnavailable} /></section><DataNotes refreshedAt={refreshedAt} /><MaintenanceLinks /><p className="text-xs ink-3 ">这一页只有管理员能打开。数据分别来自两个库，一边读不出来时另一边照常显示。</p></div>;
}

export default async function AdminHealthPage({ searchParams }: { searchParams: Promise<{ tab?: string | string[]; staff?: string | string[]; scope?: string | string[] }> }) {
  if (!(await isAdmin())) redirect("/");
  const query = await searchParams;
  const rawTab = typeof query.tab === "string" ? query.tab : "";
  const tab = rawTab === "jobs" || rawTab === "supply" || rawTab === "users" || rawTab === "system" ? rawTab : "overview";
  // ?staff=1 才把管理员与测试号算进用户行为统计。默认排除——不排除会被自己人的日常使用刷歪。
  const includeStaff = (typeof query.staff === "string" ? query.staff : "") === "1";
  // 必投清单的国内/海外切换。默认国内——目前海外没有用户在找，进来先看该看的那份。
  const mustApplyScope: MustApplyScope = (typeof query.scope === "string" ? query.scope : "") === "overseas" ? "overseas" : "domestic";
  const overview = tab === "overview";
  const [jobsResult, supabaseResult, clickResult, mustApplyResult, coverageResult, fetchResult, industriesResult, gapResult, dailySeriesResult, extraOpsResult, analyticsResult] = await Promise.allSettled([overview || tab === "jobs" ? getJobsHealthSnapshot() : Promise.resolve(null), overview || tab === "jobs" || tab === "users" || tab === "system" ? loadSupabaseHealth() : Promise.resolve(null), overview || tab === "jobs" ? loadClickValidity() : Promise.resolve(null), overview || tab === "supply" ? loadMustApplyCoverage() : Promise.resolve(null), overview || tab === "jobs" || tab === "supply" ? loadCoverageSnapshot() : Promise.resolve(null), tab === "supply" ? Promise.all(MUST_APPLY_SCOPES.map(async (scope) => [scope, await getMustApplyFetchCoverage(createServiceClient(), scope)] as const)) : Promise.resolve(null), overview || tab === "supply" ? loadUserIndustryDistribution() : Promise.resolve(null), tab === "supply" ? loadMustApplyGapAdminData() : Promise.resolve(null), overview || tab === "jobs" || tab === "system" ? loadHealthDailySeries() : Promise.resolve(null), overview || tab === "system" ? loadExtraOpsRuns() : Promise.resolve(null), tab === "users" ? getUserAnalytics(createServiceClient(), { days: 30, includeStaff }) : Promise.resolve(null)]);
  const jobs = jobsResult.status === "fulfilled" ? jobsResult.value : null;
  const operations = supabaseResult.status === "fulfilled" ? supabaseResult.value : null;
  const clickValidity = clickResult.status === "fulfilled" ? clickResult.value : null;
  const rowsByScope = mustApplyResult.status === "fulfilled" ? mustApplyResult.value : null;
  const gapData = gapResult.status === "fulfilled" ? gapResult.value : null;
  const currentDomesticCompanies = new Set(mustApplyUnion("domestic").map((row) => row.name));
  const currentGapAttempts = gapData
    ? gapData.attempts.filter(
      (row) => currentDomesticCompanies.has(String(row.company || ""))
        && row.evidence?.list_version === MUST_APPLY_VERSION,
    )
    : null;
  const gapSummary = currentGapAttempts ? summarizeMustApplyGapAttempts(currentGapAttempts) : null;
  const governanceItems = currentGapAttempts ? buildMustApplyGovernanceItems(currentGapAttempts) : null;
  const domesticCoverageRows = rowsByScope
    ? Array.from(new Map(
      Object.values(rowsByScope.domestic)
        .flat()
        .map((row) => [row.pattern, row] as const),
    ).values())
    : [];
  const supplyLedger = gapData && rowsByScope
    ? computeMustApplySupplyLedger(
      gapData.opsRuns.filter((row) => row.metrics?.list_version === MUST_APPLY_VERSION),
      domesticCoverageRows,
    )
    : null;
  const coverage = coverageResult.status === "fulfilled" ? coverageResult.value : null;
  const userDistribution = industriesResult.status === "fulfilled" && industriesResult.value ? industriesResult.value : { counts: { domestic: {}, overseas: {} }, scopeUsers: { domestic: 0, overseas: 0 }, unset: 0 };
  const activeIndustries = Object.fromEntries(MUST_APPLY_SCOPES.map((scope) => [scope, MUST_APPLY_INDUSTRIES.filter((industry) => (scope === "domestic" && industry === DEFAULT_MUST_APPLY_INDUSTRY) || (userDistribution.counts[scope][industry] || 0) > 0)])) as Record<MustApplyScope, string[]>;
  const fetchCoverage = fetchResult.status === "fulfilled" && fetchResult.value ? Object.fromEntries(fetchResult.value) as Record<MustApplyScope, MustApplyFetchCoverage> : null;
  const fetchByIndustry = fetchCoverage ? Object.fromEntries(MUST_APPLY_SCOPES.map((scope) => [scope, groupFetchCoverageByIndustry(fetchCoverage[scope], MUST_APPLY_INDUSTRIES, scope)])) as Record<MustApplyScope, Record<string, MustApplyFetchCoverage>> : null;
  const extraOpsRuns = extraOpsResult.status === "fulfilled" ? extraOpsResult.value : null;
  // 读失败与「真的没有用户」必须分开：前者传 null 让报告显示读取失败，后者才是 0。
  const userAnalytics = analyticsResult.status === "fulfilled" ? analyticsResult.value : null;
  const reports = buildDailyReports({ crawl: operations?.today?.crawl || null, discovery: operations?.today?.discovery || null, insight: { today_created: operations?.insight?.today_created }, opsRuns: operations?.today?.ops_runs || [], opsRunRows: extraOpsRuns || [] });
  const users = operations?.today?.users || null;
  const resume = operations?.today?.resume || null;
  const todayRemoved = reports.find((report) => report.key === "dead_jobs")?.metrics.find((metric) => metric.label === "判死")?.value ?? null;
  const validBand = jobs ? band(share(jobs.validActive, jobs.activeTotal), HEALTH_THRESHOLDS.validActiveShare, "higher") : "empty";
  const thinBand = jobs ? band(share(jobs.thinActive, jobs.activeTotal), HEALTH_THRESHOLDS.thinActiveShare, "lower") : "empty";
  const checkedBand = jobs ? band(share(jobs.neverChecked, jobs.activeTotal), HEALTH_THRESHOLDS.neverCheckedShare, "lower") : "empty";
  const clickStatus: BandTone = !clickValidity ? "muted" : clickValidity.totalOpens === 0 && clickValidity.livenessTotal === 0 ? "muted" : sectionStatusFromBand(band(clickValidity.probeValidityRate, HEALTH_THRESHOLDS.clickValidity, "higher"));
  const fallback = { scope: "domestic" as MustApplyScope, industry: DEFAULT_MUST_APPLY_INDUSTRY, healthy: null as number | null, total: 30, zeroHealthyCompanies: [] as string[], blindCompanies: [] as string[], userCount: 0 };
  const candidates = MUST_APPLY_SCOPES.flatMap((scope) => activeIndustries[scope].map((industry) => { const rows = rowsByScope?.[scope]?.[industry]; return { scope, industry, healthy: rows ? rows.filter((row) => row.healthy > 0).length : null, total: mustApplyByIndustry(scope)[industry].length, zeroHealthyCompanies: rows ? rows.filter((row) => row.healthy === 0).map((row) => row.name) : [], blindCompanies: rows ? rows.filter((row) => row.healthy > 0 && row.checked72h === 0).map((row) => row.name) : [], userCount: userDistribution.counts[scope][industry] || 0 }; }));
  const worst = candidates.reduce((current, item) => { const ranks: Record<HealthBand, number> = { empty: 0, good: 1, warn: 2, bad: 3 }; return ranks[mustApplyIndustryBand(rowsByScope?.[item.scope]?.[item.industry] || null)] > ranks[mustApplyIndustryBand(rowsByScope?.[current.scope]?.[current.industry] || null)] ? item : current; }, fallback);
  const health = evaluateCombinedHealth({ validActive: jobs?.validActive, crawlRuns: operations?.today?.crawl?.runs, crawlFailedRuns: operations?.today?.crawl?.failed_runs, clickProbeValidityRate: clickValidity?.probeValidityRate, mustApplyHealthyCompanies: rowsByScope ? worst.healthy : null, mustApplyTotalCompanies: worst.total, mustApplyZeroHealthyCompanies: worst.zeroHealthyCompanies, mustApplyBlindCompanies: worst.blindCompanies, mustApplyIndustries: candidates, coverageAvgPct: coverage?.avgCoveragePct, coverageBlindSources: coverage?.blind });
  const supplyStatus: BandTone = !rowsByScope ? "muted" : sectionStatusFromBand(worstBand([health.bands.mustApply, coverageBand(coverage?.avgCoveragePct)]));
  // 概览的系统色取所有模块里最严的那一档，与模块卡、热力图同出一个 moduleVerdict。
  const systemStatus: BandTone = !operations
    ? "muted"
    : reports.some((report) => report.verdict === "broken")
      ? "danger"
      : reports.some((report) => report.verdict === "attention")
        ? "warning"
        : reports.some((report) => report.verdict === "healthy")
          ? "success"
          : "muted";
  const heroDataMissing = !jobs && !operations;
  const heroStatus: BandTone = heroDataMissing || health.level === "critical" ? "danger" : health.actions.length ? "warning" : "success";
  const refreshedAt = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date());
  const tabs = [["overview", "总览"], ["jobs", "岗位库"], ["supply", "必投供给"], ["users", "用户行为"], ["system", "系统运行"]] as const;
  const dailySeries = dailySeriesResult.status === "fulfilled" ? dailySeriesResult.value : null;
  const dailySeriesUnavailable = dailySeriesResult.status === "rejected";
  const content = tab === "overview" ? <OverviewTab health={health} heroStatus={heroStatus} heroDataMissing={heroDataMissing} jobs={jobs} users={users} supplyStatus={supplyStatus} systemStatus={systemStatus} worst={worst} rowsByScope={rowsByScope} reports={reports} refreshedAt={refreshedAt} disputesOpen={operations?.insight?.disputes_open} dailySeries={dailySeries} dailySeriesUnavailable={dailySeriesUnavailable} /> : tab === "jobs" ? <JobsTab jobs={jobs} clickValidity={clickValidity} clickStatus={clickStatus} coverage={coverage} operations={operations} todayRemoved={todayRemoved} validBand={validBand} checkedBand={checkedBand} dailySeries={dailySeries} dailySeriesUnavailable={dailySeriesUnavailable} /> : tab === "supply" ? <SupplyTab rowsByScope={rowsByScope} fetchByIndustry={fetchByIndustry} activeIndustries={activeIndustries} userDistribution={userDistribution} worst={worst} gapSummary={gapSummary} governanceItems={governanceItems} ledger={supplyLedger} mustApplyScope={mustApplyScope} /> : tab === "users" ? <UserTab analytics={userAnalytics} includeStaff={includeStaff} users={users} resume={resume} /> : <SystemTab operations={operations} reports={reports} refreshedAt={refreshedAt} dailySeries={dailySeries} dailySeriesUnavailable={dailySeriesUnavailable} extraOpsUnavailable={extraOpsResult.status === "rejected"} />;
  // 模块切换已经上移到顶栏（AdminNav），页头不再重复一排一模一样的胶囊。
  const tabLabel = tabs.find(([key]) => key === tab)?.[1] || "总览";
  return <div className="min-h-screen bg-editorial"><AdminNav activeTab={tab} /><ProductPage maxWidth="max-w-6xl"><ProductHero eyebrow="运营健康" title={`管理员看板 · ${tabLabel}`} description="今天真实的运行与供给情况。" icon={ShieldCheck} /><main className="mt-6">{content}</main></ProductPage></div>;
}

import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { AnimatedStat } from "@/components/ui/animated-stat";
import { CoverageGrid, MiniBar, StackedBar, StatRing, StatusDot } from "@/components/health-viz";
import {
  band,
  bandTone,
  buildDailyReports,
  computeClickValidityMetrics,
  coverageBand,
  evaluateCombinedHealth,
  formatPercent,
  getCoverageSnapshot,
  getMustApplyFetchCoverage,
  HEALTH_THRESHOLDS,
  normalizeCrawlSources,
  translateOperationalTerm,
  type ClickValidityMetrics,
  type CombinedHealthVerdict,
  type CoverageSnapshot,
  type CrawlSourceRow,
  type DailyReport,
  type BandTone,
  type HealthBand,
  type MustApplyFetchCoverage,
  type MustApplyFetchCoverageCompany,
  type OpsRunAggregateRow,
  type TodayCrawlRow,
  type TodayDiscoveryRow,
} from "@/lib/admin-health";
import { isAdmin } from "@/lib/auth";
import { getJobsHealthSnapshot, getMustApplyCoverage, type JobsHealthSnapshot, type MustApplyCoverageRow } from "@/lib/jobs-store/read";
import { MUST_APPLY_LIST } from "@/lib/must-apply-list";
import { createServiceClient } from "@/lib/supabaseService";
import {
  Bug,
  CaretDown,
  ChartBar,
  Clock,
  Compass,
  Database,
  FileText,
  Heartbeat,
  MagnifyingGlass,
  PaperPlaneTilt,
  Pulse,
  ShieldCheck,
  UserCircle,
  Users,
} from "@phosphor-icons/react/ssr";
import { redirect } from "next/navigation";
import type { ComponentType, ReactNode } from "react";

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

async function loadSupabaseHealth(): Promise<SupabaseHealthSnapshot> {
  const service = createServiceClient();
  const { data, error } = await service.rpc("admin_health_snapshot", { p_window: "7 days" });
  if (error) throw new Error(error.message);
  return (data || {}) as SupabaseHealthSnapshot;
}

// 北极星：必投清单健康覆盖。jobs 在香港库、sources 在 Supabase，无法单条 SQL join → Node 层按公司名 needle 合并。
type MustApplyRow = MustApplyCoverageRow & { hasSource: boolean; sourceEnabled: boolean };

async function loadMustApplyCoverage(): Promise<MustApplyRow[]> {
  const [coverage, sourcesRes] = await Promise.all([
    getMustApplyCoverage(MUST_APPLY_LIST),
    createServiceClient().from("sources").select("company, enabled"),
  ]);
  if (sourcesRes.error) throw new Error(sourcesRes.error.message);
  const sources = (sourcesRes.data || []) as Array<{ company: string | null; enabled: boolean }>;
  return MUST_APPLY_LIST.map((c, i) => {
    const needle = c.pattern.replace(/%/g, "").toLowerCase();
    const matched = sources.filter((s) => (s.company || "").toLowerCase().includes(needle));
    return {
      ...coverage[i],
      hasSource: matched.length > 0,
      sourceEnabled: matched.some((s) => s.enabled),
    };
  });
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
  return rate == null ? "暂无数据" : `${(rate * 100).toFixed(1)}%`;
}

function share(numerator: number | null | undefined, denominator: number | null | undefined): number | null {
  const total = Number(denominator || 0);
  if (total <= 0) return null;
  return Number(numerator || 0) / total;
}

function sectionStatusFromBand(value: HealthBand): SectionStatus {
  if (value === "bad") return "critical";
  if (value === "warn") return "warn";
  if (value === "good") return "ok";
  return "idle";
}

function worstBand(values: HealthBand[]): HealthBand {
  if (values.includes("bad")) return "bad";
  if (values.includes("warn")) return "warn";
  if (values.includes("good")) return "good";
  return "empty";
}

const BAND_CHIP_CLASS: Record<ReturnType<typeof bandTone>, string> = {
  danger: "bg-[#f7e6e1] text-[#9c4a3c] dark:bg-[#7a392e]/30 dark:text-[#e6a99f]",
  warning: "bg-[#fbecd7] text-[#8f6225] dark:bg-[#825d28]/30 dark:text-[#e0b15a]",
  success: "bg-[#e6f2d3] text-[#5a7a2f] dark:bg-[#a3d06a]/15 dark:text-[#a3d06a]",
  muted: "bg-[#ece7dd] text-[#6b655a] dark:bg-white/[0.08] dark:text-[#b6ad9d]",
};

// 板块状态：ok 正常 / warn 注意 / critical 要处理 / idle 无数据。
// 用来给「今日一览」的状态灯、折叠条的徽章、以及是否默认展开统一定调。
type SectionStatus = "ok" | "warn" | "critical" | "idle";

const STATUS_META: Record<SectionStatus, { icon: string; label: string; badge: string; chip: string }> = {
  critical: {
    icon: "🔴",
    label: "要处理",
    badge: "bg-[#f7e6e1] text-[#9c4a3c] dark:bg-[#7a392e]/30 dark:text-[#e6a99f]",
    chip: "border-[#e0b4ac] bg-[#f7e6e1] dark:border-[#7a392e]/50 dark:bg-[#3a201a]",
  },
  warn: {
    icon: "⚠️",
    label: "注意",
    badge: "bg-[#fbecd7] text-[#8f6225] dark:bg-[#825d28]/30 dark:text-[#e0b15a]",
    chip: "border-[#edc995] bg-[#fbecd7] dark:border-[#825d28]/50 dark:bg-[#392a17]",
  },
  idle: {
    icon: "•",
    label: "无数据",
    badge: "bg-[#ece7dd] text-[#6b655a] dark:bg-white/[0.08] dark:text-[#b6ad9d]",
    chip: "border-black/[0.06] bg-white/40 dark:border-white/10 dark:bg-white/[0.03]",
  },
  ok: {
    icon: "✅",
    label: "正常",
    badge: "bg-[#e6f2d3] text-[#5a7a2f] dark:bg-[#a3d06a]/15 dark:text-[#a3d06a]",
    chip: "border-[#c8dda9] bg-[#edf6df] dark:border-[#5d793d]/50 dark:bg-[#203018]",
  },
};

// 可折叠板块：收起时只留一根状态条（标题＋状态徽章＋一句话概要），展开才显示明细。
// 用原生 <details>，无需客户端 JS，兼容 server component。出问题的板块 defaultOpen 自动展开。
function Section({
  title,
  description,
  status = "ok",
  summary,
  defaultOpen = false,
  children,
}: {
  title: string;
  description: string;
  status?: SectionStatus;
  summary?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const meta = STATUS_META[status];
  return (
    <details open={defaultOpen} className="surface group overflow-hidden">
      <summary className="flex cursor-pointer list-none items-center gap-3 p-5 sm:p-6 [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="text-lg leading-none">
          {meta.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h2 className="text-balance text-lg font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{title}</h2>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${meta.badge}`}>{meta.label}</span>
          </div>
          <p className="mt-0.5 truncate text-sm text-[#6b655a] dark:text-[#b6ad9d]">{summary || description}</p>
        </div>
        <CaretDown
          size={18}
          className="shrink-0 text-[#8a8275] transition-transform duration-200 group-open:rotate-180 dark:text-[#9a9184]"
          aria-hidden="true"
        />
      </summary>
      <div className="border-t border-black/[0.06] px-5 pb-5 pt-5 sm:px-6 sm:pb-6 dark:border-white/[0.08]">
        <p className="mb-5 text-pretty text-sm leading-6 text-[#6b655a] dark:text-[#b6ad9d]">{description}</p>
        {children}
      </div>
    </details>
  );
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
  return Number(value || 0).toLocaleString("zh-CN");
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
  return value === "—" ? "暂无数据" : value;
}

function ratioToPercentValue(value: number | null): number | null {
  return value == null ? null : Math.round(value * 100);
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

function verdictTone(level: CombinedHealthVerdict["level"]): BandTone {
  if (level === "critical") return "danger";
  if (level === "warning") return "warning";
  return "success";
}

function operationTone(status: DailyReport["status"]): BandTone {
  if (status === "failed") return "danger";
  if (status === "idle") return "muted";
  return "success";
}

function bandTextClass(value: HealthBand): string {
  if (value === "bad") return "font-semibold text-[#9c4a3c] dark:text-[#e6a99f]";
  if (value === "warn") return "font-semibold text-[#8f6225] dark:text-[#e0b15a]";
  if (value === "good") return "font-semibold text-[#3f3a33] dark:text-[#d9d0c2]";
  return "text-[#8a8275] dark:text-[#9a9184]";
}

function coverageTextClass(value: number | null): string {
  return bandTextClass(coverageBand(value));
}

const REPORT_ICONS: Record<DailyReport["key"], ComponentType<any>> = {
  crawl: Bug,
  enrichment: FileText,
  dead_jobs: Heartbeat,
  insights: Compass,
  auto_discover: Database,
  discovery: MagnifyingGlass,
};

function displayOperationMetricLabel(label: string): string {
  if (label === "判死") return translateOperationalTerm("today_removed");
  return label;
}

function OperationCard({ report }: { report: DailyReport }) {
  const Icon = REPORT_ICONS[report.key];
  const statusClass = {
    success: "bg-[#e6f2d3] text-[#5a7a2f] dark:bg-[#a3d06a]/15 dark:text-[#a3d06a]",
    idle: "bg-[#ece7dd] text-[#6b655a] dark:bg-white/[0.08] dark:text-[#b6ad9d]",
    failed: "bg-[#f7e6e1] text-[#9c4a3c] dark:bg-[#7a392e]/30 dark:text-[#e6a99f]",
  }[report.status];

  return (
    <article className="surface-soft flex h-full flex-col p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 gap-3">
          <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]">
            <Icon size={20} weight="fill" aria-hidden="true" />
          </div>
          <div>
            <h3 className="font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{report.title}</h3>
            <p className="mt-1 text-pretty text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
              {report.description}
            </p>
          </div>
        </div>
        <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold ${statusClass}`}>
          {report.statusLabel}
        </span>
      </div>

      <div className={`mt-5 grid grid-cols-2 gap-2 ${report.metrics.length >= 3 ? "sm:grid-cols-3" : ""}`}>
        {report.metrics.map((metric) => (
          <div
            key={metric.label}
            className="rounded-xl border border-black/[0.06] bg-white/55 px-3 py-3 dark:border-white/[0.08] dark:bg-white/[0.04]"
          >
            <p className="text-[11px] text-[#8a8275] dark:text-[#9a9184]">{displayOperationMetricLabel(metric.label)}</p>
            <p className="mt-1 text-lg font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">
              {metric.value == null ? (
                <span className="text-sm font-medium text-[#8a8275] dark:text-[#9a9184]">积累中</span>
              ) : (
                formatCount(metric.value)
              )}
            </p>
          </div>
        ))}
      </div>

      <p className="mt-auto flex items-center gap-1.5 pt-4 text-xs text-[#8a8275] dark:text-[#9a9184]">
        <Clock size={14} aria-hidden="true" />
        上次运行：{formatRunTime(report.lastRunAt)}
      </p>
    </article>
  );
}

function AccumulatingMetric({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-black/10 bg-white/35 p-4 dark:border-white/10 dark:bg-white/[0.03]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-[#3f3a33] dark:text-[#d9d0c2]">{title}</p>
          <p className="mt-2 text-pretty text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">{description}</p>
        </div>
        <span className="shrink-0 rounded-full bg-[#ece7dd] px-2.5 py-1 text-[11px] font-semibold text-[#6b655a] dark:bg-white/[0.08] dark:text-[#b6ad9d]">
          积累中
        </span>
      </div>
    </div>
  );
}

function AnimatedNumberText({
  value,
  suffix = "",
  fallback = "暂无数据",
  className = "text-3xl",
}: {
  value: number | null;
  suffix?: string;
  fallback?: string;
  className?: string;
}) {
  if (value == null) {
    return <span className="text-sm font-semibold text-[#8a8275] dark:text-[#9a9184]">{fallback}</span>;
  }
  return (
    <span className={`inline-flex items-baseline gap-0.5 font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf] ${className}`}>
      <AnimatedStat value={value} />
      {suffix && <span className="text-[0.58em]">{suffix}</span>}
    </span>
  );
}

function VisualKpiTile({
  label,
  value,
  suffix,
  fallback,
  pct,
  tone,
  caption,
}: {
  label: string;
  value: number | null;
  suffix?: string;
  fallback?: string;
  pct: number | null;
  tone: BandTone;
  caption: string;
}) {
  return (
    <div className="surface-soft p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-[#3f3a33] dark:text-[#d9d0c2]">{label}</p>
        <StatusDot tone={tone} />
      </div>
      <div className="mt-3">
        <AnimatedNumberText value={value} suffix={suffix} fallback={fallback} />
      </div>
      <MiniBar pct={pct} tone={tone} className="mt-3" />
      <p className="mt-2 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">{caption}</p>
    </div>
  );
}

function VisualChip({
  label,
  value,
  tone = "muted",
  detail,
}: {
  label: string;
  value: string;
  tone?: BandTone;
  detail?: string;
}) {
  return (
    <div className="rounded-2xl border border-black/[0.06] bg-white/45 px-3.5 py-3 dark:border-white/[0.08] dark:bg-white/[0.04]">
      <div className="flex items-center gap-2">
        <StatusDot tone={tone} />
        <p className="text-xs font-medium text-[#6b655a] dark:text-[#b6ad9d]">{label}</p>
      </div>
      <p className="mt-1 text-lg font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">{value}</p>
      {detail && <p className="mt-1 text-[11px] leading-4 text-[#8a8275] dark:text-[#9a9184]">{detail}</p>}
    </div>
  );
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
      <p className="rounded-2xl border border-dashed border-black/10 bg-white/35 px-4 py-5 text-sm text-[#8a8275] dark:border-white/10 dark:bg-white/[0.03] dark:text-[#9a9184]">
        {emptyLabel}
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {items.map((item) => {
        const itemBand = coverageBand(item.pct);
        const tone = bandTone(itemBand);
        return (
          <div key={item.key} className="grid items-center gap-2 sm:grid-cols-[10rem_1fr_5.5rem]">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-[#1a1714] dark:text-[#f3ecdf]">{item.label}</p>
              {item.caption && <p className="truncate text-[11px] text-[#9a9184] dark:text-[#837c70]">{item.caption}</p>}
            </div>
            {item.pct == null ? (
              <div className="flex min-w-0 justify-start">
                <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${BAND_CHIP_CLASS.muted}`}>
                  算不出（盲区）
                </span>
              </div>
            ) : (
              <div className="relative min-w-0">
                <MiniBar pct={item.pct / 100} tone={tone} />
                <span className="absolute left-[90%] top-[-3px] h-[calc(100%+6px)] w-px bg-[#1a1714]/30 dark:bg-white/40" />
              </div>
            )}
            <div className="text-left text-sm tabular-nums text-[#3f3a33] dark:text-[#d9d0c2] sm:text-right">
              {item.pct == null ? (
                <span className="text-[#8a8275] dark:text-[#9a9184]">暂无数据</span>
              ) : (
                <span className={coverageTextClass(item.pct)}>{item.pct}%</span>
              )}
              {item.fetched != null && item.total != null && (
                <p className="text-[11px] text-[#9a9184] dark:text-[#837c70]">
                  {formatCount(item.fetched)}/{formatCount(item.total)}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function HealthHeroVisual({
  health,
  refreshedAt,
  mustApply,
  mustTotal,
  maHealthy,
  clickValidity,
  coverage,
}: {
  health: CombinedHealthVerdict;
  refreshedAt: string;
  mustApply: MustApplyRow[] | null;
  mustTotal: number;
  maHealthy: number;
  clickValidity: ClickValidityMetrics | null;
  coverage: CoverageSnapshot | null;
}) {
  const coreBands = [health.bands.mustApply, health.bands.clickValidity, health.bands.coverage];
  const coreMeasured = coreBands.filter((value) => value !== "empty").length;
  const coreGood = coreBands.filter((value) => value === "good").length;
  const corePct = coreMeasured > 0 ? coreGood / coreMeasured : null;
  const ringTone = corePct == null ? "muted" : verdictTone(health.level);
  const clickPctValue = ratioToPercentValue(clickValidity?.probeValidityRate ?? null);

  return (
    <div className="grid gap-5 lg:grid-cols-[11rem_1fr] lg:items-center">
      <div className="flex justify-center lg:justify-start">
        <StatRing pct={corePct} tone={ringTone} size={148} stroke={13}>
          <span
            className={`text-2xl font-semibold ${
              health.level === "healthy" && corePct != null
                ? "text-[#00c853] dark:text-[#00e676]"
                : "text-[#1a1714] dark:text-[#f3ecdf]"
            }`}
          >
            {corePct == null ? "积累中" : health.label}
          </span>
          <span className="mt-1 text-[11px] leading-4 text-[#6b655a] dark:text-[#b6ad9d]">
            {corePct == null ? "0/3 项可判定" : `${coreGood}/3 项核心达标`}
          </span>
        </StatRing>
      </div>

      <div className="space-y-4">
        <div className="grid gap-3 md:grid-cols-3">
          <VisualKpiTile
            label="必投健康覆盖"
            value={mustApply ? maHealthy : null}
            suffix={`/${mustTotal}`}
            fallback="积累中"
            pct={mustApply ? share(maHealthy, mustTotal) : null}
            tone={bandTone(health.bands.mustApply)}
            caption={`目标 ≥${HEALTH_THRESHOLDS.mustApplyHealthyCompanies.good}/30`}
          />
          <VisualKpiTile
            label="点开仍在招"
            value={clickPctValue}
            suffix="%"
            fallback="暂无数据"
            pct={clickValidity?.probeValidityRate ?? null}
            tone={bandTone(health.bands.clickValidity)}
            caption={`目标 ≥${Math.round(HEALTH_THRESHOLDS.clickValidity.good * 100)}%，不造昨日对比`}
          />
          <VisualKpiTile
            label="全库抓全率"
            value={coverage?.avgCoveragePct ?? null}
            suffix="%"
            fallback="积累中"
            pct={percentToRatio(coverage?.avgCoveragePct ?? null)}
            tone={bandTone(health.bands.coverage)}
            caption={`目标 ≥${HEALTH_THRESHOLDS.coveragePct.good}%；盲区不算 0%`}
          />
        </div>

        <div className="flex flex-wrap gap-2">
          {health.actions.length > 0 ? (
            health.actions.map((action, index) => (
              <span
                key={action}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold ${
                  health.level === "critical" && index === 0 ? BAND_CHIP_CLASS.danger : BAND_CHIP_CLASS.warning
                }`}
              >
                <span aria-hidden="true">{health.level === "critical" && index === 0 ? "🔴" : "⚠️"}</span>
                {action}
              </span>
            ))
          ) : (
            <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold ${BAND_CHIP_CLASS.success}`}>
              <StatusDot tone="success" />
              暂无红线行动项
            </span>
          )}
        </div>

        <p className="text-[11px] leading-5 text-[#8a8275] dark:text-[#9a9184]">
          页面生成时间：<span className="tabular-nums">{refreshedAt}</span> 北京时间 · 趋势基线 · 积累中 · 快照指标不造昨日对比
        </p>
      </div>
    </div>
  );
}

function CoverageSection({
  snapshot,
  status = "ok",
  summary,
  defaultOpen = false,
}: {
  snapshot: CoverageSnapshot | null;
  status?: SectionStatus;
  summary?: string;
  defaultOpen?: boolean;
}) {
  if (!snapshot) {
    return (
      <Section
        title="全库抓全率"
        description="每家公司：官网有多少岗 vs 我们抓到多少。排在前面的是抓漏最多的，优先补。"
        status={status}
        summary={summary}
        defaultOpen={defaultOpen}
      >
        <ErrorPanel label="全库抓全率" />
      </Section>
    );
  }

  const hasCoverageData =
    snapshot.measurable > 0 ||
    snapshot.blind > 0 ||
    snapshot.avgCoveragePct != null ||
    snapshot.underCount > 0 ||
    snapshot.underSources.length > 0;
  const averageTone = bandTone(coverageBand(snapshot.avgCoveragePct));

  return (
    <Section
      title="全库抓全率"
      description="每家公司：官网有多少岗 vs 我们抓到多少。排在前面的是抓漏最多的，优先补。"
      status={status}
      summary={summary}
      defaultOpen={defaultOpen}
    >
      {!hasCoverageData ? (
        <AccumulatingMetric title="全库抓全率" description="覆盖率数据将在下次抓取后生成" />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1.15fr_1fr_1fr_1fr]">
            <div className="surface-soft flex items-center gap-4 p-4">
              <StatRing pct={percentToRatio(snapshot.avgCoveragePct)} tone={averageTone} size={78} stroke={8} target={0.9}>
                <span className="text-sm font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">
                  {snapshot.avgCoveragePct == null ? "积累中" : `${snapshot.avgCoveragePct}%`}
                </span>
              </StatRing>
              <div className="min-w-0">
                <p className="text-sm font-medium text-[#3f3a33] dark:text-[#d9d0c2]">平均抓全率</p>
                <p className="mt-1 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
                  目标 {HEALTH_THRESHOLDS.coveragePct.good}%，只算官网报总数的源。
                </p>
              </div>
            </div>
            <VisualChip label="可测源数" value={formatCount(snapshot.measurable)} tone="muted" />
            <VisualChip label="抓不全源数（<90%）" value={formatCount(snapshot.underCount)} tone={snapshot.underCount > 0 ? "warning" : "success"} />
            <VisualChip label="盲区源数" value={formatCount(snapshot.blind)} tone="muted" detail="官网不报总数" />
          </div>
          <p className="mt-3 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
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
    </Section>
  );
}

// 北极星卡：必投清单健康覆盖。回答「目标用户最想投的头部公司，我们到底罩住了几家」——
// 这是产品对用户承诺的真实覆盖率，掉了要优先修它，别被库存总量的大数字安慰。
function MustApplyFetchCoverageBlock({ coverage }: { coverage: MustApplyFetchCoverage | null }) {
  if (!coverage) {
    return (
      <div className="mt-5 border-t border-black/[0.06] pt-5 dark:border-white/[0.08]">
        <ErrorPanel label="必投30家抓全率" />
      </div>
    );
  }

  const total = coverage.total || MUST_APPLY_LIST.length;
  const leaking = coverage.companies.filter(
    (company): company is MustApplyFetchCoverageCompany & { coveragePct: number } =>
      company.coveragePct !== null && company.coveragePct < 90,
  );
  const averageTone = bandTone(coverageBand(coverage.avgPct));

  return (
    <div className="mt-5 border-t border-black/[0.06] pt-5 dark:border-white/[0.08]">
      <div className="mb-3">
        <h3 className="font-semibold text-[#1a1714] dark:text-[#f3ecdf]">必投30家抓全率</h3>
        <p className="mt-1 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
          官网总数 vs 我们抓到；抓全率低于 90% 的公司排在前面。
        </p>
      </div>

      {coverage.measurable === 0 && coverage.companies.length === 0 ? (
        <AccumulatingMetric title="必投30家抓全率" description="还没有抓取填入官网总数，暂时算不出抓全率。" />
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-[8.5rem_1fr] lg:items-center">
            <StatRing pct={percentToRatio(coverage.avgPct)} tone={averageTone} size={118} stroke={10} target={0.9}>
              <span className="text-lg font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">
                {coverage.avgPct == null ? "积累中" : `${coverage.avgPct}%`}
              </span>
              <span className="mt-0.5 text-[10px] text-[#8a8275] dark:text-[#9a9184]">平均抓全率</span>
            </StatRing>
            <div className="grid gap-3 sm:grid-cols-3">
              <VisualChip label="抓全家数" value={`${coverage.fullyFetched}/${total}`} tone="muted" detail="≥90% 才算抓全" />
              <VisualChip label="盲区(算不出)" value={formatCount(coverage.blind)} tone="muted" detail="官网不报总数" />
              <VisualChip label="可测公司" value={formatCount(coverage.measurable)} tone="muted" detail="只用可测源算平均" />
            </div>
          </div>

          {coverage.measurable === 0 ? (
            <p className="mt-4 rounded-2xl border border-dashed border-black/10 bg-white/35 px-4 py-5 text-sm text-[#8a8275] dark:border-white/10 dark:bg-white/[0.03] dark:text-[#9a9184]">
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

function MustApplySection({
  rows,
  fetchCoverage,
  healthBand = "empty",
  summary,
}: {
  rows: MustApplyRow[] | null;
  fetchCoverage: MustApplyFetchCoverage | null;
  healthBand?: HealthBand;
  summary?: string;
}) {
  const status = sectionStatusFromBand(healthBand);
  const meta = STATUS_META[status];
  if (!rows) {
    return (
      <section className="surface p-5 sm:p-6">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold text-[#1a1714] dark:text-[#f3ecdf]">必投清单健康覆盖</h2>
            <p className="mt-1 text-sm text-[#6b655a] dark:text-[#b6ad9d]">目标用户最常投的头部公司逐家对账。</p>
          </div>
          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${STATUS_META.idle.badge}`}>暂无数据</span>
        </div>
        <ErrorPanel label="必投清单覆盖" />
        <MustApplyFetchCoverageBlock coverage={fetchCoverage} />
      </section>
    );
  }
  const n = rows.length;
  const healthyCount = rows.filter((r) => r.healthy > 0).length;
  const freshCount = rows.filter((r) => r.new7d > 0).length;
  const checkedCount = rows.filter((r) => r.checked72h > 0).length;
  const gaps = rows.filter((r) => r.healthy === 0);
  const blind = rows.filter((r) => r.healthy > 0 && r.checked72h === 0);
  const gridCells = rows.map((r) => {
    const tone: BandTone = r.healthy === 0 ? "danger" : r.checked72h === 0 ? "warning" : "success";
    return {
      tone,
      label: `${r.name}｜健康岗 ${r.healthy}·近7天新 ${r.new7d}·72h核验 ${r.checked72h}｜${sourceStatusLabel(r)}`,
    };
  });
  return (
    <section className="surface p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-[#1a1714] dark:text-[#f3ecdf]">必投清单健康覆盖</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-[#6b655a] dark:text-[#b6ad9d]">
            30 家目标公司逐家对账：有没有健康岗、近 7 天有没有新岗、72 小时内有没有核验。这里掉了，库存总量再大也不能算健康。
          </p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${meta.badge}`}>{meta.label}</span>
      </div>
      {summary && <p className="mb-4 text-sm text-[#6b655a] dark:text-[#b6ad9d]">{summary}</p>}

      <div className="grid gap-5 lg:grid-cols-[11rem_1fr] lg:items-center">
        <div className="flex justify-center lg:justify-start">
          <StatRing pct={share(healthyCount, n)} tone={bandTone(healthBand)} size={154} stroke={12} target={28 / 30}>
            <span className="inline-flex items-baseline gap-0.5 text-3xl font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">
              <AnimatedStat value={healthyCount} />
              <span className="text-sm">/30</span>
            </span>
            <span className="mt-1 text-[11px] leading-4 text-[#6b655a] dark:text-[#b6ad9d]">家有健康岗</span>
          </StatRing>
        </div>
        <div className="min-w-0">
          <CoverageGrid cells={gridCells} />
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-[#6b655a] dark:text-[#b6ad9d]">
            <span className="inline-flex items-center gap-1.5"><StatusDot tone="success" />有健康岗</span>
            <span className="inline-flex items-center gap-1.5"><StatusDot tone="warning" />72h未核验</span>
            <span className="inline-flex items-center gap-1.5"><StatusDot tone="danger" />零健康岗</span>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <VisualChip label="近 7 天有新岗" value={`${freshCount}/${n}`} tone="muted" detail="活水信号，不作健康阈值" />
        <VisualChip label="72h 内核验过" value={`${checkedCount}/${n}`} tone={blind.length > 0 ? "warning" : "success"} detail="有岗未核验会在下方点名" />
        <VisualChip label="健康覆盖目标" value={`≥${HEALTH_THRESHOLDS.mustApplyHealthyCompanies.good}/30`} tone={bandTone(healthBand)} detail="24-27 家为注意，低于 24 家为出事" />
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
              有岗但 72h 未核验：{blind.map((r) => r.name).join("、")}
            </p>
          )}
        </div>
      )}
      <MustApplyFetchCoverageBlock coverage={fetchCoverage} />
    </section>
  );
}

function ClickValiditySection({
  clickValidity,
  status,
  summary,
}: {
  clickValidity: ClickValidityMetrics | null;
  status: SectionStatus;
  summary: string;
}) {
  const meta = STATUS_META[status];
  const clickBand = band(clickValidity?.probeValidityRate, HEALTH_THRESHOLDS.clickValidity, "higher");
  const clickTone = bandTone(clickBand);
  const sample = clickValidity ? clickValidity.alive + clickValidity.dead : 0;
  return (
    <section className="surface p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-[#1a1714] dark:text-[#f3ecdf]">点一下能打开的比例（核心承诺）</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-[#6b655a] dark:text-[#b6ad9d]">
            用户点开官网那一刻，岗位是否还在招。目标是可直接核验的点击里 ≥99% 仍在招；没有数据时只标暂无数据，不当作 0。
          </p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${meta.badge}`}>{meta.label}</span>
      </div>
      <p className="mb-4 text-sm text-[#6b655a] dark:text-[#b6ad9d]">{summary}</p>
      {!clickValidity ? (
        <ErrorPanel label="点击有效率" />
      ) : (
        <>
          <div className="grid gap-5 lg:grid-cols-[11rem_1fr] lg:items-center">
            <div className="flex justify-center lg:justify-start">
              <StatRing pct={clickValidity.probeValidityRate} tone={clickTone} size={150} stroke={12} target={0.99}>
                {clickValidity.probeValidityRate == null ? (
                  <>
                    <span className="text-lg font-semibold text-[#8a8275] dark:text-[#9a9184]">暂无数据</span>
                    <span className="mt-1 text-[11px] text-[#8a8275] dark:text-[#9a9184]">目标 99%</span>
                  </>
                ) : (
                  <>
                    <span className="inline-flex items-baseline gap-0.5 text-3xl font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">
                      <AnimatedStat value={Math.round(clickValidity.probeValidityRate * 100)} />
                      <span className="text-sm">%</span>
                    </span>
                    <span className="mt-1 text-[11px] leading-4 text-[#6b655a] dark:text-[#b6ad9d]">点开仍在招</span>
                  </>
                )}
              </StatRing>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <VisualChip
                label="点击核验覆盖"
                value={formatRate(clickValidity.coverageRate)}
                tone={clickValidity.coverageRate == null ? "muted" : "success"}
                detail={`总点击 ${formatCount(clickValidity.totalOpens)}`}
              />
              <VisualChip
                label="探不动占比"
                value={formatRate(clickValidity.unknownRate)}
                tone={clickValidity.unknownRate == null ? "muted" : clickValidity.unknownRate > 0 ? "warning" : "success"}
                detail={`总核验 ${formatCount(clickValidity.livenessTotal)}`}
              />
              <VisualChip
                label="样本"
                value={formatCount(sample)}
                tone={sample > 0 ? "success" : "muted"}
                detail={`仍在招 ${formatCount(clickValidity.alive)} · 已关闭 ${formatCount(clickValidity.dead)}`}
              />
              <VisualChip
                label="SPA 源死岗抽检率"
                value="暂无数据"
                tone="muted"
                detail="审计抽样还未接入"
              />
            </div>
          </div>

          <p className="mt-3 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
            目标 99%。可探源和不可探源分开报，不把探不动的点击塞进成功率。
          </p>

          {clickValidity.byAdapter.length > 0 && (
            <details className="mt-5 rounded-2xl border border-black/[0.07] bg-white/35 dark:border-white/[0.1] dark:bg-white/[0.03]">
              <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold text-[#1a1714] dark:text-[#f3ecdf] [&::-webkit-details-marker]:hidden">
                按技术来源展开
              </summary>
              <div className="overflow-auto border-t border-black/[0.06] dark:border-white/[0.08]">
                <table className="w-full min-w-[560px] text-left text-sm">
                  <caption className="caption-bottom px-4 py-3 text-left text-xs text-[#8a8275] dark:text-[#9a9184]">
                    来源名保留原始 adapter，方便工程定位。
                  </caption>
                  <thead className="bg-[#f4efe6] text-xs text-[#8a8275] dark:bg-[#1c1813] dark:text-[#9a9184]">
                    <tr>
                      <th className="px-4 py-3 font-medium">来源</th>
                      <th className="px-4 py-3 text-right font-medium">仍在招</th>
                      <th className="px-4 py-3 text-right font-medium">已关闭</th>
                      <th className="px-4 py-3 text-right font-medium">探不动</th>
                      <th className="px-4 py-3 font-medium">点开仍在招</th>
                    </tr>
                  </thead>
                  <tbody>
                    {clickValidity.byAdapter.map((a) => {
                      const adapterBand = band(a.validityRate, HEALTH_THRESHOLDS.clickValidity, "higher");
                      return (
                        <tr
                          key={a.adapter}
                          className="border-t border-black/[0.05] text-[#3f3a33] dark:border-white/[0.08] dark:text-[#d9d0c2]"
                        >
                          <td className="px-4 py-3 font-medium">{a.adapter}</td>
                          <td className="px-4 py-3 text-right tabular-nums">{a.alive}</td>
                          <td className="px-4 py-3 text-right tabular-nums">{a.dead}</td>
                          <td className="px-4 py-3 text-right tabular-nums">{a.unknown}</td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-3">
                              <MiniBar pct={a.validityRate} tone={bandTone(adapterBand)} className="min-w-28 flex-1" />
                              <span className={`w-16 text-right tabular-nums ${bandTextClass(adapterBand)}`}>
                                {formatRate(a.validityRate)}
                              </span>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
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

function SmallMetricTile({
  label,
  value,
  detail,
  icon: Icon,
  tone = "muted",
}: {
  label: string;
  value: number | null;
  detail: string;
  icon: ComponentType<any>;
  tone?: BandTone;
}) {
  return (
    <div className="surface-soft p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[#6b655a] dark:text-[#b6ad9d]">
          <span className={`grid size-7 place-items-center rounded-lg ${BAND_CHIP_CLASS[tone]}`}>
            <Icon size={15} weight="fill" aria-hidden="true" />
          </span>
          <p className="text-xs font-medium">{label}</p>
        </div>
        <StatusDot tone={tone} />
      </div>
      <div className="mt-3">
        <AnimatedNumberText value={value} fallback="暂无数据" className="text-2xl" />
      </div>
      <p className="mt-2 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">{detail}</p>
    </div>
  );
}

function JobsLibrarySection({
  jobs,
  operations,
  crawlSources,
  todayRemoved,
  jobsStatus,
  jobsSummary,
  validActiveShareBand,
  thinShareBand,
  neverCheckedShareBand,
}: {
  jobs: JobsHealthSnapshot | null;
  operations: SupabaseHealthSnapshot | null;
  crawlSources: ReturnType<typeof normalizeCrawlSources>;
  todayRemoved: number | null;
  jobsStatus: SectionStatus;
  jobsSummary: string;
  validActiveShareBand: HealthBand;
  thinShareBand: HealthBand;
  neverCheckedShareBand: HealthBand;
}) {
  return (
    <Section
      title="岗位库体检"
      description="看岗位构成、空壳岗和待核查量；招聘源按近 7 天实际运行结果计算成功率。"
      status={jobsStatus}
      summary={jobsSummary}
      defaultOpen={jobsStatus === "critical"}
    >
      {!jobs ? (
        <ErrorPanel label="岗位库体检" />
      ) : (
        <>
          <div className="grid gap-5 lg:grid-cols-[12rem_1fr] lg:items-center">
            <div className="flex justify-center lg:justify-start">
              <StatRing
                pct={share(jobs.validActive, jobs.activeTotal)}
                tone={bandTone(validActiveShareBand)}
                size={166}
                stroke={13}
              >
                <span className="inline-flex items-baseline gap-0.5 text-3xl font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">
                  <AnimatedStat value={jobs.validActive} />
                </span>
                <span className="mt-1 text-[11px] leading-4 text-[#6b655a] dark:text-[#b6ad9d]">
                  能投岗位 / 在招 {formatCount(jobs.activeTotal)}
                </span>
              </StatRing>
            </div>
            <div className="space-y-4">
              <div>
                <div className="flex items-center justify-between gap-3 text-xs text-[#6b655a] dark:text-[#b6ad9d]">
                  <span>在招构成</span>
                  <span className="tabular-nums">
                    能投 {formatCount(jobs.validActive)} · 空壳 {formatCount(jobs.thinActive)}
                  </span>
                </div>
                <StackedBar
                  className="mt-2 h-3"
                  total={jobs.activeTotal}
                  segments={[
                    { value: jobs.validActive, tone: "success" },
                    { value: jobs.thinActive, tone: "warning" },
                  ]}
                />
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#6b655a] dark:text-[#b6ad9d]">
                  <span className="inline-flex items-center gap-1.5"><StatusDot tone="success" />能投岗位</span>
                  <span className="inline-flex items-center gap-1.5"><StatusDot tone="warning" />空壳岗</span>
                </div>
              </div>
              <div className="rounded-2xl border border-black/[0.06] bg-white/40 p-4 dark:border-white/[0.08] dark:bg-white/[0.03]">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <p className="font-medium text-[#3f3a33] dark:text-[#d9d0c2]">待核查占在招</p>
                  <p className={`tabular-nums ${bandTextClass(neverCheckedShareBand)}`}>
                    {displayEmptyRate(formatPercent(jobs.neverChecked, jobs.activeTotal))}
                  </p>
                </div>
                <MiniBar pct={share(jobs.neverChecked, jobs.activeTotal)} tone={bandTone(neverCheckedShareBand)} className="mt-3" />
                <p className="mt-2 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
                  待核查会和在招岗位重叠，所以单独画条形，不放进圆环，避免重复计数。
                </p>
              </div>
            </div>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <SmallMetricTile label="今日新进" value={jobs.todayNew} detail="今天新入库的岗位" icon={ChartBar} tone="success" />
            <SmallMetricTile
              label={translateOperationalTerm("today_removed")}
              value={todayRemoved}
              detail="今天新判定失效的岗位"
              icon={Heartbeat}
              tone={todayRemoved == null ? "muted" : todayRemoved > 0 ? "warning" : "success"}
            />
            <SmallMetricTile
              label={translateOperationalTerm("expired")}
              value={jobs.expired}
              detail="探活确认永久移除"
              icon={Bug}
              tone="muted"
            />
            <SmallMetricTile
              label={translateOperationalTerm("removed")}
              value={jobs.removed}
              detail="疑似下线，后续可能恢复"
              icon={Clock}
              tone="muted"
            />
          </div>

          <p className="mt-3 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
            今日下架（今天新判定失效） · 已确认撤岗（探活确认永久移除） · 暂时下线（疑似下线，可能恢复） · 空壳岗（有链接但没岗位正文，质量差） · 待核查（还没探活验证）
          </p>
        </>
      )}

      <details className="mt-5 rounded-2xl border border-black/[0.07] bg-white/35 dark:border-white/[0.1] dark:bg-white/[0.03]">
        <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold text-[#1a1714] dark:text-[#f3ecdf] [&::-webkit-details-marker]:hidden">
          招聘源近 7 天表现
        </summary>
        <div className="border-t border-black/[0.06] p-4 dark:border-white/[0.08]">
          <p className="mb-3 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
            成功率按完成、部分完成、失败三类运行计算；没运行过的招聘源显示“暂无数据”。
          </p>
          {!operations ? (
            <ErrorPanel label="招聘源统计" />
          ) : crawlSources.length === 0 ? (
            <p className="text-sm text-[#8a8275] dark:text-[#9a9184]">暂无启用的招聘源。</p>
          ) : (
            <div className="max-h-[34rem] overflow-auto rounded-2xl border border-black/[0.07] dark:border-white/[0.1]">
              <table className="w-full min-w-[680px] text-left text-sm">
                <thead className="sticky top-0 z-10 bg-[#f4efe6] text-xs text-[#8a8275] dark:bg-[#1c1813] dark:text-[#9a9184]">
                  <tr>
                    <th className="px-4 py-3 font-medium">公司</th>
                    <th className="px-4 py-3 text-right font-medium">运行次数</th>
                    <th className="px-4 py-3 font-medium">成功率</th>
                    <th className="px-4 py-3 text-right font-medium">部分完成</th>
                    <th className="px-4 py-3 text-right font-medium">失败 / 跳过</th>
                  </tr>
                </thead>
                <tbody>
                  {crawlSources.map((source) => {
                    const successRatio = parsePercentRatio(source.successRate);
                    return (
                      <tr
                        key={source.sourceId}
                        className="border-t border-black/[0.05] text-[#3f3a33] dark:border-white/[0.08] dark:text-[#d9d0c2]"
                      >
                        <td className="max-w-80 px-4 py-3">
                          <p className="truncate font-medium">{source.company}</p>
                          <p className="mt-0.5 truncate text-[11px] text-[#9a9184] dark:text-[#837c70]">{source.adapterName}</p>
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">{source.runs}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-3">
                            <MiniBar pct={successRatio} tone={sourceSuccessTone(source.successRate)} className="min-w-28 flex-1" />
                            <span className="w-16 text-right tabular-nums">{displayEmptyRate(source.successRate)}</span>
                          </div>
                        </td>
                        <td className={`px-4 py-3 text-right tabular-nums ${source.partialRate === "—" ? "text-[#8a8275] dark:text-[#9a9184]" : ""}`}>
                          {displayEmptyRate(source.partialRate)}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">
                          <span className={source.failed > 0 ? "font-semibold text-[#9c4a3c] dark:text-[#e6a99f]" : ""}>{source.failed}</span>
                          <span className="text-[#9a9184] dark:text-[#837c70]"> / {source.skipped}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </details>
    </Section>
  );
}

const PRIMARY_REPORT_METRIC: Record<DailyReport["key"], string> = {
  crawl: "新增岗位",
  enrichment: "补全正文",
  dead_jobs: "判死",
  insights: "新增洞察",
  auto_discover: "新增源",
  discovery: "产出岗位",
};

function primaryReportMetric(report: DailyReport) {
  return (
    report.metrics.find((metric) => metric.label === PRIMARY_REPORT_METRIC[report.key]) ||
    report.metrics.find((metric) => metric.value != null) ||
    report.metrics[0]
  );
}

function DailyReportsSection({
  operations,
  reports,
  reportsStatus,
  reportsSummary,
}: {
  operations: SupabaseHealthSnapshot | null;
  reports: DailyReport[];
  reportsStatus: SectionStatus;
  reportsSummary: string;
}) {
  return (
    <Section
      title="每日战报"
      description="各模块每日战报：每个任务只露出一个最关键数字；完整明细默认收起。今天没记录是灰色，不当作失败。"
      status={reportsStatus}
      summary={reportsSummary}
      defaultOpen={reportsStatus === "critical"}
    >
      {!operations ? (
        <ErrorPanel label="每日战报" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {reports.map((report) => {
              const metric = primaryReportMetric(report);
              const tone = operationTone(report.status);
              return (
                <article key={report.key} className="rounded-2xl border border-black/[0.06] bg-white/45 p-3 dark:border-white/[0.08] dark:bg-white/[0.04]">
                  <div className="flex items-center gap-2">
                    <StatusDot tone={tone} />
                    <h3 className="truncate text-xs font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{report.title}</h3>
                  </div>
                  <p className="mt-3 text-2xl font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">
                    {metric?.value == null ? (
                      <span className="text-sm font-medium text-[#8a8275] dark:text-[#9a9184]">
                        {report.status === "idle" ? "今天没记录" : "积累中"}
                      </span>
                    ) : (
                      <AnimatedStat value={metric.value} />
                    )}
                  </p>
                  <p className="mt-1 truncate text-[11px] text-[#6b655a] dark:text-[#b6ad9d]">
                    {metric ? displayOperationMetricLabel(metric.label) : report.statusLabel}
                  </p>
                  <p className="mt-2 truncate text-[11px] text-[#9a9184] dark:text-[#837c70]">
                    上次运行 {formatRunTime(report.lastRunAt)}
                  </p>
                </article>
              );
            })}
          </div>

          <details className="mt-5 rounded-2xl border border-black/[0.07] bg-white/35 dark:border-white/[0.1] dark:bg-white/[0.03]">
            <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold text-[#1a1714] dark:text-[#f3ecdf] [&::-webkit-details-marker]:hidden">
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
    </Section>
  );
}

function BusinessPanel({ title, icon: Icon, children }: { title: string; icon: ComponentType<any>; children: ReactNode }) {
  return (
    <div className="surface-soft p-4">
      <div className="flex items-center gap-2">
        <span className="grid size-7 place-items-center rounded-lg bg-[#ece7dd] text-[#6b655a] dark:bg-white/[0.08] dark:text-[#b6ad9d]">
          <Icon size={15} weight="fill" aria-hidden="true" />
        </span>
        <h3 className="text-sm font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{title}</h3>
      </div>
      <div className="mt-3 grid gap-3">{children}</div>
    </div>
  );
}

function HeroNumberTile({
  label,
  value,
  detail,
  icon: Icon,
  tone = "muted",
  warning = false,
}: {
  label: string;
  value: number | string | null;
  detail: string;
  icon: ComponentType<any>;
  tone?: BandTone;
  warning?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl border px-3.5 py-3 ${
        warning
          ? "border-[#edc995] bg-[#fbecd7] dark:border-[#825d28]/60 dark:bg-[#392a17]"
          : "border-black/[0.06] bg-white/45 dark:border-white/[0.08] dark:bg-white/[0.04]"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[#6b655a] dark:text-[#b6ad9d]">
          <span className={`grid size-7 place-items-center rounded-lg ${BAND_CHIP_CLASS[tone]}`}>
            <Icon size={15} weight="fill" aria-hidden="true" />
          </span>
          <p className="text-xs font-medium">{label}</p>
        </div>
        <StatusDot tone={tone} />
      </div>
      <p className="mt-3 text-2xl font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">
        {typeof value === "number" ? <AnimatedStat value={value} /> : value ?? "暂无数据"}
      </p>
      <p className="mt-1 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">{detail}</p>
    </div>
  );
}

function BusinessSection({
  operations,
  users,
  resume,
  bizStatus,
  bizSummary,
}: {
  operations: SupabaseHealthSnapshot | null;
  users: NonNullable<SupabaseHealthSnapshot["today"]>["users"] | null;
  resume: NonNullable<SupabaseHealthSnapshot["today"]>["resume"] | null;
  bizStatus: SectionStatus;
  bizSummary: string;
}) {
  const disputesOpen = Number(operations?.insight?.disputes_open || 0);
  return (
    <Section
      title="用户与业务"
      description="用户、求职偏好、收藏投递、简历解析和职业洞察均使用现有真实数据。"
      status={bizStatus}
      summary={bizSummary}
      defaultOpen={bizStatus === "critical"}
    >
      {!operations ? (
        <ErrorPanel label="用户与业务统计" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <BusinessPanel title="增长" icon={Users}>
            {users ? (
              <>
                <HeroNumberTile label="总用户数" value={Number(users.total_users || 0)} detail="当前累计注册用户" icon={Users} tone="success" />
                <HeroNumberTile label="今日新增用户" value={Number(users.today_users || 0)} detail="真实日增量，不展示伪趋势" icon={UserCircle} tone="muted" />
              </>
            ) : (
              <ErrorPanel label="用户统计" />
            )}
            <AccumulatingMetric title="趋势基线" description="用户、覆盖、库存都是快照指标，历史基线还在积累中。" />
          </BusinessPanel>

          <BusinessPanel title="参与" icon={ChartBar}>
            {users ? (
              <>
                <HeroNumberTile label="设了求职偏好" value={Number(users.users_with_preferences || 0)} detail="已保存目标岗位、城市或关键词的用户" icon={UserCircle} tone="success" />
                <HeroNumberTile label="收藏岗位" value={Number(users.saved_total || 0)} detail={`今日新增 ${formatCount(users.saved_today)} 次`} icon={Heartbeat} tone="muted" />
                <HeroNumberTile label="投递记录" value={Number(users.applied_total || 0)} detail={`今日新增 ${formatCount(users.applied_today)} 次`} icon={PaperPlaneTilt} tone="muted" />
              </>
            ) : (
              <ErrorPanel label="用户操作统计" />
            )}
          </BusinessPanel>

          <BusinessPanel title="待办" icon={ShieldCheck}>
            {resume ? (
              <HeroNumberTile
                label="今日简历解析"
                value={Number(resume.started || 0)}
                detail={`成功率 ${displayEmptyRate(formatPercent(resume.succeeded, resume.started))}；智能 / 规则 ${formatCount(resume.llm)} / ${formatCount(resume.rule)}`}
                icon={FileText}
                tone="muted"
              />
            ) : (
              <ErrorPanel label="简历解析统计" />
            )}
            <HeroNumberTile
              label="可用职业洞察"
              value={Number(operations.insight?.active_total || 0)}
              detail={`今日新增 ${formatCount(operations.insight?.today_created)} 条`}
              icon={Compass}
              tone="success"
            />
            <HeroNumberTile
              label="待处理申诉"
              value={disputesOpen}
              detail={`历史累计 ${formatCount(operations.insight?.disputes_total)} 条`}
              icon={ShieldCheck}
              tone={disputesOpen > 0 ? "warning" : "muted"}
              warning={disputesOpen > 0}
            />
            <AccumulatingMetric title="洞察抽屉打开率" description="需要先持续记录岗位卡曝光和洞察打开事件，数据稳定后再展示。" />
            <AccumulatingMetric title="零结果搜索率" description="需要先持续记录搜索提交、筛选条件和返回结果数，暂不拿别的日志代替。" />
          </BusinessPanel>
        </div>
      )}
    </Section>
  );
}

export default async function AdminHealthPage() {
  if (!(await isAdmin())) {
    redirect("/");
  }

  const [jobsResult, supabaseResult, clickResult, mustApplyResult, coverageResult, mustApplyFetchResult] = await Promise.allSettled([
    getJobsHealthSnapshot(),
    loadSupabaseHealth(),
    loadClickValidity(),
    loadMustApplyCoverage(),
    loadCoverageSnapshot(),
    getMustApplyFetchCoverage(createServiceClient()),
  ]);

  if (jobsResult.status === "rejected") {
    console.error("[admin-health] jobs snapshot failed:", jobsResult.reason);
  }
  if (supabaseResult.status === "rejected") {
    console.error("[admin-health] supabase snapshot failed:", supabaseResult.reason);
  }
  if (clickResult.status === "rejected") {
    console.error("[admin-health] click validity failed:", clickResult.reason);
  }
  if (mustApplyResult.status === "rejected") {
    console.error("[admin-health] must-apply coverage failed:", mustApplyResult.reason);
  }
  if (coverageResult.status === "rejected") {
    console.error("[admin-health] crawl coverage failed:", coverageResult.reason);
  }
  if (mustApplyFetchResult.status === "rejected") {
    console.error("[admin-health] must-apply fetch coverage failed:", mustApplyFetchResult.reason);
  }

  const jobs = jobsResult.status === "fulfilled" ? jobsResult.value : null;
  const operations = supabaseResult.status === "fulfilled" ? supabaseResult.value : null;
  const clickValidity = clickResult.status === "fulfilled" ? clickResult.value : null;
  const mustApply = mustApplyResult.status === "fulfilled" ? mustApplyResult.value : null;
  const coverage = coverageResult.status === "fulfilled" ? coverageResult.value : null;
  const mustApplyFetchCoverage = mustApplyFetchResult.status === "fulfilled" ? mustApplyFetchResult.value : null;
  const crawlSources = normalizeCrawlSources(operations?.crawl_sources);
  const reports = buildDailyReports({
    crawl: operations?.today?.crawl || null,
    discovery: operations?.today?.discovery || null,
    insight: { today_created: operations?.insight?.today_created },
    opsRuns: operations?.today?.ops_runs || [],
  });
  const deadReport = reports.find((report) => report.key === "dead_jobs");
  const todayRemoved = deadReport?.metrics.find((metric) => metric.label === "判死")?.value ?? null;
  const users = operations?.today?.users || null;
  const resume = operations?.today?.resume || null;
  const refreshedAt = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date());

  const mustTotal = mustApply?.length ?? MUST_APPLY_LIST.length;
  const maRows = mustApply || [];
  const maHealthy = maRows.filter((r) => r.healthy > 0).length;
  const maGapRows = maRows.filter((r) => r.healthy === 0);
  const maBlindRows = maRows.filter((r) => r.healthy > 0 && r.checked72h === 0);
  const maGaps = maGapRows.length;
  const maBlind = maBlindRows.length;
  const health = evaluateCombinedHealth({
    validActive: jobs?.validActive,
    crawlRuns: operations?.today?.crawl?.runs,
    crawlFailedRuns: operations?.today?.crawl?.failed_runs,
    clickProbeValidityRate: clickValidity?.probeValidityRate,
    mustApplyHealthyCompanies: mustApply ? maHealthy : null,
    mustApplyTotalCompanies: mustTotal,
    mustApplyZeroHealthyCompanies: maGapRows.map((r) => r.name),
    mustApplyBlindCompanies: maBlindRows.map((r) => r.name),
    coverageAvgPct: coverage?.avgCoveragePct,
    coverageBlindSources: coverage?.blind,
  });
  const mustApplySummary = !mustApply
    ? "必投清单数据暂不可用"
    : `${maHealthy}/${mustTotal} 家有健康岗` + (maGaps ? ` · ${maGaps} 家零健康岗` : "") + (maBlind ? ` · ${maBlind} 家 72h 未核验` : "");

  const failedReports = reports.filter((r) => r.status === "failed").length;
  const ranReports = reports.filter((r) => r.status === "success").length;
  const reportsStatus: SectionStatus = !operations ? "idle" : failedReports > 0 ? "critical" : ranReports === 0 ? "idle" : "ok";
  const reportsSummary = !operations
    ? "战报数据暂不可用"
    : `${ranReports}/${reports.length} 个模块今天已跑` + (failedReports ? ` · ${failedReports} 个失败` : "");

  const coverageHasData =
    !!coverage &&
    (coverage.measurable > 0 || coverage.avgCoveragePct != null || coverage.underCount > 0 || coverage.blind > 0);
  const coverageUnder = coverage?.underCount ?? 0;
  const coverageStatus = !coverage || !coverageHasData ? "idle" : sectionStatusFromBand(coverageBand(coverage.avgCoveragePct));
  const coverageSummary = !coverageHasData
    ? "抓全率数据积累中"
    : (coverage!.avgCoveragePct != null ? `平均抓全率 ${coverage!.avgCoveragePct}%` : "抓全率积累中") +
      (coverageUnder > 0 ? ` · ${coverageUnder} 家抓不全` : "");

  const validActiveShareBand = jobs
    ? band(share(jobs.validActive, jobs.activeTotal), HEALTH_THRESHOLDS.validActiveShare, "higher")
    : "empty";
  const thinShareBand = jobs
    ? band(share(jobs.thinActive, jobs.activeTotal), HEALTH_THRESHOLDS.thinActiveShare, "lower")
    : "empty";
  const neverCheckedShareBand = jobs
    ? band(share(jobs.neverChecked, jobs.activeTotal), HEALTH_THRESHOLDS.neverCheckedShare, "lower")
    : "empty";
  const jobsQualityBand = worstBand([validActiveShareBand, thinShareBand, neverCheckedShareBand]);
  const jobsStatus = !jobs ? "idle" : sectionStatusFromBand(jobsQualityBand);
  const jobsSummary = !jobs
    ? "岗位库数据暂不可用"
    : `在招 ${formatCount(jobs.activeTotal)} · 空壳 ${formatCount(jobs.thinActive)} · 待核查 ${formatCount(jobs.neverChecked)}`;

  let clickStatus: SectionStatus;
  let clickSummary: string;
  if (!clickValidity) {
    clickStatus = "idle";
    clickSummary = "点击有效率数据暂不可用";
  } else if (clickValidity.totalOpens === 0 && clickValidity.livenessTotal === 0) {
    clickStatus = "idle";
    clickSummary = "点击有效率积累中";
  } else {
    clickStatus = sectionStatusFromBand(health.bands.clickValidity);
    clickSummary = `点开仍在招 ${formatRate(clickValidity.probeValidityRate)} · 核验覆盖 ${formatRate(clickValidity.coverageRate)}`;
  }

  const bizStatus: SectionStatus = !operations || !users ? "idle" : "ok";
  const bizSummary =
    !operations || !users
      ? "用户数据暂不可用"
      : `${formatCount(users.total_users)} 用户 · 今日新增 ${formatCount(users.today_users)} · 投递 ${formatCount(users.applied_total)}`;

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-6xl">
        <ProductHero
          eyebrow="今日健康"
          title={`今天：${health.label}`}
          description="先看核心承诺有没有破：必投公司有没有健康岗、用户点开是否还在招、今天后台任务有没有正常跑。所有数字都来自真实数据库；没有可靠来源的项目会明确标为暂无数据或积累中。"
          icon={Pulse}
        >
          <HealthHeroVisual
            health={health}
            refreshedAt={refreshedAt}
            mustApply={mustApply}
            mustTotal={mustTotal}
            maHealthy={maHealthy}
            clickValidity={clickValidity}
            coverage={coverage}
          />
        </ProductHero>

        <div className="mt-6 grid gap-4">
          <MustApplySection
            rows={mustApply}
            fetchCoverage={mustApplyFetchCoverage}
            healthBand={health.bands.mustApply}
            summary={mustApplySummary}
          />

          <ClickValiditySection clickValidity={clickValidity} status={clickStatus} summary={clickSummary} />

          <JobsLibrarySection
            jobs={jobs}
            operations={operations}
            crawlSources={crawlSources}
            todayRemoved={todayRemoved}
            jobsStatus={jobsStatus}
            jobsSummary={jobsSummary}
            validActiveShareBand={validActiveShareBand}
            thinShareBand={thinShareBand}
            neverCheckedShareBand={neverCheckedShareBand}
          />

          <CoverageSection
            snapshot={coverage}
            status={coverageStatus}
            summary={coverageSummary}
            defaultOpen={coverageStatus === "critical"}
          />

          <DailyReportsSection
            operations={operations}
            reports={reports}
            reportsStatus={reportsStatus}
            reportsSummary={reportsSummary}
          />

          <BusinessSection
            operations={operations}
            users={users}
            resume={resume}
            bizStatus={bizStatus}
            bizSummary={bizSummary}
          />

          <div className="flex items-center gap-2 px-1 text-xs text-[#8a8275] dark:text-[#9a9184]">
            <ShieldCheck size={15} weight="fill" aria-hidden="true" />
            该页面仅管理员可访问；两套数据库分别读取，任一侧异常时另一侧仍可显示。
          </div>
        </div>
      </ProductPage>
    </div>
  );
}

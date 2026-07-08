import Navbar from "@/components/Navbar";
import { MetricTile, ProductHero, ProductPage } from "@/components/ProductChrome";
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
  type HealthBand,
  type MustApplyFetchCoverage,
  type MustApplyFetchCoverageCompany,
  type OpsRunAggregateRow,
  type TodayCrawlRow,
  type TodayDiscoveryRow,
} from "@/lib/admin-health";
import { isAdmin } from "@/lib/auth";
import { getJobsHealthSnapshot, getMustApplyCoverage, type MustApplyCoverageRow } from "@/lib/jobs-store/read";
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

const BAND_PANEL_CLASS: Record<ReturnType<typeof bandTone>, string> = {
  danger: "border-[#e0b4ac] bg-[#f7e6e1] dark:border-[#7a392e]/60 dark:bg-[#3a201a]",
  warning: "border-[#edc995] bg-[#fbecd7] dark:border-[#825d28]/60 dark:bg-[#392a17]",
  success: "border-[#c8dda9] bg-[#edf6df] dark:border-[#5d793d]/60 dark:bg-[#203018]",
  muted: "border-black/[0.06] bg-white/45 dark:border-white/10 dark:bg-white/[0.03]",
};

function bandChipClass(value: HealthBand | "neutral"): string {
  return value === "neutral" ? BAND_CHIP_CLASS.muted : BAND_CHIP_CLASS[bandTone(value)];
}

function bandPanelClass(value: HealthBand): string {
  return BAND_PANEL_CLASS[bandTone(value)];
}

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

function formatWholePercent(value: number | null): string {
  return value == null ? "积累中" : `${value}%`;
}

function displayEmptyRate(value: string): string {
  return value === "—" ? "暂无数据" : value;
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

function mustApplyCoverageTextClass(value: number | null): string {
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

function RatioCard({
  label,
  value,
  detail,
  tone = "good",
}: {
  label: string;
  value: string;
  detail: string;
  tone?: HealthBand | "neutral";
}) {
  const isMuted = tone === "empty" || tone === "neutral";
  return (
    <div className="surface-soft p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-[#3f3a33] dark:text-[#d9d0c2]">{label}</p>
        <span className={`rounded-full px-2.5 py-1 ${isMuted ? "text-[11px]" : "text-xs"} font-semibold tabular-nums ${bandChipClass(tone)}`}>
          {value}
        </span>
      </div>
      <p className="mt-3 text-pretty text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">{detail}</p>
    </div>
  );
}

function BusinessMetric({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string;
  value: number | string;
  detail: string;
  icon: ComponentType<any>;
}) {
  return (
    <div className="surface-soft p-4">
      <div className="flex items-center gap-2 text-[#6b655a] dark:text-[#b6ad9d]">
        <Icon size={17} weight="fill" aria-hidden="true" />
        <p className="text-xs font-medium">{label}</p>
      </div>
      <p className="mt-3 text-2xl font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">{value}</p>
      <p className="mt-2 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">{detail}</p>
    </div>
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
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricTile label="可测源数" value={snapshot.measurable} icon={Database} tone="sky" />
            <MetricTile
              label="平均抓全率"
              value={formatWholePercent(snapshot.avgCoveragePct)}
              icon={ChartBar}
              tone={
                snapshot.avgCoveragePct == null
                  ? "muted"
                  : coverageBand(snapshot.avgCoveragePct) === "bad" || coverageBand(snapshot.avgCoveragePct) === "warn"
                    ? "orange"
                    : "lime"
              }
            />
            <MetricTile label="抓不全源数（<90%）" value={snapshot.underCount} icon={Bug} tone="orange" />
            <MetricTile label="盲区源数" value={snapshot.blind} icon={MagnifyingGlass} tone="muted" />
          </div>
          <p className="mt-3 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
            盲区=官网接口不报总数，算不出，非抓漏。
          </p>

          <div className="mt-5">
            {snapshot.underSources.length === 0 ? (
              <p className="rounded-2xl border border-dashed border-black/10 bg-white/35 px-4 py-5 text-sm text-[#8a8275] dark:border-white/10 dark:bg-white/[0.03] dark:text-[#9a9184]">
                暂无抓全率低于 90% 的公司。
              </p>
            ) : (
              <div className="overflow-x-auto rounded-2xl border border-black/[0.07] dark:border-white/[0.1]">
                <table className="w-full min-w-[620px] text-left text-sm">
                  <thead className="bg-[#f4efe6] text-xs text-[#8a8275] dark:bg-[#1c1813] dark:text-[#9a9184]">
                    <tr>
                      <th className="px-4 py-3 font-medium">公司</th>
                      <th className="px-4 py-3 text-right font-medium">官网总数</th>
                      <th className="px-4 py-3 text-right font-medium">我们抓到</th>
                      <th className="px-4 py-3 text-right font-medium">抓全率%</th>
                      <th className="px-4 py-3 text-right font-medium">上次抓取</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.underSources.map((source) => (
                      <tr
                        key={`${source.company}-${source.adapter}-${source.lastRunAt || "none"}`}
                        className="border-t border-black/[0.05] text-[#3f3a33] dark:border-white/[0.08] dark:text-[#d9d0c2]"
                      >
                        <td className="max-w-80 px-4 py-3 font-medium">
                          <span className="block truncate">{source.company}</span>
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">{formatCount(source.reportedTotal)}</td>
                        <td className="px-4 py-3 text-right tabular-nums">{formatCount(source.fetched)}</td>
                        <td className={`px-4 py-3 text-right tabular-nums ${coverageTextClass(source.coveragePct)}`}>
                          {source.coveragePct == null ? "算不出" : `${source.coveragePct}%`}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-[#6b655a] dark:text-[#b6ad9d]">
                          {formatRunDateTime(source.lastRunAt)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
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

  return (
    <div className="mt-5 border-t border-black/[0.06] pt-5 dark:border-white/[0.08]">
      {/* 频率分层（高价值源提频）待线上抓全率数据积累后按数据决定，暂不实现。 */}
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
          <div className="grid gap-3 sm:grid-cols-3">
            <RatioCard
              label="抓全家数"
              value={`${coverage.fullyFetched}/${total}`}
              detail="抓全率 ≥90% 的公司数（含盲区无法计算的公司）；漏抓信号看右侧「平均抓全率」与下方明细。"
              tone="neutral"
            />
            <RatioCard
              label="平均抓全率"
              value={coverage.avgPct == null ? "暂无数据" : `${coverage.avgPct}%`}
              detail="只用官网报了总数的公司计算。"
              tone={coverageBand(coverage.avgPct)}
            />
            <RatioCard
              label="盲区(算不出)"
              value={formatCount(coverage.blind)}
              detail="官网不报总数，暂时算不出抓全率；这不是抓漏。"
              tone="neutral"
            />
          </div>

          {coverage.measurable === 0 ? (
            <p className="mt-4 rounded-2xl border border-dashed border-black/10 bg-white/35 px-4 py-5 text-sm text-[#8a8275] dark:border-white/10 dark:bg-white/[0.03] dark:text-[#9a9184]">
              必投清单还没有可计算官网总数的数据，等下一轮抓取填入后展示明细。
            </p>
          ) : leaking.length === 0 ? (
            <p className="mt-4 rounded-2xl border border-dashed border-black/10 bg-white/35 px-4 py-5 text-sm text-[#8a8275] dark:border-white/10 dark:bg-white/[0.03] dark:text-[#9a9184]">
              暂无抓全率低于 90% 的必投公司。
            </p>
          ) : (
            <div className="mt-4 overflow-x-auto rounded-2xl border border-black/[0.07] dark:border-white/[0.1]">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead className="bg-[#f4efe6] text-xs text-[#8a8275] dark:bg-[#1c1813] dark:text-[#9a9184]">
                  <tr>
                    <th className="px-4 py-3 font-medium">公司</th>
                    <th className="px-4 py-3 text-right font-medium">官网总数</th>
                    <th className="px-4 py-3 text-right font-medium">我们抓到</th>
                    <th className="px-4 py-3 text-right font-medium">抓全率%</th>
                  </tr>
                </thead>
                <tbody>
                  {leaking.map((company) => (
                    <tr
                      key={company.pattern || company.name}
                      className="border-t border-black/[0.05] text-[#3f3a33] dark:border-white/[0.08] dark:text-[#d9d0c2]"
                    >
                      <td className="max-w-80 px-4 py-3 font-medium">
                        <span className="block truncate">{company.name}</span>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">{formatCount(company.reportedTotal)}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{formatCount(company.fetched)}</td>
                      <td className={`px-4 py-3 text-right tabular-nums ${mustApplyCoverageTextClass(company.coveragePct)}`}>
                        {company.coveragePct}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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

      {(gaps.length > 0 || blind.length > 0) && (
        <div className="mb-4 space-y-2 text-sm leading-6">
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

      <div className="grid gap-3 lg:grid-cols-[1.25fr_1fr_1fr]">
        <div className={`rounded-2xl border p-5 ${bandPanelClass(healthBand)}`}>
          <p className="text-sm font-medium text-[#3f3a33] dark:text-[#d9d0c2]">必投健康覆盖</p>
          <p className="mt-3 text-4xl font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">
            {healthyCount}/{n}
          </p>
          <p className="mt-2 text-xs leading-5 text-[#6b655a] dark:text-[#b6ad9d]">
            目标 ≥{HEALTH_THRESHOLDS.mustApplyHealthyCompanies.good}/30；24-27 家为注意，低于 24 家为出事。
          </p>
        </div>
        <RatioCard
          label="近 7 天有新岗"
          value={`${freshCount}/${n}`}
          detail="7 天内有新岗入库；这是活水信号，不当作健康判定阈值。"
          tone="neutral"
        />
        <RatioCard
          label="72h 内核验过"
          value={`${checkedCount}/${n}`}
          detail="3 天内至少一个岗被复核；有健康岗但没复核的公司会在上方点名。"
          tone={blind.length > 0 ? "warn" : "good"}
        />
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="border-b border-black/[0.08] text-left text-xs text-[#8a8275] dark:border-white/[0.1] dark:text-[#9a9184]">
              <th className="py-2 pr-3 font-medium">公司</th>
              <th className="py-2 pr-3 font-medium">健康岗</th>
              <th className="py-2 pr-3 font-medium">近 7 天新岗</th>
              <th className="py-2 pr-3 font-medium">72h 核验岗</th>
              <th className="py-2 font-medium">源状态</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className="border-b border-black/[0.04] dark:border-white/[0.06]">
                <td className="py-2 pr-3 font-medium text-[#1a1714] dark:text-[#f3ecdf]">{r.name}</td>
                <td className={`py-2 pr-3 tabular-nums ${r.healthy === 0 ? "font-semibold text-[#9c4a3c] dark:text-[#e6a99f]" : "text-[#3f3a33] dark:text-[#d9d0c2]"}`}>
                  {formatCount(r.healthy)}
                </td>
                <td className="py-2 pr-3 tabular-nums text-[#3f3a33] dark:text-[#d9d0c2]">{formatCount(r.new7d)}</td>
                <td className={`py-2 pr-3 tabular-nums ${r.healthy > 0 && r.checked72h === 0 ? "font-semibold text-[#8f6225] dark:text-[#e0b15a]" : "text-[#3f3a33] dark:text-[#d9d0c2]"}`}>
                  {formatCount(r.checked72h)}
                </td>
                <td className="py-2 text-xs">
                  {r.hasSource ? (
                    r.sourceEnabled ? (
                      <span className="text-[#5a7a2f] dark:text-[#a3d06a]">已接入</span>
                    ) : (
                      <span className="text-[#9c4a3c] dark:text-[#e6a99f]">源已禁用</span>
                    )
                  ) : (
                    <span className="text-[#9c4a3c] dark:text-[#e6a99f]">从未接入</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <MustApplyFetchCoverageBlock coverage={fetchCoverage} />
    </section>
  );
}

function VerdictBlock({ health, refreshedAt }: { health: CombinedHealthVerdict; refreshedAt: string }) {
  const status: SectionStatus =
    health.level === "critical" ? "critical" : health.level === "warning" ? "warn" : "ok";
  const meta = STATUS_META[status];
  return (
    <div className={`rounded-2xl border px-4 py-4 ${meta.chip}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-[#1a1714] dark:text-[#f3ecdf]">先看这几项</p>
          <p className="mt-1 text-xs leading-5 text-[#6b655a] dark:text-[#b6ad9d]">{health.message}</p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${meta.badge}`}>{meta.label}</span>
      </div>
      <div className="mt-3 space-y-2">
        {health.actions.map((action) => (
          <p key={action} className="rounded-xl bg-white/45 px-3 py-2 text-sm leading-5 text-[#3f3a33] dark:bg-white/[0.04] dark:text-[#d9d0c2]">
            {action}
          </p>
        ))}
      </div>
      <p className="mt-3 text-[11px] text-[#8a8275] dark:text-[#9a9184]">
        页面生成时间：<span className="tabular-nums">{refreshedAt}</span> 北京时间
      </p>
    </div>
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
      ) : clickValidity.totalOpens === 0 && clickValidity.livenessTotal === 0 ? (
        <AccumulatingMetric
          title="点击有效率"
          description="还没有可用点击核验事件，等事件持续写入后再判断。"
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <RatioCard
              label="点开仍在招"
              value={formatRate(clickValidity.probeValidityRate)}
              detail={`能直接核验的点击中，岗位仍在招的比例；目标 ≥99%。样本 ${formatCount(clickValidity.alive + clickValidity.dead)}。`}
              tone={band(clickValidity.probeValidityRate, HEALTH_THRESHOLDS.clickValidity, "higher")}
            />
            <RatioCard
              label="点击核验覆盖"
              value={formatRate(clickValidity.coverageRate)}
              detail={`有核验结果的点击 / 总点击 ${formatCount(clickValidity.totalOpens)}。覆盖低时，核心比例代表性不足。`}
              tone={clickValidity.coverageRate == null ? "empty" : "neutral"}
            />
            <RatioCard
              label="探不动占比"
              value={formatRate(clickValidity.unknownRate)}
              detail={`探不动 / 总核验 ${formatCount(clickValidity.livenessTotal)}；这部分需要后台审计兜底。`}
              tone={clickValidity.unknownRate == null ? "empty" : "neutral"}
            />
            <RatioCard
              label="SPA 源死岗抽检率"
              value="暂无数据"
              detail="飞书、Moka、北森等不可探源的真实死岗比例还未接入审计抽样。"
              tone="empty"
            />
          </div>
          {clickValidity.byAdapter.length > 0 && (
            <div className="mt-5 overflow-auto rounded-2xl border border-black/[0.07] dark:border-white/[0.1]">
              <table className="w-full min-w-[480px] text-left text-sm">
                <caption className="caption-bottom px-4 py-3 text-left text-xs text-[#8a8275] dark:text-[#9a9184]">
                  按技术来源拆开，来源名保留原始 adapter，方便工程定位。
                </caption>
                <thead className="bg-[#f4efe6] text-xs text-[#8a8275] dark:bg-[#1c1813] dark:text-[#9a9184]">
                  <tr>
                    <th className="px-4 py-3 font-medium">来源</th>
                    <th className="px-4 py-3 text-right font-medium">仍在招</th>
                    <th className="px-4 py-3 text-right font-medium">已关闭</th>
                    <th className="px-4 py-3 text-right font-medium">探不动</th>
                    <th className="px-4 py-3 text-right font-medium">点开仍在招</th>
                  </tr>
                </thead>
                <tbody>
                  {clickValidity.byAdapter.map((a) => (
                    <tr
                      key={a.adapter}
                      className="border-t border-black/[0.05] text-[#3f3a33] dark:border-white/[0.08] dark:text-[#d9d0c2]"
                    >
                      <td className="px-4 py-3 font-medium">{a.adapter}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{a.alive}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{a.dead}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{a.unknown}</td>
                      <td className={`px-4 py-3 text-right tabular-nums ${bandTextClass(band(a.validityRate, HEALTH_THRESHOLDS.clickValidity, "higher"))}`}>
                        {formatRate(a.validityRate)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
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
          action={
            <div className="surface-soft min-w-44 px-4 py-3">
              <p className="text-xs text-[#8a8275] dark:text-[#9a9184]">趋势基线</p>
              <p className="mt-1 text-sm font-semibold text-[#3f3a33] dark:text-[#d9d0c2]">积累中</p>
              <p className="mt-0.5 text-[11px] text-[#9a9184] dark:text-[#837c70]">快照指标不造昨日对比</p>
            </div>
          }
        >
          <VerdictBlock health={health} refreshedAt={refreshedAt} />
        </ProductHero>

        <div className="mt-6 grid gap-4">
          <MustApplySection
            rows={mustApply}
            fetchCoverage={mustApplyFetchCoverage}
            healthBand={health.bands.mustApply}
            summary={mustApplySummary}
          />

          <ClickValiditySection clickValidity={clickValidity} status={clickStatus} summary={clickSummary} />

          <Section
            title="各模块每日战报"
            description="每张卡只回答三件事：今天处理了多少、有没有跑、上次什么时候跑。"
            status={reportsStatus}
            summary={reportsSummary}
            defaultOpen={reportsStatus === "critical"}
          >
            {!operations ? (
              <ErrorPanel label="每日战报" />
            ) : (
              <div className="grid gap-3 lg:grid-cols-2">
                {reports.map((report) => (
                  <OperationCard key={report.key} report={report} />
                ))}
              </div>
            )}
          </Section>

          <Section
            title="岗位库体检"
            description="看岗位构成、空壳岗和待核查量；招聘源按近 7 天实际运行结果计算成功率。"
            status={jobsStatus}
            summary={jobsSummary}
            defaultOpen={false}
          >
            {!jobs ? (
              <ErrorPanel label="岗位库体检" />
            ) : (
              <>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  <RatioCard
                    label="能投岗位（库存）"
                    value={formatCount(jobs.validActive)}
                    detail={`占在招 ${displayEmptyRate(formatPercent(jobs.validActive, jobs.activeTotal))}；这是库存背景，不是今天健康结论。`}
                    tone={validActiveShareBand}
                  />
                  <RatioCard
                    label="今日新进"
                    value={formatCount(jobs.todayNew)}
                    detail="今天新入库的岗位，是真实日增量。"
                    tone="neutral"
                  />
                  <RatioCard
                    label={translateOperationalTerm("today_removed")}
                    value={todayRemoved == null ? "暂无数据" : formatCount(todayRemoved)}
                    detail="今天新判定失效的岗位，来自每日死岗治理记录。"
                    tone={todayRemoved == null ? "empty" : "neutral"}
                  />
                  <RatioCard
                    label={translateOperationalTerm("expired")}
                    value={formatCount(jobs.expired)}
                    detail="探活确认永久移除，属于正常治理结果，不因非零自动报警。"
                    tone="neutral"
                  />
                  <RatioCard
                    label={translateOperationalTerm("removed")}
                    value={formatCount(jobs.removed)}
                    detail="疑似下线，后续再次出现时可以恢复；这是信息项。"
                    tone="neutral"
                  />
                  <RatioCard
                    label={`${translateOperationalTerm("thin_active")}占在招`}
                    value={displayEmptyRate(formatPercent(jobs.thinActive, jobs.activeTotal))}
                    detail={`${formatCount(jobs.thinActive)} 条职位描述不足 60 字，不计入能投岗位。`}
                    tone={thinShareBand}
                  />
                  <RatioCard
                    label={`${translateOperationalTerm("never_checked")}占在招`}
                    value={displayEmptyRate(formatPercent(jobs.neverChecked, jobs.activeTotal))}
                    detail={`${formatCount(jobs.neverChecked)} 条还没有完成过在招核查。`}
                    tone={neverCheckedShareBand}
                  />
                </div>
                <p className="mt-3 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
                  今日下架（今天新判定失效） · 已确认撤岗（探活确认永久移除） · 暂时下线（疑似下线，可能恢复） · 空壳岗（有链接但没岗位正文，质量差） · 待核查（还没探活验证）
                </p>
              </>
            )}

            <div className="mt-5 border-t border-black/[0.06] pt-5 dark:border-white/[0.08]">
              <div className="mb-3">
                <h3 className="font-semibold text-[#1a1714] dark:text-[#f3ecdf]">招聘源近 7 天表现</h3>
                <p className="mt-1 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
                  成功率按完成、部分完成、失败三类运行计算；没运行过的招聘源显示“暂无数据”。
                </p>
              </div>
              {!operations ? (
                <ErrorPanel label="招聘源统计" />
              ) : crawlSources.length === 0 ? (
                <p className="text-sm text-[#8a8275] dark:text-[#9a9184]">暂无启用的招聘源。</p>
              ) : (
                <div className="max-h-[34rem] overflow-auto rounded-2xl border border-black/[0.07] dark:border-white/[0.1]">
                  <table className="w-full min-w-[620px] text-left text-sm">
                    <thead className="sticky top-0 z-10 bg-[#f4efe6] text-xs text-[#8a8275] dark:bg-[#1c1813] dark:text-[#9a9184]">
                      <tr>
                        <th className="px-4 py-3 font-medium">公司</th>
                        <th className="px-4 py-3 text-right font-medium">运行次数</th>
                        <th className="px-4 py-3 text-right font-medium">成功率</th>
                        <th className="px-4 py-3 text-right font-medium">部分完成</th>
                        <th className="px-4 py-3 text-right font-medium">失败 / 跳过</th>
                      </tr>
                    </thead>
                    <tbody>
                      {crawlSources.map((source) => (
                        <tr
                          key={source.sourceId}
                          className="border-t border-black/[0.05] text-[#3f3a33] dark:border-white/[0.08] dark:text-[#d9d0c2]"
                        >
                          <td className="max-w-80 px-4 py-3">
                            <p className="truncate font-medium">{source.company}</p>
                            <p className="mt-0.5 truncate text-[11px] text-[#9a9184] dark:text-[#837c70]">
                              {source.adapterName}
                            </p>
                          </td>
                          <td className="px-4 py-3 text-right tabular-nums">{source.runs}</td>
                          <td className={`px-4 py-3 text-right tabular-nums ${source.successRate === "—" ? "text-[#8a8275] dark:text-[#9a9184]" : "font-semibold"}`}>
                            {displayEmptyRate(source.successRate)}
                          </td>
                          <td className={`px-4 py-3 text-right tabular-nums ${source.partialRate === "—" ? "text-[#8a8275] dark:text-[#9a9184]" : ""}`}>
                            {displayEmptyRate(source.partialRate)}
                          </td>
                          <td className="px-4 py-3 text-right tabular-nums">
                            <span className={source.failed > 0 ? "font-semibold text-[#9c4a3c] dark:text-[#e6a99f]" : ""}>
                              {source.failed}
                            </span>
                            <span className="text-[#9a9184] dark:text-[#837c70]"> / {source.skipped}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </Section>

          <CoverageSection
            snapshot={coverage}
            status={coverageStatus}
            summary={coverageSummary}
            defaultOpen={coverageStatus === "critical" || coverageStatus === "warn"}
          />

          <Section
            title="用户与业务"
            description="用户、求职偏好、收藏投递、简历解析和职业洞察均使用现有真实数据。"
            status={bizStatus}
            summary={bizSummary}
            defaultOpen={false}
          >
            {!operations ? (
              <ErrorPanel label="用户与业务统计" />
            ) : (
              <div className="grid gap-6 lg:grid-cols-3">
                <div>
                  <h3 className="text-sm font-semibold text-[#1a1714] dark:text-[#f3ecdf]">增长</h3>
                  <div className="mt-3 grid gap-3">
                    {users ? (
                      <>
                        <BusinessMetric
                          label="总用户数"
                          value={formatCount(users.total_users)}
                          detail="当前累计注册用户"
                          icon={Users}
                        />
                        <BusinessMetric
                          label="今日新增用户"
                          value={formatCount(users.today_users)}
                          detail="真实日增量，不展示伪趋势"
                          icon={UserCircle}
                        />
                      </>
                    ) : (
                      <ErrorPanel label="用户统计" />
                    )}
                    <AccumulatingMetric title="趋势基线" description="用户、覆盖、库存都是快照指标，历史基线还在积累中。" />
                  </div>
                </div>

                <div>
                  <h3 className="text-sm font-semibold text-[#1a1714] dark:text-[#f3ecdf]">参与</h3>
                  <div className="mt-3 grid gap-3">
                    {users ? (
                      <>
                        <BusinessMetric
                          label="设了求职偏好"
                          value={formatCount(users.users_with_preferences)}
                          detail="已保存目标岗位、城市或关键词的用户"
                          icon={UserCircle}
                        />
                        <BusinessMetric
                          label="收藏岗位"
                          value={formatCount(users.saved_total)}
                          detail={`今日新增 ${formatCount(users.saved_today)} 次`}
                          icon={ChartBar}
                        />
                        <BusinessMetric
                          label="投递记录"
                          value={formatCount(users.applied_total)}
                          detail={`今日新增 ${formatCount(users.applied_today)} 次`}
                          icon={PaperPlaneTilt}
                        />
                      </>
                    ) : (
                      <ErrorPanel label="用户操作统计" />
                    )}
                  </div>
                </div>

                <div>
                  <h3 className="text-sm font-semibold text-[#1a1714] dark:text-[#f3ecdf]">待办</h3>
                  <div className="mt-3 grid gap-3">
                    {resume ? (
                      <BusinessMetric
                        label="今日简历解析"
                        value={formatCount(resume.started)}
                        detail={`成功率 ${displayEmptyRate(formatPercent(resume.succeeded, resume.started))}；智能 / 规则 ${formatCount(resume.llm)} / ${formatCount(resume.rule)}`}
                        icon={FileText}
                      />
                    ) : (
                      <ErrorPanel label="简历解析统计" />
                    )}
                    <BusinessMetric
                      label="可用职业洞察"
                      value={formatCount(operations.insight?.active_total)}
                      detail={`今日新增 ${formatCount(operations.insight?.today_created)} 条`}
                      icon={Compass}
                    />
                    <BusinessMetric
                      label="待处理申诉"
                      value={formatCount(operations.insight?.disputes_open)}
                      detail={`历史累计 ${formatCount(operations.insight?.disputes_total)} 条`}
                      icon={ShieldCheck}
                    />
                    <AccumulatingMetric
                      title="洞察抽屉打开率"
                      description="需要先持续记录岗位卡曝光和洞察打开事件，数据稳定后再展示。"
                    />
                    <AccumulatingMetric
                      title="零结果搜索率"
                      description="需要先持续记录搜索提交、筛选条件和返回结果数，暂不拿别的日志代替。"
                    />
                  </div>
                </div>
              </div>
            )}
          </Section>

          <div className="flex items-center gap-2 px-1 text-xs text-[#8a8275] dark:text-[#9a9184]">
            <ShieldCheck size={15} weight="fill" aria-hidden="true" />
            该页面仅管理员可访问；两套数据库分别读取，任一侧异常时另一侧仍可显示。
          </div>
        </div>
      </ProductPage>
    </div>
  );
}

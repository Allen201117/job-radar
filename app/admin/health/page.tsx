import Navbar from "@/components/Navbar";
import { MetricTile, ProductHero, ProductPage } from "@/components/ProductChrome";
import {
  buildDailyReports,
  computeClickValidityMetrics,
  evaluateTodayHealth,
  formatPercent,
  normalizeCrawlSources,
  type ClickValidityMetrics,
  type CrawlSourceRow,
  type DailyReport,
  type OpsRunAggregateRow,
  type TodayCrawlRow,
  type TodayDiscoveryRow,
} from "@/lib/admin-health";
import { isAdmin } from "@/lib/auth";
import { getJobsHealthSnapshot, getMustApplyCoverage, type MustApplyCoverageRow } from "@/lib/jobs-store/read";
import { MUST_APPLY_LIST } from "@/lib/must-apply-list";
import { createServiceClient } from "@/lib/supabaseService";
import {
  Briefcase,
  Bug,
  ChartBar,
  CheckCircle,
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

function formatRate(rate: number | null): string {
  return rate == null ? "—" : `${(rate * 100).toFixed(1)}%`;
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="surface p-5 sm:p-6">
      <div className="mb-5">
        <h2 className="text-balance text-xl font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{title}</h2>
        <p className="mt-1 text-pretty text-sm leading-6 text-[#6b655a] dark:text-[#b6ad9d]">{description}</p>
      </div>
      {children}
    </section>
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

const REPORT_ICONS: Record<DailyReport["key"], ComponentType<any>> = {
  crawl: Bug,
  enrichment: FileText,
  dead_jobs: Heartbeat,
  insights: Compass,
  auto_discover: Database,
  discovery: MagnifyingGlass,
};

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
            <p className="text-[11px] text-[#8a8275] dark:text-[#9a9184]">{metric.label}</p>
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
  warning = false,
}: {
  label: string;
  value: string;
  detail: string;
  warning?: boolean;
}) {
  return (
    <div className="surface-soft p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-[#3f3a33] dark:text-[#d9d0c2]">{label}</p>
        <span
          className={
            warning
              ? "rounded-full bg-[#f7e6e1] px-2.5 py-1 text-xs font-semibold tabular-nums text-[#9c4a3c] dark:bg-[#7a392e]/30 dark:text-[#e6a99f]"
              : "rounded-full bg-[#e6f2d3] px-2.5 py-1 text-xs font-semibold tabular-nums text-[#5a7a2f] dark:bg-[#a3d06a]/15 dark:text-[#a3d06a]"
          }
        >
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

// 北极星卡：必投清单健康覆盖。回答「目标用户最想投的头部公司，我们到底罩住了几家」——
// 这是产品对用户承诺的真实覆盖率，掉了要优先修它，别被库存总量的大数字安慰。
function MustApplySection({ rows }: { rows: MustApplyRow[] | null }) {
  if (!rows) {
    return (
      <Section title="北极星 · 必投清单健康覆盖" description="目标用户最常投的头部公司逐家对账。">
        <ErrorPanel label="必投清单覆盖" />
      </Section>
    );
  }
  const n = rows.length;
  const healthyCount = rows.filter((r) => r.healthy > 0).length;
  const freshCount = rows.filter((r) => r.new7d > 0).length;
  const checkedCount = rows.filter((r) => r.checked72h > 0).length;
  const gaps = rows.filter((r) => r.healthy === 0);
  const blind = rows.filter((r) => r.healthy > 0 && r.checked72h === 0);
  return (
    <Section
      title="北极星 · 必投清单健康覆盖"
      description={`目标用户最常投的 ${n} 家头部公司逐家对账：有没有健康岗、近 7 天有没有新岗、72 小时内有没有核验。这是对用户承诺的真实覆盖率——掉了先修它，不看库存总量。清单口径在 lib/must-apply-list.ts。`}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <RatioCard
          label="有健康岗的公司"
          value={`${healthyCount}/${n}`}
          detail="active 且 JD 正文完整（与首页「能投岗位」同口径）。为 0 的 = 用户想投但我们完全没货。"
          warning={healthyCount < n * 0.8}
        />
        <RatioCard
          label="近 7 天有新岗"
          value={`${freshCount}/${n}`}
          detail="7 天内有新岗入库——覆盖是活水还是存量。"
          warning={freshCount < n * 0.7}
        />
        <RatioCard
          label="72h 内核验过"
          value={`${checkedCount}/${n}`}
          detail="3 天内至少一个岗被探活复核——「仍在招」承诺的底气；为 0 的属探活盲区。"
          warning={checkedCount < n * 0.7}
        />
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
              探活盲区（有岗但 72h 未核验）：{blind.map((r) => r.name).join("、")}
            </p>
          )}
        </div>
      )}
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
    </Section>
  );
}

export default async function AdminHealthPage() {
  if (!(await isAdmin())) {
    redirect("/");
  }

  const [jobsResult, supabaseResult, clickResult, mustApplyResult] = await Promise.allSettled([
    getJobsHealthSnapshot(),
    loadSupabaseHealth(),
    loadClickValidity(),
    loadMustApplyCoverage(),
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

  const jobs = jobsResult.status === "fulfilled" ? jobsResult.value : null;
  const operations = supabaseResult.status === "fulfilled" ? supabaseResult.value : null;
  const clickValidity = clickResult.status === "fulfilled" ? clickResult.value : null;
  const mustApply = mustApplyResult.status === "fulfilled" ? mustApplyResult.value : null;
  const crawlSources = normalizeCrawlSources(operations?.crawl_sources);
  const reports = buildDailyReports({
    crawl: operations?.today?.crawl || null,
    discovery: operations?.today?.discovery || null,
    insight: { today_created: operations?.insight?.today_created },
    opsRuns: operations?.today?.ops_runs || [],
  });
  const deadReport = reports.find((report) => report.key === "dead_jobs");
  const todayRemoved = deadReport?.metrics.find((metric) => metric.label === "判死")?.value ?? null;
  const health = jobs
    ? evaluateTodayHealth({
        validActive: jobs.validActive,
        crawlRuns: operations?.today?.crawl?.runs,
        crawlFailedRuns: operations?.today?.crawl?.failed_runs,
      })
    : null;
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

  const healthTone = health?.level === "critical"
    ? "border-[#e0b4ac] bg-[#f7e6e1] text-[#9c4a3c] dark:border-[#7a392e]/60 dark:bg-[#3a201a] dark:text-[#e6a99f]"
    : health?.level === "warning"
      ? "border-[#edc995] bg-[#fbecd7] text-[#8f6225] dark:border-[#825d28]/60 dark:bg-[#392a17] dark:text-[#e0b15a]"
      : "border-[#c8dda9] bg-[#edf6df] text-[#55752e] dark:border-[#5d793d]/60 dark:bg-[#203018] dark:text-[#a3d06a]";

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-6xl">
        <ProductHero
          eyebrow="今日健康"
          title="今天运营得怎么样？"
          description="先看今天有没有正常跑，再看岗位库质量和用户使用情况。所有数字都来自真实数据库；没有可靠来源的项目会明确标为积累中。"
          icon={Pulse}
          action={
            <div className="surface-soft min-w-44 px-4 py-3 text-right">
              <p className="text-xs text-[#8a8275] dark:text-[#9a9184]">页面生成时间</p>
              <p className="mt-1 text-sm font-semibold tabular-nums text-[#3f3a33] dark:text-[#d9d0c2]">
                {refreshedAt}
              </p>
              <p className="mt-0.5 text-[11px] text-[#9a9184] dark:text-[#837c70]">北京时间</p>
            </div>
          }
        >
          {jobs ? (
            <>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <MetricTile label="能投岗位" value={jobs.validActive} icon={Briefcase} tone="white" />
                <MetricTile label="今日新进" value={jobs.todayNew} icon={Database} tone="lime" />
                <MetricTile
                  label="今日下架"
                  value={todayRemoved == null ? "积累中" : todayRemoved}
                  icon={Heartbeat}
                  tone="orange"
                />
                <MetricTile
                  label="有效率"
                  value={formatPercent(jobs.validActive, jobs.activeTotal)}
                  icon={CheckCircle}
                  tone="sky"
                />
              </div>
              {health && (
                <div className={`mt-4 flex items-start gap-3 rounded-2xl border px-4 py-3 ${healthTone}`}>
                  <span className="text-lg" aria-hidden="true">
                    {health.level === "critical" ? "🔴" : health.level === "warning" ? "⚠️" : "✅"}
                  </span>
                  <div>
                    <p className="text-sm font-semibold">今日判断：{health.label}</p>
                    <p className="mt-1 text-xs leading-5 opacity-90">{health.message}</p>
                  </div>
                </div>
              )}
            </>
          ) : (
            <ErrorPanel label="岗位库统计" />
          )}
        </ProductHero>

        <div className="mt-6 grid gap-6">
          <MustApplySection rows={mustApply} />

          <Section
            title="各模块每日战报"
            description="每张卡只回答三件事：今天处理了多少、有没有跑、上次什么时候跑。"
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
          >
            {!jobs ? (
              <ErrorPanel label="岗位库体检" />
            ) : (
              <div className="grid gap-3 sm:grid-cols-3">
                <RatioCard
                  label="在招岗位"
                  value={formatPercent(jobs.activeTotal, jobs.total)}
                  detail={`${formatCount(jobs.activeTotal)} 条当前在招。首页“能投岗位”只取其中有完整职位描述的高质量岗位。`}
                />
                <RatioCard
                  label="已确认撤岗"
                  value={formatPercent(jobs.expired, jobs.total)}
                  detail={`${formatCount(jobs.expired)} 条已确认撤岗，等待清理任务回收。`}
                  warning={jobs.expired > 0}
                />
                <RatioCard
                  label="暂时下线"
                  value={formatPercent(jobs.removed, jobs.total)}
                  detail={`${formatCount(jobs.removed)} 条本轮没抓到，后续再次出现时可以恢复。`}
                  warning={jobs.removed > 0}
                />
                <RatioCard
                  label="空壳岗占在招"
                  value={formatPercent(jobs.thinActive, jobs.activeTotal)}
                  detail={`${formatCount(jobs.thinActive)} 条职位描述不足 60 字，不计入“能投岗位”。`}
                  warning={jobs.thinActive > 0}
                />
                <RatioCard
                  label="待核查占在招"
                  value={formatPercent(jobs.neverChecked, jobs.activeTotal)}
                  detail={`${formatCount(jobs.neverChecked)} 条还没有完成过在招核查，应随每日治理持续下降。`}
                  warning={jobs.neverChecked > 0}
                />
              </div>
            )}

            <div className="mt-5 border-t border-black/[0.06] pt-5 dark:border-white/[0.08]">
              <div className="mb-3">
                <h3 className="font-semibold text-[#1a1714] dark:text-[#f3ecdf]">招聘源近 7 天表现</h3>
                <p className="mt-1 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
                  成功率按完成、部分完成、失败三类运行计算；没运行过的招聘源显示“—”。
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
                          <td className="px-4 py-3 text-right font-semibold tabular-nums">{source.successRate}</td>
                          <td className="px-4 py-3 text-right tabular-nums">{source.partialRate}</td>
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

          <Section
            title="点击有效率（护城河指标）"
            description="用户点开官网那刻，岗位是否还在招。四个数必须一起看——只报「可探源 99%」会偷窄分母（最难的 SPA 不进分母）。"
          >
            {!clickValidity ? (
              <ErrorPanel label="点击有效率" />
            ) : clickValidity.totalOpens === 0 && clickValidity.livenessTotal === 0 ? (
              <AccumulatingMetric
                title="点击有效率"
                description="需要先持续记录用户点开官网（opportunity_official_opened）和点击核验（job_liveness_at_click）事件，数据稳定后展示。"
              />
            ) : (
              <>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <RatioCard
                    label="可探源点击有效率"
                    value={formatRate(clickValidity.probeValidityRate)}
                    detail={`点开后岗位仍在招的比例（仅 wt/hotjob/workday 等可探源；分母排除 unknown）。目标 ≥99%。样本 ${formatCount(clickValidity.alive + clickValidity.dead)}。`}
                    warning={clickValidity.probeValidityRate != null && clickValidity.probeValidityRate < 0.99}
                  />
                  <RatioCard
                    label="点击核验覆盖率"
                    value={formatRate(clickValidity.coverageRate)}
                    detail={`有核验结果的点击 / 总点击 ${formatCount(clickValidity.totalOpens)}。太低说明上面的 99% 没代表性。`}
                    warning={clickValidity.coverageRate != null && clickValidity.coverageRate < 0.5}
                  />
                  <RatioCard
                    label="unknown 占比"
                    value={formatRate(clickValidity.unknownRate)}
                    detail={`探不动（unknown）/ 总核验 ${formatCount(clickValidity.livenessTotal)}。越高说明越多源探不动，靠后台审计兜底。`}
                    warning={clickValidity.unknownRate != null && clickValidity.unknownRate > 0.3}
                  />
                  <RatioCard
                    label="SPA 源死岗抽检率"
                    value="—"
                    detail="不可探源（飞书/Moka/北森等）的真实死岗比例，来自审计抽样，非点击事件——待审计流水线接入。"
                  />
                </div>
                {clickValidity.byAdapter.length > 0 && (
                  <div className="mt-5 overflow-auto rounded-2xl border border-black/[0.07] dark:border-white/[0.1]">
                    <table className="w-full min-w-[480px] text-left text-sm">
                      <thead className="bg-[#f4efe6] text-xs text-[#8a8275] dark:bg-[#1c1813] dark:text-[#9a9184]">
                        <tr>
                          <th className="px-4 py-3 font-medium">来源</th>
                          <th className="px-4 py-3 text-right font-medium">仍在招</th>
                          <th className="px-4 py-3 text-right font-medium">已关闭</th>
                          <th className="px-4 py-3 text-right font-medium">探不动</th>
                          <th className="px-4 py-3 text-right font-medium">有效率</th>
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
                            <td className="px-4 py-3 text-right font-semibold tabular-nums">{formatRate(a.validityRate)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </Section>

          <Section
            title="用户与业务"
            description="用户、求职偏好、收藏投递、简历解析和职业洞察均使用现有真实数据。"
          >
            {!operations ? (
              <ErrorPanel label="用户与业务统计" />
            ) : (
              <>
                {users ? (
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <BusinessMetric
                      label="总用户数"
                      value={formatCount(users.total_users)}
                      detail={`今日新注册 ${formatCount(users.today_users)} 人`}
                      icon={Users}
                    />
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
                  </div>
                ) : (
                  <ErrorPanel label="用户与操作统计" />
                )}

                <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {resume ? (
                    <>
                      <BusinessMetric
                        label="今日简历解析"
                        value={formatCount(resume.started)}
                        detail={`成功率 ${formatPercent(resume.succeeded, resume.started)}`}
                        icon={FileText}
                      />
                      <BusinessMetric
                        label="简历解析方式"
                        value={`${formatCount(resume.llm)} / ${formatCount(resume.rule)}`}
                        detail="智能解析 / 规则解析"
                        icon={CheckCircle}
                      />
                    </>
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
                </div>

                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <AccumulatingMetric
                    title="洞察抽屉打开率"
                    description="需要先持续记录岗位卡曝光和洞察打开事件，数据稳定后再展示。"
                  />
                  <AccumulatingMetric
                    title="零结果搜索率"
                    description="需要先持续记录搜索提交、筛选条件和返回结果数，暂不拿别的日志代替。"
                  />
                </div>
              </>
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

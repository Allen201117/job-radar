import Navbar from "@/components/Navbar";
import { MetricTile, ProductHero, ProductPage } from "@/components/ProductChrome";
import {
  formatPercent,
  normalizeCrawlSources,
  normalizeDiscoveryModes,
  normalizeInsightDimensions,
  type CrawlSourceRow,
  type DiscoveryFailureRow,
  type DiscoveryModeRow,
  type InsightDimensionRow,
} from "@/lib/admin-health";
import { isAdmin } from "@/lib/auth";
import { getJobsHealthSnapshot } from "@/lib/jobs-store/read";
import { createServiceClient } from "@/lib/supabaseService";
import {
  ArrowsClockwise,
  Briefcase,
  Database,
  FileText,
  Pulse,
  ShieldCheck,
} from "@phosphor-icons/react/ssr";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

export const dynamic = "force-dynamic";

type SupabaseHealthSnapshot = {
  window_days?: number;
  crawl_sources?: CrawlSourceRow[];
  discovery_modes?: DiscoveryModeRow[];
  discovery_failures?: DiscoveryFailureRow[];
  insight?: {
    active_total?: number;
    dimensions?: InsightDimensionRow[];
    disputes_total?: number;
    disputes_open?: number;
  };
};

async function loadSupabaseHealth(): Promise<SupabaseHealthSnapshot> {
  const service = createServiceClient();
  const { data, error } = await service.rpc("admin_health_snapshot", { p_window: "7 days" });
  if (error) throw new Error(error.message);
  return (data || {}) as SupabaseHealthSnapshot;
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
        <h2 className="text-balance text-lg font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{title}</h2>
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

function PendingMetric({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-black/10 bg-white/35 p-4 dark:border-white/10 dark:bg-white/[0.03]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-[#3f3a33] dark:text-[#d9d0c2]">{title}</p>
          <p className="mt-2 text-pretty text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">{description}</p>
        </div>
        <span className="shrink-0 rounded-full bg-[#ece7dd] px-2.5 py-1 text-[11px] font-semibold text-[#6b655a] dark:bg-white/[0.08] dark:text-[#b6ad9d]">
          待埋点
        </span>
      </div>
    </div>
  );
}

function formatCount(value: number | undefined): string {
  return Number(value || 0).toLocaleString("zh-CN");
}

export default async function AdminHealthPage() {
  if (!(await isAdmin())) {
    redirect("/");
  }

  const [jobsResult, supabaseResult] = await Promise.allSettled([
    getJobsHealthSnapshot(),
    loadSupabaseHealth(),
  ]);

  if (jobsResult.status === "rejected") {
    console.error("[admin-health] jobs snapshot failed:", jobsResult.reason);
  }
  if (supabaseResult.status === "rejected") {
    console.error("[admin-health] supabase snapshot failed:", supabaseResult.reason);
  }

  const jobs = jobsResult.status === "fulfilled" ? jobsResult.value : null;
  const operations = supabaseResult.status === "fulfilled" ? supabaseResult.value : null;
  const crawlSources = normalizeCrawlSources(operations?.crawl_sources);
  const discoveryModes = normalizeDiscoveryModes(
    operations?.discovery_modes,
    operations?.discovery_failures,
  );
  const insightDimensions = normalizeInsightDimensions(operations?.insight?.dimensions);
  const refreshedAt = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date());

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-6xl">
        <ProductHero
          eyebrow="系统健康"
          title="今天的数据健康吗？"
          description="聚合岗位库、抓取、失活、刷新发现与职业洞察。岗位指标来自香港 PostgreSQL，运营日志与洞察来自 Supabase。"
          icon={Pulse}
          action={
            <div className="surface-soft min-w-44 px-4 py-3 text-right">
              <p className="text-xs text-[#8a8275] dark:text-[#9a9184]">页面生成时间</p>
              <p className="mt-1 text-sm font-semibold tabular-nums text-[#3f3a33] dark:text-[#d9d0c2]">
                {refreshedAt}
              </p>
              <p className="mt-0.5 text-[11px] text-[#9a9184] dark:text-[#837c70]">Asia/Shanghai</p>
            </div>
          }
        >
          {jobs ? (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <MetricTile label="有效在招" value={jobs.validActive} icon={Briefcase} tone="white" />
              <MetricTile label="今日新增" value={jobs.todayNew} icon={Database} tone="lime" />
              <MetricTile label="今日更新" value={jobs.todayUpdated} icon={ArrowsClockwise} tone="sky" />
              <MetricTile
                label="薄卡占 active"
                value={formatPercent(jobs.thinActive, jobs.activeTotal)}
                icon={FileText}
                tone="orange"
              />
            </div>
          ) : (
            <ErrorPanel label="岗位库统计" />
          )}
        </ProductHero>

        <div className="mt-6 grid gap-6">
          <Section
            title="岗位质量与失活"
            description="有效岗位按 JD 正文不少于 60 字计算；今日更新指今天再次抓到、且不是今天首次发现的岗位。"
          >
            {jobs ? (
              <div className="grid gap-3 sm:grid-cols-3">
                <RatioCard
                  label="expired 占全库"
                  value={formatPercent(jobs.expired, jobs.total)}
                  detail={`${formatCount(jobs.expired)} 条已确认撤岗；按现行策略会由清理任务永久删除。`}
                  warning={jobs.expired > 0}
                />
                <RatioCard
                  label="removed 占全库"
                  value={formatPercent(jobs.removed, jobs.total)}
                  detail={`${formatCount(jobs.removed)} 条抓取漏看，可在后续重抓时恢复 active。`}
                  warning={jobs.removed > 0}
                />
                <RatioCard
                  label="active 从未探活"
                  value={formatPercent(jobs.neverChecked, jobs.activeTotal)}
                  detail={`${formatCount(jobs.neverChecked)} 条 enrich_checked_at 仍为空，应随巡检轮转持续下降。`}
                  warning={jobs.neverChecked > 0}
                />
              </div>
            ) : (
              <ErrorPanel label="岗位失活统计" />
            )}
          </Section>

          <Section
            title={`抓取健康 · 近 ${operations?.window_days || 7} 天`}
            description="成功率与 partial 比例的分母为 success + partial_success + failed；skipped 单独展示，不混入成功率。无运行记录的启用源显示“—”。"
          >
            {!operations ? (
              <ErrorPanel label="抓取统计" />
            ) : crawlSources.length === 0 ? (
              <p className="text-sm text-[#8a8275] dark:text-[#9a9184]">暂无启用 source。</p>
            ) : (
              <div className="max-h-[34rem] overflow-auto rounded-2xl border border-black/[0.07] dark:border-white/[0.1]">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <thead className="sticky top-0 z-10 bg-[#f4efe6] text-xs text-[#8a8275] dark:bg-[#1c1813] dark:text-[#9a9184]">
                    <tr>
                      <th className="px-4 py-3 font-medium">Source</th>
                      <th className="px-4 py-3 font-medium">Adapter</th>
                      <th className="px-4 py-3 text-right font-medium">运行</th>
                      <th className="px-4 py-3 text-right font-medium">成功率</th>
                      <th className="px-4 py-3 text-right font-medium">Partial</th>
                      <th className="px-4 py-3 text-right font-medium">失败 / 跳过</th>
                    </tr>
                  </thead>
                  <tbody>
                    {crawlSources.map((source) => (
                      <tr
                        key={source.sourceId}
                        className="border-t border-black/[0.05] text-[#3f3a33] dark:border-white/[0.08] dark:text-[#d9d0c2]"
                      >
                        <td className="max-w-72 truncate px-4 py-3 font-medium">{source.company}</td>
                        <td className="px-4 py-3 font-mono text-xs text-[#6b655a] dark:text-[#b6ad9d]">
                          {source.adapterName}
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
          </Section>

          <Section
            title={`刷新与发现 · 近 ${operations?.window_days || 7} 天`}
            description="平均耗时只计算有完整 started_at / finished_at 的运行；失败原因包含 failed 与 partial_success。"
          >
            {!operations ? (
              <ErrorPanel label="刷新与发现统计" />
            ) : discoveryModes.length === 0 ? (
              <p className="text-sm text-[#8a8275] dark:text-[#9a9184]">近 7 天暂无刷新或发现运行。</p>
            ) : (
              <div className="grid gap-3 lg:grid-cols-2">
                {discoveryModes.map((mode) => (
                  <div key={mode.mode} className="surface-soft p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{mode.label}</p>
                        <p className="mt-1 text-xs text-[#8a8275] dark:text-[#9a9184]">
                          {mode.runs} 次运行 · {mode.completedRuns} 次有完整耗时
                        </p>
                      </div>
                      <div className="rounded-xl bg-[#dbe9fa] px-3 py-2 text-right dark:bg-[#7fb2e8]/15">
                        <p className="text-[11px] text-[#5f7893] dark:text-[#9fc5ed]">平均耗时</p>
                        <p className="mt-0.5 font-semibold tabular-nums text-[#2f6299] dark:text-[#7fb2e8]">
                          {mode.averageDuration}
                        </p>
                      </div>
                    </div>
                    <div className="mt-4 border-t border-black/[0.06] pt-3 dark:border-white/[0.08]">
                      <p className="text-xs font-medium text-[#6b655a] dark:text-[#b6ad9d]">失败原因</p>
                      {mode.failures.length ? (
                        <div className="mt-2 flex flex-wrap gap-2">
                          {mode.failures.map((failure) => (
                            <span
                              key={failure.reason}
                              className="rounded-full bg-[#f7e6e1] px-2.5 py-1 text-xs text-[#9c4a3c] dark:bg-[#7a392e]/30 dark:text-[#e6a99f]"
                            >
                              <span className="font-mono">{failure.reason}</span>
                              <span className="ml-1.5 font-semibold tabular-nums">× {failure.count}</span>
                            </span>
                          ))}
                        </div>
                      ) : (
                        <p className="mt-2 text-xs text-[#8a8275] dark:text-[#9a9184]">暂无失败原因记录。</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Section>

          <Section
            title="职业洞察"
            description="统计当前 active 洞察及申诉队列；维度按洞察表真实枚举展示。"
          >
            {!operations ? (
              <ErrorPanel label="洞察统计" />
            ) : (
              <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
                <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
                  <RatioCard
                    label="Active 洞察"
                    value={formatCount(operations.insight?.active_total)}
                    detail="当前对用户可用的 active 条目。"
                  />
                  <RatioCard
                    label="全部申诉"
                    value={formatCount(operations.insight?.disputes_total)}
                    detail="历史累计提交的申诉。"
                  />
                  <RatioCard
                    label="待处理申诉"
                    value={formatCount(operations.insight?.disputes_open)}
                    detail="status=open，需管理员处理。"
                    warning={Number(operations.insight?.disputes_open || 0) > 0}
                  />
                </div>
                <div className="surface-soft p-4">
                  <p className="text-sm font-medium text-[#3f3a33] dark:text-[#d9d0c2]">Active 洞察按维度</p>
                  {insightDimensions.length ? (
                    <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                      {insightDimensions.map((item) => (
                        <div
                          key={item.dimension}
                          className="rounded-xl border border-black/[0.06] bg-white/55 px-3 py-3 dark:border-white/[0.08] dark:bg-white/[0.04]"
                        >
                          <p className="text-xs text-[#8a8275] dark:text-[#9a9184]">{item.label}</p>
                          <p className="mt-1 text-xl font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">
                            {formatCount(item.count)}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-3 text-sm text-[#8a8275] dark:text-[#9a9184]">暂无 active 洞察。</p>
                  )}
                </div>
              </div>
            )}
          </Section>

          <Section
            title="产品使用指标"
            description="以下指标没有可靠数据来源，不用现有日志勉强推算；任务 4 埋点接入后再替换为真实数字。"
          >
            <div className="grid gap-3 sm:grid-cols-3">
              <PendingMetric
                title="零结果搜索率"
                description="需要记录搜索提交、结果数和筛选上下文。"
              />
              <PendingMetric
                title="洞察抽屉打开率"
                description="需要关联岗位卡曝光与洞察抽屉打开事件。"
              />
              <PendingMetric
                title="简历解析成功率"
                description="需要记录解析请求、成功、失败类型与文件格式。"
              />
            </div>
          </Section>

          <div className="flex items-center gap-2 px-1 text-xs text-[#8a8275] dark:text-[#9a9184]">
            <ShieldCheck size={15} weight="fill" aria-hidden="true" />
            该页面仅管理员可访问；数据查询在服务端执行。
          </div>
        </div>
      </ProductPage>
    </div>
  );
}

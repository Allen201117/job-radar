"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ArrowSquareOut, CircleNotch, Scales, X, XCircle } from "@phosphor-icons/react";
import { recruitmentCategory } from "@/lib/china-keyword-expansion";
import {
  fetchCompanyInsights,
  getCachedInsights,
  type CompanyInsightResponse,
} from "@/lib/insight-client";
import {
  formatHiringSignalChip,
  type InsightChipTone,
} from "@/lib/insight-chip-format";
import { extractDeadline, extractEducation, extractExperience } from "@/lib/job-fields";
import { matchTier } from "@/lib/scoring";
import type { MatchReason, ScoredJob } from "@/lib/types";
import { cleanSummary, cn, freshnessLabel } from "@/lib/utils";

type Props = {
  open: boolean;
  jobs: ScoredJob[];
  hasPreferences: boolean;
  onClose: () => void;
  onRemove: (jobId: string) => void;
};

type InsightState = {
  loading: boolean;
  data: CompanyInsightResponse | null;
};

const MATCH_REASON_LABELS = {
  role: "命中目标方向",
  location: "命中城市",
  keyword: "命中技能",
  company: "命中目标公司",
} satisfies Record<Exclude<MatchReason["type"], "freshness">, string>;

const CHIP_TONE: Record<InsightChipTone, string> = {
  positive: "border-[#a9d8c4] bg-[#dcf2e8] text-[#2f8a63] dark:border-[#6cc99e]/[0.30] dark:bg-[#6cc99e]/[0.15] dark:text-[#6cc99e]",
  warning: "border-[#e7c98a] bg-[#fbeecb] text-[#8a6312] dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]",
  neutral: "border-black/[0.08] bg-[#f4efe6] text-[#8a8275] dark:border-white/[0.1] dark:bg-white/[0.08] dark:text-[#9a9184]",
};

const LABEL_CELL =
  "sticky left-0 z-10 w-28 min-w-28 border-b border-r border-black/[0.06] bg-[#f4efe6] px-3 py-4 align-top text-xs font-semibold text-[#6b655a] dark:border-white/[0.1] dark:bg-[#16130f] dark:text-[#b6ad9d]";
const DATA_CELL =
  "min-w-[220px] border-b border-r border-black/[0.06] bg-white/45 px-4 py-4 align-top text-sm text-[#1a1714] dark:border-white/[0.1] dark:bg-white/[0.04] dark:text-[#f3ecdf]";
const MUTED = "text-[#9a9184] dark:text-[#837c70]";

function companyKey(company: string): string {
  return company.trim().toLowerCase();
}

function matchReasonText(reason: MatchReason): string {
  if (reason.type === "freshness") return reason.value;
  return `${MATCH_REASON_LABELS[reason.type]}：${reason.value}`;
}

function recruitTypeStyle(t: string): string {
  if (t === "实习")
    return "border-[#e7c98a] bg-[#fbeecb] text-[#8a6312] dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]";
  if (t === "校招")
    return "border-[#bcdcae] bg-[#e6f2d6] text-[#4f6f2a] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]";
  return "border-[#b7d2ee] bg-[#dceafa] text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]";
}

function tierStyle(level: "high" | "related"): string {
  if (level === "high") {
    return "border-[#a9d8c4] bg-[#dcf2e8] text-[#2f8a63] dark:border-[#6cc99e]/[0.30] dark:bg-[#6cc99e]/[0.15] dark:text-[#6cc99e]";
  }
  return "border-[#b7d2ee] bg-[#dceafa] text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]";
}

function textOrMuted(value: string | null | undefined, fallback = "未知"): ReactNode {
  const text = value?.trim() || fallback;
  if (text === fallback || text === "未知") return <span className={MUTED}>{text}</span>;
  return text;
}

function hiringSignalChip(data: CompanyInsightResponse | null) {
  const items = data?.dimensions?.hiring || [];
  for (const item of items) {
    const payload = (item.payload || {}) as Record<string, unknown>;
    const chip = formatHiringSignalChip(
      payload.hiring_signal as Record<string, unknown> | null | undefined,
    );
    if (chip) return chip;
  }
  return null;
}

function compensationSummary(data: CompanyInsightResponse | null): string | null {
  const item = data?.dimensions?.compensation_intensity?.[0];
  if (!item) return null;
  return item.title ? `${item.title}：${item.content}` : item.content;
}

export default function SavedCompare({
  open,
  jobs,
  hasPreferences,
  onClose,
  onRemove,
}: Props) {
  const [insights, setInsights] = useState<Record<string, InsightState>>({});

  const companyList = useMemo(() => {
    const seen = new Map<string, string>();
    for (const job of jobs) {
      const key = companyKey(job.company);
      if (key && !seen.has(key)) seen.set(key, job.company);
    }
    return Array.from(seen.entries());
  }, [jobs]);

  const jobDetails = useMemo(() => {
    const map = new Map<
      string,
      {
        recruitType: string;
        experience: string;
        education: string;
        deadline: string;
        freshness: { label: string; stale: boolean };
      }
    >();
    for (const job of jobs) {
      const summary = cleanSummary(job.summary);
      map.set(job.id, {
        recruitType: recruitmentCategory({
          title: job.title,
          job_type: job.job_type,
          summary,
          jd_url: job.jd_url,
        }),
        experience: job.experience || extractExperience(summary),
        education: job.education || extractEducation(summary),
        deadline: job.deadline || extractDeadline(summary),
        freshness: freshnessLabel(job.last_seen_at),
      });
    }
    return map;
  }, [jobs]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    for (const [key, company] of companyList) {
      const cached = getCachedInsights(company);
      if (cached) {
        setInsights((prev) => ({ ...prev, [key]: { loading: false, data: cached } }));
        continue;
      }
      setInsights((prev) => ({ ...prev, [key]: { loading: true, data: prev[key]?.data || null } }));
      void fetchCompanyInsights(company).then((data) => {
        if (cancelled) return;
        setInsights((prev) => ({ ...prev, [key]: { loading: false, data } }));
      });
    }
    return () => {
      cancelled = true;
    };
  }, [companyList, open]);

  // 通过 portal 渲染到 body：saved 列表卡片有 hover transform，fixed 对比层不能成为它的后代。
  if (!open || typeof document === "undefined") return null;

  const tableMinWidth = 128 + jobs.length * 220;

  function renderRow(label: string, renderCell: (job: ScoredJob) => ReactNode) {
    return (
      <tr>
        <th scope="row" className={LABEL_CELL}>
          {label}
        </th>
        {jobs.map((job) => (
          <td key={`${label}-${job.id}`} className={DATA_CELL}>
            {renderCell(job)}
          </td>
        ))}
      </tr>
    );
  }

  function detail(job: ScoredJob) {
    return jobDetails.get(job.id)!;
  }

  function matchCell(job: ScoredJob) {
    if (!hasPreferences) return <span className={MUTED}>未设置偏好</span>;
    const tier = matchTier(job.match_score);
    const reasons = (job.match_reasons || []).slice(0, 3);
    if (!tier.label && reasons.length === 0) return <span className={MUTED}>暂无明显匹配</span>;
    return (
      <div className="space-y-2">
        {tier.label && tier.level !== "none" && (
          <span className={cn("inline-flex rounded-full border px-2.5 py-0.5 text-[11px] font-semibold", tierStyle(tier.level))}>
            {tier.label}
          </span>
        )}
        {reasons.length > 0 && (
          <ul className="space-y-1 text-xs leading-5 text-[#6b655a] dark:text-[#b6ad9d]">
            {reasons.map((reason, idx) => (
              <li key={`${reason.type}-${reason.value}-${idx}`}>{matchReasonText(reason)}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  function insightCell(job: ScoredJob) {
    const state = insights[companyKey(job.company)];
    if (!state || state.loading) {
      return (
        <span className="inline-flex items-center gap-2 text-xs text-[#8a8275] dark:text-[#9a9184]">
          <CircleNotch size={14} weight="bold" className="animate-spin" aria-hidden="true" />
          正在加载洞察
        </span>
      );
    }
    const chip = hiringSignalChip(state.data);
    const comp = compensationSummary(state.data);
    if (!chip && !comp) return <span className={MUTED}>暂无洞察</span>;
    return (
      <div className="space-y-2">
        {chip && (
          <span className={cn("inline-flex rounded-full border px-2.5 py-0.5 text-[11px] font-semibold", CHIP_TONE[chip.tone])}>
            {chip.text}
          </span>
        )}
        {comp && <p className="text-xs leading-5 text-[#6b655a] dark:text-[#b6ad9d]">{comp}</p>}
      </div>
    );
  }

  return createPortal(
    <div className="fixed inset-0 z-[60] flex">
      <button
        type="button"
        aria-label="关闭"
        onClick={onClose}
        className="absolute inset-0 bg-[#1a1714]/40 backdrop-blur-sm dark:bg-black/60"
      />
      <section
        role="dialog"
        aria-modal="true"
        aria-label="岗位对比决策桌"
        className="relative flex h-full w-full flex-col bg-[#f4efe6] text-[#1a1714] shadow-2xl dark:bg-[#16130f] dark:text-[#f3ecdf]"
      >
        <header className="border-b border-black/[0.06] bg-gradient-to-b from-white/70 to-transparent px-4 pb-4 pt-5 sm:px-6 dark:border-white/[0.1] dark:from-white/[0.05]">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm text-[#8a8275] dark:text-[#9a9184]">
                <Scales size={17} weight="bold" aria-hidden="true" />
                对比决策桌
              </div>
              <h2 className="mt-1 text-2xl font-semibold leading-tight">并排看关键决策信息</h2>
              <p className="mt-1 text-xs text-[#8a8275] dark:text-[#9a9184]">已选 {jobs.length}/4，关闭后选择状态会保留。</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="shrink-0 rounded-full bg-black/[0.05] p-2 text-[#5f594e] transition hover:bg-black/[0.08] hover:text-[#1a1714] dark:bg-white/[0.05] dark:text-[#b6ad9d] dark:hover:bg-white/[0.08] dark:hover:text-[#f3ecdf]"
              aria-label="关闭对比层"
            >
              <X size={18} weight="bold" aria-hidden="true" />
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto px-3 py-4 sm:px-6 sm:py-6">
          {jobs.length === 0 ? (
            <div className="rounded-[1.25rem] border border-dashed border-black/[0.12] bg-white/45 px-6 py-12 text-center text-sm text-[#6b655a] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d]">
              还没有选择岗位。
            </div>
          ) : (
            <div className="overflow-x-auto rounded-[1.25rem] border border-black/[0.08] dark:border-white/[0.1]">
              <table className="border-separate border-spacing-0 text-left" style={{ minWidth: tableMinWidth }}>
                <tbody>
                  {renderRow("职位", (job) => (
                    <div className="space-y-1">
                      <p className="text-[15px] font-semibold leading-5">{job.title}</p>
                      <p className="text-xs text-[#8a8275] dark:text-[#9a9184]">{job.company}</p>
                    </div>
                  ))}
                  {renderRow("城市", (job) => textOrMuted(job.location))}
                  {renderRow("招聘类型", (job) => (
                    <span className={cn("inline-flex rounded-full border px-2.5 py-0.5 text-[11px] font-semibold", recruitTypeStyle(detail(job).recruitType))}>
                      {detail(job).recruitType}
                    </span>
                  ))}
                  {renderRow("匹配", matchCell)}
                  {renderRow("经验要求", (job) => textOrMuted(detail(job).experience))}
                  {renderRow("学历要求", (job) => textOrMuted(detail(job).education))}
                  {renderRow("薪资", (job) => textOrMuted(job.salary_text, "官网未披露"))}
                  {renderRow("截止", (job) => textOrMuted(detail(job).deadline))}
                  {renderRow("新鲜度", (job) => {
                    const freshness = detail(job).freshness;
                    if (!freshness.label) return <span className={MUTED}>未知</span>;
                    return (
                      <span
                        className={cn(
                          "inline-flex rounded-full border px-2.5 py-0.5 text-[11px] font-semibold",
                          freshness.stale
                            ? "border-[#e7c98a] bg-[#fbeecb] text-[#8a6312] dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]"
                            : "border-[#bcdcae] bg-[#e6f2d6] text-[#4f6f2a] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]",
                        )}
                      >
                        {freshness.label}
                      </span>
                    );
                  })}
                  {renderRow("公司洞察", insightCell)}
                  {renderRow("操作", (job) => (
                    <div className="flex flex-col gap-2">
                      <a
                        href={job.jd_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-full bg-[#1a1714] px-3 py-2 text-sm font-semibold text-[#f7f1e6] transition hover:bg-[#2b2520] dark:bg-[#f3ecdf] dark:text-[#16130f] dark:hover:bg-[#e8ddca]"
                      >
                        查看官网
                        <ArrowSquareOut size={14} weight="bold" aria-hidden="true" />
                      </a>
                      <button
                        type="button"
                        onClick={() => onRemove(job.id)}
                        className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-full border border-black/[0.08] bg-white/70 px-3 py-2 text-sm font-semibold text-[#3f3a33] transition hover:bg-white dark:border-white/[0.12] dark:bg-white/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.08]"
                      >
                        <XCircle size={14} weight="bold" aria-hidden="true" />
                        移出对比
                      </button>
                    </div>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </div>,
    document.body,
  );
}

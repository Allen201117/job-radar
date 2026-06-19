"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Briefcase,
  CalendarBlank,
  FileArrowUp,
  Path,
  Scales,
  ShieldWarning,
} from "@phosphor-icons/react";
import type { CareerPathReport, TimingStatusKind } from "@/lib/types";
import { cn } from "@/lib/utils";

const TIMING_STYLE: Record<TimingStatusKind, string> = {
  open: "border border-[#bcdcae] dark:border-[#a3d06a]/[0.30] bg-[#e6f2d6] dark:bg-[#a3d06a]/[0.15] text-[#4f6f2a] dark:text-[#a3d06a]",
  rolling: "border border-[#b7d2ee] dark:border-[#7fb2e8]/[0.30] bg-[#dceafa] dark:bg-[#7fb2e8]/[0.15] text-[#2f6299] dark:text-[#7fb2e8]",
  closed: "border border-[#e7c98a] dark:border-[#e0b15a]/[0.30] bg-[#fbeecb] dark:bg-[#e0b15a]/[0.15] text-[#8a6312] dark:text-[#e0b15a]",
  unknown: "border border-black/[0.08] dark:border-white/[0.1] bg-[#f4efe6] dark:bg-[#16130f] text-[#8a8275] dark:text-[#9a9184]",
};

export default function CareerPathClient() {
  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState<CareerPathReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    fetch("/api/career-path")
      .then(async (r) => {
        if (r.status === 401) throw new Error("请先登录");
        const d = await r.json();
        if (!d.ok) throw new Error(d.error || "加载失败");
        if (alive) setReport(d.report as CareerPathReport);
      })
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  if (loading) return <p className="mt-8 text-sm text-[#8a8275] dark:text-[#9a9184]">正在生成职业路径…</p>;
  if (error)
    return (
      <p className="mt-8 rounded-xl border border-black/[0.06] dark:border-white/[0.1] bg-white/55 dark:bg-white/[0.05] p-4 text-sm text-[#5f594e] dark:text-[#b6ad9d]">
        {error}
      </p>
    );
  if (!report) return null;

  const noData = report.recommendations.length === 0;

  return (
    <div className="mt-8 space-y-8 text-[#1a1714] dark:text-[#f3ecdf]">
      {/* 画像摘要 */}
      <ProfileSummary report={report} />

      {report.is_recommended_fallback && report.recommendations.length > 0 && (
        <p className="rounded-xl border border-[#cfe0f5] dark:border-[#7fb2e8]/[0.30] bg-[#e8f1fc] dark:bg-[#7fb2e8]/[0.15] px-4 py-3 text-sm leading-6 text-[#2f6299] dark:text-[#7fb2e8]">
          你还没设置目标公司，以下是按<strong>当前招聘窗口期</strong>给出的推荐。到
          <Link href="/preferences" className="mx-1 underline underline-offset-2 hover:text-[#1a1714] dark:hover:text-[#f3ecdf]">
            偏好设置
          </Link>
          里加上目标公司，建议会更贴合你。
        </p>
      )}

      {noData ? (
        <EmptyState reason={report.failure_reason} />
      ) : (
        <section>
          <SectionTitle icon={CalendarBlank} title="优先投递建议" hint="按招聘窗口期与在招岗位排序" />
          <div className="space-y-3">
            {report.recommendations.map((rec) => (
              <article
                key={rec.company}
                className="surface-soft p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-base font-semibold">{rec.display_name || rec.company}</span>
                  <span className={cn("rounded-full px-2.5 py-1 text-xs font-semibold", TIMING_STYLE[rec.timing.status])}>
                    {rec.timing.label}
                  </span>
                  {rec.job_count > 0 && (
                    <Link
                      href="/jobs"
                      className="inline-flex items-center gap-1 rounded-full border border-black/[0.08] dark:border-white/[0.1] bg-white/70 dark:bg-white/[0.05] px-2.5 py-1 text-xs text-[#5f594e] dark:text-[#b6ad9d] transition hover:bg-white dark:hover:bg-white/[0.05] hover:text-[#1a1714] dark:hover:text-[#f3ecdf]"
                    >
                      <Briefcase size={12} weight="bold" />
                      {rec.job_count} 个在招
                    </Link>
                  )}
                </div>
                {rec.timing.detail && (
                  <p className="mt-1.5 text-xs text-[#8a8275] dark:text-[#9a9184]">招聘节奏：{rec.timing.detail}</p>
                )}
                <div className="mt-2 grid gap-1.5 text-sm sm:grid-cols-2">
                  {rec.comp_note && (
                    <span className="inline-flex items-center gap-1.5 text-[#5f594e] dark:text-[#b6ad9d]">
                      <Scales size={14} className="text-[#a39a8c] dark:text-[#8b8478]" /> {rec.comp_note}
                    </span>
                  )}
                  {rec.caution_note && (
                    <span className="inline-flex items-center gap-1.5 text-[#9a6a2a] dark:text-[#e0b15a]">
                      <ShieldWarning size={14} className="text-[#c79237] dark:text-[#e0b15a]" /> {rec.caution_note}
                    </span>
                  )}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {report.path_notes.length > 0 && (
        <section>
          <SectionTitle icon={Path} title="路径 / 跳板" hint="据公开报道的人才流动观察" />
          <div className="space-y-3">
            {report.path_notes.map((n, i) => (
              <NoteCard key={`${n.company}-${i}`} company={n.company} title={n.title} content={n.content} />
            ))}
          </div>
        </section>
      )}

      {report.cautions.length > 0 && (
        <section>
          <SectionTitle icon={ShieldWarning} title="温馨提示" hint="群体性反馈，非事实定性，仅供参考" />
          <div className="space-y-3">
            {report.cautions.map((n, i) => (
              <NoteCard key={`${n.company}-${i}`} company={n.company} title={n.title} content={n.content} caution />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function ProfileSummary({ report }: { report: CareerPathReport }) {
  const { target_roles, seniority, target_locations } = report.profile_summary;
  // 无画像时不在这里出提示框，交给下方单一的 EmptyState（上传引导卡），避免两个相似的框重复。
  if (!report.has_profile) return null;
  const chips = [
    ...(seniority ? [seniority] : []),
    ...target_roles,
    ...target_locations,
  ];
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-[#8a8275] dark:text-[#9a9184]">你的画像：</span>
      {chips.map((c) => (
        <span key={c} className="rounded-full border border-black/[0.06] dark:border-white/[0.1] bg-white/70 dark:bg-white/[0.05] px-2.5 py-1 text-xs text-[#5f594e] dark:text-[#b6ad9d]">
          {c}
        </span>
      ))}
    </div>
  );
}

function EmptyState({ reason }: { reason: CareerPathReport["failure_reason"] }) {
  if (reason === "no_profile") {
    return (
      <div className="rounded-2xl border border-dashed border-black/[0.12] dark:border-white/[0.12] bg-white/45 dark:bg-white/[0.04] px-6 py-12 text-center">
        <div className="mx-auto grid size-12 place-items-center rounded-2xl bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]">
          <FileArrowUp size={22} weight="bold" aria-hidden="true" />
        </div>
        <h3 className="mt-4 text-lg font-semibold text-[#1a1714] dark:text-[#f3ecdf]">先上传简历，解锁你的职业路径</h3>
        <p className="mx-auto mt-2 max-w-md text-pretty text-sm leading-6 text-[#5f594e] dark:text-[#b6ad9d]">
          上传简历或填写目标岗位 / 城市 / 公司后，我们会结合公司洞察（时机 / 性价比 / 路径 / 文化）给出投递优先级与温馨提示。
        </p>
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          <Link href="/me" className="btn-ink">
            上传简历
            <ArrowRight size={16} weight="bold" aria-hidden="true" />
          </Link>
          <Link href="/preferences" className="btn-soft">填写求职偏好</Link>
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-black/[0.06] dark:border-white/[0.1] bg-white/55 dark:bg-white/[0.05] p-5 text-sm leading-6 text-[#5f594e] dark:text-[#b6ad9d]">
      你的目标公司暂无经核实的洞察信息。我们只展示通过分级与时效校验的内容，宁缺毋滥。
    </div>
  );
}

function SectionTitle({
  icon: Icon,
  title,
  hint,
}: {
  icon: typeof Path;
  title: string;
  hint?: string;
}) {
  return (
    <div className="mb-3 flex items-baseline gap-2">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-[#3f3a33] dark:text-[#d9d0c2]">
        <Icon size={16} weight="bold" className="text-[#6a4fa0] dark:text-[#a98fd6]" />
        {title}
      </h2>
      {hint && <span className="text-xs text-[#9a9184] dark:text-[#837c70]">· {hint}</span>}
    </div>
  );
}

function NoteCard({
  company,
  title,
  content,
  caution,
}: {
  company: string;
  title: string | null;
  content: string;
  caution?: boolean;
}) {
  return (
    <article
      className={cn(
        "rounded-xl border border-black/[0.05] dark:border-white/[0.1] border-l-2 bg-white/55 dark:bg-white/[0.05] p-4 pl-3.5 text-sm",
        caution ? "border-l-[#e0a94e] dark:border-l-[#e0b15a]" : "border-l-[#9a7fce] dark:border-l-[#a98fd6]",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-[#8a8275] dark:text-[#9a9184]">{company}</span>
        {title && <span className="text-sm font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{title}</span>}
      </div>
      <p className="mt-1 leading-6 text-[#5f594e] dark:text-[#b6ad9d]">{content}</p>
    </article>
  );
}

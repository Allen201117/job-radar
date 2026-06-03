"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Briefcase,
  CalendarBlank,
  Path,
  Scales,
  ShieldWarning,
  SlidersHorizontal,
} from "@phosphor-icons/react";
import type { CareerPathReport, TimingStatusKind } from "@/lib/types";
import { cn } from "@/lib/utils";

const TIMING_STYLE: Record<TimingStatusKind, string> = {
  open: "border border-emerald-300/25 bg-emerald-300/15 text-emerald-200",
  rolling: "border border-sky-300/25 bg-sky-300/15 text-sky-200",
  closed: "border border-amber-300/25 bg-amber-300/15 text-amber-200",
  unknown: "border border-white/15 bg-white/10 text-white/55",
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

  if (loading) return <p className="mt-8 text-sm text-white/50">正在生成职业路径…</p>;
  if (error)
    return (
      <p className="mt-8 rounded-xl border border-white/10 bg-white/[0.04] p-4 text-sm text-white/60">
        {error}
      </p>
    );
  if (!report) return null;

  const noData = report.recommendations.length === 0;

  return (
    <div className="mt-8 space-y-8 text-white">
      {/* 画像摘要 */}
      <ProfileSummary report={report} />

      {report.is_recommended_fallback && report.recommendations.length > 0 && (
        <p className="rounded-xl border border-sky-300/20 bg-sky-300/10 px-4 py-3 text-sm leading-6 text-sky-100/90">
          你还没设置目标公司，以下是按<strong>当前招聘窗口期</strong>给出的推荐。到
          <Link href="/preferences" className="mx-1 underline underline-offset-2 hover:text-white">
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
                className="rounded-[1.1rem] border border-white/10 bg-white/[0.05] p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-base font-semibold">{rec.display_name || rec.company}</span>
                  <span className={cn("rounded-full px-2.5 py-1 text-xs font-semibold", TIMING_STYLE[rec.timing.status])}>
                    {rec.timing.label}
                  </span>
                  {rec.job_count > 0 && (
                    <Link
                      href="/jobs"
                      className="inline-flex items-center gap-1 rounded-full border border-white/12 bg-white/[0.06] px-2.5 py-1 text-xs text-white/70 transition hover:border-white/25 hover:text-white"
                    >
                      <Briefcase size={12} weight="bold" />
                      {rec.job_count} 个在招
                    </Link>
                  )}
                </div>
                {rec.timing.detail && (
                  <p className="mt-1.5 text-xs text-white/45">招聘节奏：{rec.timing.detail}</p>
                )}
                <div className="mt-2 grid gap-1.5 text-sm sm:grid-cols-2">
                  {rec.comp_note && (
                    <span className="inline-flex items-center gap-1.5 text-white/70">
                      <Scales size={14} className="text-white/40" /> {rec.comp_note}
                    </span>
                  )}
                  {rec.caution_note && (
                    <span className="inline-flex items-center gap-1.5 text-amber-200/80">
                      <ShieldWarning size={14} className="text-amber-300/70" /> {rec.caution_note}
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
  if (!report.has_profile) {
    return (
      <div className="rounded-xl border border-white/10 bg-white/[0.04] p-4 text-sm leading-6 text-white/60">
        还没有你的求职画像。到
        <Link href="/preferences" className="mx-1 underline underline-offset-2 hover:text-white">
          偏好设置
        </Link>
        上传简历或填写目标岗位/城市/公司，路径建议会基于你的画像生成。
      </div>
    );
  }
  const chips = [
    ...(seniority ? [seniority] : []),
    ...target_roles,
    ...target_locations,
  ];
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-white/45">你的画像：</span>
      {chips.map((c) => (
        <span key={c} className="rounded-full border border-white/10 bg-white/[0.06] px-2.5 py-1 text-xs text-white/75">
          {c}
        </span>
      ))}
    </div>
  );
}

function EmptyState({ reason }: { reason: CareerPathReport["failure_reason"] }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.04] p-5 text-sm leading-6 text-white/65">
      {reason === "no_profile" ? (
        <>
          先到
          <Link href="/preferences" className="mx-1 inline-flex items-center gap-1 underline underline-offset-2 hover:text-white">
            偏好设置 <ArrowRight size={13} weight="bold" />
          </Link>
          设置目标公司或上传简历，我们再据公司洞察给出投递优先级与温馨提示。
        </>
      ) : (
        "你的目标公司暂无经核实的洞察信息。我们只展示通过分级与时效校验的内容，宁缺毋滥。"
      )}
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
      <h2 className="flex items-center gap-2 text-sm font-semibold text-white/80">
        <Icon size={16} weight="bold" className="text-violet-300" />
        {title}
      </h2>
      {hint && <span className="text-xs text-white/40">· {hint}</span>}
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
        "rounded-xl border-l-2 bg-white/[0.04] p-4 pl-3.5 text-sm",
        caution ? "border-l-amber-300/50" : "border-l-violet-300/50",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-white/50">{company}</span>
        {title && <span className="text-sm font-semibold text-white/90">{title}</span>}
      </div>
      <p className="mt-1 leading-6 text-white/70">{content}</p>
    </article>
  );
}

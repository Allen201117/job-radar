"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowSquareOut,
  BookmarkSimple,
  Briefcase,
  CalendarBlank,
  CaretDown,
  CheckCircle,
  GraduationCap,
  Hourglass,
  MapPin,
  Sparkle,
  XCircle,
} from "@phosphor-icons/react";
import { createBrowserClient } from "@/lib/supabaseClient";
import { normalizeChinaJobType } from "@/lib/china-keyword-expansion";
import CompanyInsightDrawer from "@/components/CompanyInsightDrawer";
import { fetchCompanyInsights, getCachedInsights } from "@/lib/insight-client";
import type { ScoredJob } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  job: ScoredJob;
  onActionChange: (jobId: string, action: PrimaryAction | null) => void;
  // 本次会话刷新/发现新拿到的岗位 → 绿色高亮 + 「本次新发现」标
  sessionNew?: boolean;
}

type PrimaryAction = "saved" | "ignored" | "applied";

function extractExperience(text?: string | null): string {
  if (!text) return "未知";
  const t = text.replace(/\s+/g, "");
  if (/应届|无经验要求|经验不限|不限经验|noexperience|entrylevel/i.test(t)) return "应届/不限";
  let m = t.match(/(\d+)[-~至到](\d+)年/) || t.match(/(\d+)年(?:以上)?(?:工作)?经验/);
  if (m) return m[2] ? `${m[1]}-${m[2]}年` : `${m[1]}年+`;
  // 英文：3-5 years / 5+ years / 3 years experience（空格已去除）
  m = t.match(/(\d+)[-~to]+(\d+)years?/i) || t.match(/(\d+)\+?years?(?:ofexperience)?/i);
  if (m) return m[2] ? `${m[1]}-${m[2]}年` : `${m[1]}年+`;
  return "未知";
}

function extractEducation(text?: string | null): string {
  if (!text) return "未知";
  if (/博士|ph\.?d|doctora/i.test(text)) return "博士";
  if (/硕士|研究生|master/i.test(text)) return "硕士";
  if (/本科|学士|bachelor|undergrad/i.test(text)) return "本科";
  if (/大专|专科/.test(text)) return "大专";
  if (/学历不限|不限学历/.test(text)) return "不限";
  return "未知";
}

function extractDeadline(text?: string | null): string {
  if (!text) return "未知";
  if (/长期有效|长期招聘|long[\s-]?term|rolling|until filled/i.test(text)) return "长期有效";
  const m = text.match(
    /(?:截止|截至|申请截止|投递截止|deadline)[^0-9]{0,8}(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2})/i,
  );
  if (m) return m[1].replace(/[年月]/g, "-").replace(/[./]/g, "-").replace(/-+$/, "");
  return "未知";
}

function recruitTypeStyle(t: string): string {
  if (/实习|intern/i.test(t)) return "border border-amber-300/25 bg-amber-300/15 text-amber-200";
  if (/校招|管培|应届|graduate|campus|new grad/i.test(t))
    return "border border-emerald-300/25 bg-emerald-300/15 text-emerald-200";
  if (/社招|全职|experienced|professional/i.test(t))
    return "border border-sky-300/25 bg-sky-300/15 text-sky-200";
  return "border border-white/10 bg-white/10 text-white/62";
}

export default function JobCard({ job, onActionChange, sessionNew }: Props) {
  const [acting, setActing] = useState(false);
  const [currentAction, setCurrentAction] = useState(job.user_action);
  const [actionError, setActionError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [insightOpen, setInsightOpen] = useState(false);
  const [timingHint, setTimingHint] = useState<string | null>(null);
  const supabase = createBrowserClient();

  useEffect(() => {
    setCurrentAction(job.user_action);
  }, [job.user_action]);

  // 懒取该公司洞察（client 层按公司去重缓存），有时机洞察则在卡片上提示
  useEffect(() => {
    if (!job.company) return;
    let alive = true;
    const apply = (res: ReturnType<typeof getCachedInsights>) => {
      const timing = res?.dimensions?.timing?.[0];
      if (alive && timing) setTimingHint(timing.title || timing.time_window || "查看招聘时机");
    };
    const cached = getCachedInsights(job.company);
    if (cached) {
      apply(cached);
      return;
    }
    void fetchCompanyInsights(job.company).then((res) => apply(res));
    return () => {
      alive = false;
    };
  }, [job.company]);

  // 优先用爬虫从完整 JD 抽取并入库的结构化列；列为空（历史行/未重抓）才回退旧的 summary 正则。
  const exp = useMemo(() => job.experience || extractExperience(job.summary), [job.experience, job.summary]);
  const edu = useMemo(() => job.education || extractEducation(job.summary), [job.education, job.summary]);
  const deadline = useMemo(
    () => job.deadline || extractDeadline(job.summary),
    [job.deadline, job.summary],
  );
  const recruitType = useMemo(
    () =>
      normalizeChinaJobType({
        title: job.title,
        sourceType: job.job_type,
        summary: job.summary,
      }) ||
      job.job_type ||
      null,
    [job.title, job.job_type, job.summary],
  );

  async function writeAction(action: PrimaryAction | null, prev: PrimaryAction | null) {
    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      const uid = session?.user?.id;
      if (!uid) throw new Error("未登录");
      await supabase
        .from("job_actions")
        .delete()
        .eq("user_id", uid)
        .eq("job_id", job.id)
        .neq("action", "viewed");
      if (action) {
        const { error } = await supabase
          .from("job_actions")
          .upsert(
            { user_id: uid, job_id: job.id, action },
            { onConflict: "user_id,job_id,action" },
          );
        if (error) throw error;
      }
    } catch (e) {
      console.error("[job-card] action failed", e);
      setCurrentAction(prev);
      onActionChange(job.id, prev);
      setActionError("操作失败，已回退");
      setTimeout(() => setActionError(""), 2500);
    } finally {
      setActing(false);
    }
  }

  function handleAction(action: PrimaryAction) {
    if (acting) return;
    setActionError("");
    const prev = currentAction as PrimaryAction | null;
    const next = prev === action ? null : action;
    setCurrentAction(next);
    onActionChange(job.id, next);
    setActing(true);
    void writeAction(next, prev);
  }

  function handleView() {
    window.open(job.jd_url, "_blank", "noopener,noreferrer");
    supabase.auth.getSession().then(({ data: { session } }) => {
      const uid = session?.user?.id;
      if (uid) {
        void supabase.from("job_actions").upsert(
          { user_id: uid, job_id: job.id, action: "viewed" },
          { onConflict: "user_id,job_id,action" },
        );
      }
    });
  }

  const isNew =
    job.first_seen_at &&
    (Date.now() - new Date(job.first_seen_at).getTime()) / 86400000 <= 3;
  const posted = job.posted_at
    ? new Date(job.posted_at).toLocaleDateString("zh-CN")
    : "未知";

  return (
    <article
      className={cn(
        "group rounded-[1.35rem] border p-5 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] transition duration-200 hover:-translate-y-0.5 hover:shadow-2xl hover:shadow-black/25",
        sessionNew
          ? "border-lime-300/45 bg-lime-300/[0.06] ring-1 ring-lime-300/25 hover:border-lime-300/60 hover:bg-lime-300/[0.09]"
          : "border-white/10 bg-white/[0.065] hover:border-white/18 hover:bg-white/[0.085]",
      )}
    >
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-white/58">{job.company}</span>
            {recruitType && (
              <span
                className={cn(
                  "rounded-full px-2.5 py-1 text-xs font-semibold",
                  recruitTypeStyle(recruitType),
                )}
              >
                {recruitType}
              </span>
            )}
            {sessionNew && (
              <span className="inline-flex items-center gap-1 rounded-full bg-lime-300 px-2.5 py-1 text-xs font-semibold text-lime-950">
                <Sparkle size={12} weight="fill" aria-hidden="true" />
                本次新发现
              </span>
            )}
            {isNew && !sessionNew && (
              <span className="rounded-full bg-sky-300 px-2.5 py-1 text-xs font-semibold text-sky-950">
                新发现
              </span>
            )}
            {currentAction && (
              <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-[#08090c]">
                {currentAction === "saved"
                  ? "已收藏"
                  : currentAction === "applied"
                    ? "已投递"
                    : currentAction === "ignored"
                      ? "已忽略"
                      : ""}
              </span>
            )}
            <button
              type="button"
              onClick={() => setInsightOpen(true)}
              title="查看该公司的职业洞察（社区聚合·非官方）"
              className="inline-flex items-center gap-1 rounded-full border border-violet-300/25 bg-violet-300/12 px-2.5 py-1 text-xs font-medium text-violet-200 transition hover:border-violet-300/40 hover:bg-violet-300/20"
            >
              <Sparkle size={12} weight="fill" aria-hidden="true" />
              {timingHint ? `时机: ${timingHint}` : "职业洞察"}
            </button>
          </div>

          <button
            type="button"
            onClick={handleView}
            className="mt-2 block max-w-full text-left text-xl font-semibold leading-snug text-white transition-colors hover:text-sky-200"
          >
            <span className="text-balance">{job.title}</span>
          </button>

          <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2 xl:grid-cols-3">
            <Field icon={MapPin} label="城市" value={job.location || "未知"} />
            <Field icon={Briefcase} label="薪资" value={job.salary_text || "官网未披露"} />
            <Field icon={GraduationCap} label="经验" value={exp} />
            <Field icon={GraduationCap} label="学历" value={edu} />
            <Field icon={CalendarBlank} label="发布" value={posted} />
            <Field icon={Hourglass} label="截止" value={deadline} />
          </div>

          {job.summary && (
            <div className="mt-4">
              <p
                className={cn(
                  "whitespace-pre-line text-pretty text-sm leading-6 text-white/56",
                  !expanded && "line-clamp-3",
                )}
              >
                {job.summary}
              </p>
              {job.summary.length > 80 && (
                <button
                  type="button"
                  onClick={() => setExpanded((v) => !v)}
                  className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-sky-300 transition-colors hover:text-sky-200"
                >
                  {expanded ? "收起" : "展开全文"}
                  <CaretDown
                    className={cn("size-4 transition-transform", expanded && "rotate-180")}
                    aria-hidden="true"
                  />
                </button>
              )}
            </div>
          )}

          {job.matched_keywords.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-1.5">
              {job.matched_keywords.map((kw) => (
                <span
                  key={kw}
                  className="rounded-full border border-sky-300/20 bg-sky-300/10 px-2.5 py-1 text-xs font-medium text-sky-200"
                >
                  {kw}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex shrink-0 flex-col gap-2 lg:w-36">
          {job.match_score > 0 && (
            <div
              title="根据你的求职偏好与简历画像计算的匹配度（越高越契合）"
              className={cn(
                "rounded-xl px-3 py-2 text-center shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]",
                job.match_score >= 50
                  ? "bg-white text-[#08090c]"
                  : "bg-white/10 text-white",
              )}
            >
              <span className="block text-xs opacity-80">匹配度</span>
              <span className="tabular-nums text-2xl font-semibold leading-none">
                {job.match_score}
              </span>
            </div>
          )}

          <button
            type="button"
            onClick={handleView}
            className="inline-flex items-center justify-center gap-2 rounded-full bg-sky-300 px-4 py-2 text-sm font-semibold text-sky-950 transition duration-200 hover:bg-sky-200 active:scale-[0.98]"
          >
            官网详情
            <ArrowSquareOut size={16} weight="bold" aria-hidden="true" />
          </button>
          <ActionButton
            active={currentAction === "saved"}
            disabled={acting}
            onClick={() => handleAction("saved")}
            icon={BookmarkSimple}
            label={currentAction === "saved" ? "已收藏" : "收藏"}
          />
          <ActionButton
            active={currentAction === "applied"}
            disabled={acting}
            onClick={() => handleAction("applied")}
            icon={CheckCircle}
            label={currentAction === "applied" ? "已投递" : "标记投递"}
          />
          <ActionButton
            muted
            active={currentAction === "ignored"}
            disabled={acting}
            onClick={() => handleAction("ignored")}
            icon={XCircle}
            label={currentAction === "ignored" ? "已忽略" : "忽略"}
          />
          {actionError && (
            <span className="rounded-lg bg-red-400/10 px-2 py-1 text-right text-xs text-red-200">
              {actionError}
            </span>
          )}
        </div>
      </div>

      <CompanyInsightDrawer
        company={job.company}
        open={insightOpen}
        onClose={() => setInsightOpen(false)}
      />
    </article>
  );
}

function Field({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof MapPin;
  label: string;
  value: string;
}) {
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.06] px-3 py-2">
      <Icon size={16} className="shrink-0 text-white/42" aria-hidden="true" />
      <div className="min-w-0">
        <span className="mr-1 text-white/42">{label}</span>
        <span className="truncate font-medium text-white/82">{value}</span>
      </div>
    </div>
  );
}

function ActionButton({
  active,
  disabled,
  muted,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  disabled: boolean;
  muted?: boolean;
  onClick: () => void;
  icon: typeof BookmarkSimple;
  label: string;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition duration-200 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50",
        active
          ? "bg-white text-[#08090c]"
          : muted
            ? "text-white/52 hover:bg-white/10 hover:text-white"
            : "bg-white/10 text-white/78 hover:bg-white/16 hover:text-white",
      )}
    >
      <Icon size={16} weight={active ? "fill" : "regular"} aria-hidden="true" />
      {label}
    </button>
  );
}

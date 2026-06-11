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
import {
  classifyJobFunction,
  recruitmentCategory,
} from "@/lib/china-keyword-expansion";
import CompanyInsightDrawer from "@/components/CompanyInsightDrawer";
import type { ScoredJob } from "@/lib/types";
import { cleanSummary, cn, freshnessLabel } from "@/lib/utils";

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

// 招聘类型（实习/校招/社招）= 强特征，三色区分，每张卡片必显示。
function recruitTypeStyle(t: string): string {
  if (t === "实习") return "border border-[#e7c98a] bg-[#fbeecb] text-[#8a6312]";
  if (t === "校招") return "border border-[#bcdcae] bg-[#e6f2d6] text-[#4f6f2a]";
  return "border border-[#b7d2ee] bg-[#dceafa] text-[#2f6299]"; // 社招
}

// 岗位职能（产品/研发/…）= 次强特征，统一中性配色，每张卡片必显示。
const FUNCTION_STYLE = "border border-black/[0.08] bg-[#f0ece2] text-[#6b655a]";

export default function JobCard({ job, onActionChange, sessionNew }: Props) {
  const [acting, setActing] = useState(false);
  const [currentAction, setCurrentAction] = useState(job.user_action);
  const [actionError, setActionError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [insightOpen, setInsightOpen] = useState(false);
  const supabase = createBrowserClient();

  useEffect(() => {
    setCurrentAction(job.user_action);
  }, [job.user_action]);

  // 展示用 summary：解 HTML 实体 + 去标签（历史 greenhouse 行存的是实体编码 HTML，否则显示乱码）。
  const summary = useMemo(() => cleanSummary(job.summary), [job.summary]);
  // 优先用爬虫从完整 JD 抽取并入库的结构化列；列为空（历史行/未重抓）才回退旧的 summary 正则。
  const exp = useMemo(() => job.experience || extractExperience(summary), [job.experience, summary]);
  const edu = useMemo(() => job.education || extractEducation(summary), [job.education, summary]);
  const deadline = useMemo(
    () => job.deadline || extractDeadline(summary),
    [job.deadline, summary],
  );
  // 强特征标签：招聘类型穷尽落到 实习/校招/社招 之一（必显示）；职能粗分到 产品/研发/… （必显示）。
  const recruitType = useMemo(
    () => recruitmentCategory({ title: job.title, job_type: job.job_type, summary, jd_url: job.jd_url }),
    [job.title, job.job_type, summary, job.jd_url],
  );
  const jobFunction = useMemo(
    () => classifyJobFunction({ title: job.title, job_type: job.job_type, summary }),
    [job.title, job.job_type, summary],
  );
  // 新鲜度信任信号：last_seen_at 距今多久 → 「今天/X 天前确认在招」；>14 天转暖橙告警「可能已下线」。
  const freshness = useMemo(() => freshnessLabel(job.last_seen_at), [job.last_seen_at]);

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
        "group rounded-[1.35rem] border p-5 text-[#1a1714] transition duration-300 ease-out will-change-transform hover:-translate-y-1 motion-reduce:hover:translate-y-0",
        sessionNew
          ? "border-[#bcdcae] bg-[#eef6e0] ring-1 ring-[#cfe6b0] hover:bg-[#e8f3d6] hover:shadow-[0_26px_56px_-28px_rgba(60,90,30,0.4)]"
          : "border-black/[0.06] bg-white/70 shadow-[0_18px_44px_-30px_rgba(40,34,28,0.32)] hover:border-black/[0.1] hover:bg-white hover:shadow-[0_26px_56px_-26px_rgba(40,34,28,0.42)]",
      )}
    >
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-[#8a8275]">{job.company}</span>
            <span
              className={cn(
                "rounded-full px-2.5 py-1 text-xs font-semibold",
                recruitTypeStyle(recruitType),
              )}
            >
              {recruitType}
            </span>
            <span className={cn("rounded-full px-2.5 py-1 text-xs font-semibold", FUNCTION_STYLE)}>
              {jobFunction}
            </span>
            {sessionNew && (
              <span className="inline-flex items-center gap-1 rounded-full bg-[#dcefb4] px-2.5 py-1 text-xs font-semibold text-[#4f6f2a]">
                <Sparkle size={12} weight="fill" aria-hidden="true" />
                本次新发现
              </span>
            )}
            {isNew && !sessionNew && (
              <span className="rounded-full bg-[#cfe2f8] px-2.5 py-1 text-xs font-semibold text-[#2f6299]">
                新发现
              </span>
            )}
            {currentAction && (
              <span className="rounded-full bg-[#1a1714] px-2.5 py-1 text-xs font-semibold text-[#f7f1e6]">
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
              title="查看该公司的职业洞察（时机/上市/薪酬/路径/文化，社区聚合·非官方）"
              className="inline-flex items-center gap-1 rounded-full border border-[#cfc0e6] bg-[#efe9f8] px-2.5 py-1 text-xs font-medium text-[#6a4fa0] transition hover:border-[#bba9dd] hover:bg-[#e7def4]"
            >
              <Sparkle size={12} weight="fill" aria-hidden="true" />
              职业洞察
            </button>
          </div>

          <button
            type="button"
            onClick={handleView}
            className="mt-2 block max-w-full text-left text-xl font-semibold leading-snug text-[#1a1714] transition-colors hover:text-[#3f7cc0]"
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

          {freshness.label && (
            <p
              className={cn(
                "mt-2 text-xs font-medium",
                freshness.stale ? "text-[#9a6a2a]" : "text-[#8a8275]",
              )}
            >
              {freshness.label}
            </p>
          )}

          {summary && (
            <div className="mt-4">
              <p
                className={cn(
                  "whitespace-pre-line text-pretty text-sm leading-6 text-[#5f594e]",
                  !expanded && "line-clamp-3",
                )}
              >
                {summary}
              </p>
              {summary.length > 80 && (
                <button
                  type="button"
                  onClick={() => setExpanded((v) => !v)}
                  className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-[#3f7cc0] transition-colors hover:text-[#2f6299]"
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
                  className="rounded-full border border-[#cfe0f5] bg-[#e8f1fc] px-2.5 py-1 text-xs font-medium text-[#2f6299]"
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
                "rounded-xl px-3 py-2 text-center",
                job.match_score >= 50
                  ? "bg-[#1a1714] text-[#f7f1e6]"
                  : "border border-black/[0.06] bg-[#f4efe6] text-[#1a1714]",
              )}
            >
              <span className="block text-xs opacity-70">匹配度</span>
              <span className="tabular-nums text-2xl font-semibold leading-none">
                {job.match_score}
              </span>
            </div>
          )}

          <button
            type="button"
            onClick={handleView}
            className="inline-flex items-center justify-center gap-2 rounded-full bg-[#1a1714] px-4 py-2 text-sm font-semibold text-[#f7f1e6] transition duration-200 hover:bg-[#2b2520] active:scale-[0.98]"
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
            <span className="rounded-lg border border-[#e0b4ac] bg-[#f7e6e1] px-2 py-1 text-right text-xs text-[#9c4a3c]">
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
    <div className="flex min-w-0 items-center gap-2 rounded-xl border border-black/[0.06] bg-white/55 px-3 py-2">
      <Icon size={16} className="shrink-0 text-[#a39a8c]" aria-hidden="true" />
      <div className="min-w-0">
        <span className="mr-1 text-[#9a9184]">{label}</span>
        <span className="truncate font-medium text-[#3f3a33]">{value}</span>
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
          ? "bg-[#1a1714] text-[#f7f1e6]"
          : muted
            ? "text-[#8a8275] hover:bg-black/[0.05] hover:text-[#1a1714]"
            : "border border-black/[0.07] bg-white/70 text-[#3f3a33] hover:bg-white",
      )}
    >
      <Icon size={16} weight={active ? "fill" : "regular"} aria-hidden="true" />
      {label}
    </button>
  );
}

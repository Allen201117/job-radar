"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowSquareOut,
  BookmarkSimple,
  Briefcase,
  CalendarBlank,
  CaretDown,
  ChartBar,
  CheckCircle,
  GraduationCap,
  Hourglass,
  MapPin,
  Sparkle,
  XCircle,
} from "@phosphor-icons/react";
import {
  classifyJobFunction,
  recruitmentCategory,
} from "@/lib/china-keyword-expansion";
import { extractDeadline, extractEducation, extractExperience } from "@/lib/job-fields";
import { matchTier } from "@/lib/scoring";
import CompanyInsightDrawer from "@/components/CompanyInsightDrawer";
import {
  getCachedAvailability,
  requestInsightAvailability,
  subscribeAvailability,
  type InsightAvailability,
} from "@/lib/insight-client";
import { track } from "@/lib/track";
import type { MatchReason, ScoredJob } from "@/lib/types";
import type {
  OpportunityReason,
  OpportunityTier,
  FreshnessState,
  OpportunitySignal,
  OpportunitySignalType,
} from "@/lib/opportunities/types";
import { IGNORE_REASONS } from "@/lib/opportunities/feedback";
import { cleanSummary, cn, freshnessLabel } from "@/lib/utils";

interface Props {
  job: ScoredJob;
  onActionChange: (jobId: string, action: PrimaryAction | null) => void;
  // 本次会话刷新/发现新拿到的岗位 → 绿色高亮 + 「本次新发现」标
  sessionNew?: boolean;
  // 'opportunity' = 今日机会卡（档位/原因来自引擎，按钮=值得投/不适合/已投递）；
  // 'library'（默认）= 岗位库卡（matchTier 徽标 + match_reasons，按钮=值得投/标记投递/忽略）。
  // 命名统一：saved 动作全站统一叫「值得投」（与导航/saved 页同名），不再出现「收藏」双名。
  variant?: "library" | "opportunity";
  opportunityTier?: OpportunityTier;
  opportunityReasons?: OpportunityReason[];
  freshnessState?: FreshnessState;
  // v3：信号标签（≥1，护城河外显）+ 点击有效率埋点用的核验年龄。
  opportunitySignals?: OpportunitySignal[];
  opportunityCheckedAgeHours?: number | null;
}

// 信号 chip 配色：关键提醒醒目（暖橙），STILL_OPEN 绿（仍在招），CLOSED_OR_STALE 灰。
const SIGNAL_STYLE: Record<OpportunitySignalType, string> = {
  STILL_OPEN: "border-[#bcdcae] bg-[#eef6e0] text-[#4d6b2f] dark:border-[#a3d06a]/45 dark:bg-[#a3d06a]/20 dark:text-[#d2f0ad]",
  OPEN_UNVERIFIED: "border-[#e4d1a8] bg-[#f8efd9] text-[#8a6a2a] dark:border-[#e0b15a]/30 dark:bg-[#e0b15a]/12 dark:text-[#e0b15a]",
  DEADLINE_SOON: "border-[#f0d9a8] bg-[#fbf1de] text-[#9a6a1f] dark:border-[#e8b87f]/30 dark:bg-[#e8b87f]/12 dark:text-[#e8b87f]",
  CLOSED_OR_STALE: "border-black/[0.08] bg-[#f0ece2] text-[#6b655a] dark:border-white/10 dark:bg-white/[0.08] dark:text-[#b6ad9d]",
  CAMPUS_WINDOW: "border-[#cfe0f5] bg-[#e8f1fc] text-[#2f6299] dark:border-[#7fb2e8]/30 dark:bg-[#7fb2e8]/12 dark:text-[#7fb2e8]",
  NEWLY_DISCOVERED: "border-[#cfe0f5] bg-[#e8f1fc] text-[#2f6299] dark:border-[#7fb2e8]/30 dark:bg-[#7fb2e8]/12 dark:text-[#7fb2e8]",
  COMPANY_MOMENTUM: "border-[#cfe0f5] bg-[#e8f1fc] text-[#2f6299] dark:border-[#7fb2e8]/30 dark:bg-[#7fb2e8]/12 dark:text-[#7fb2e8]",
};

const OPPORTUNITY_TIER_LABEL: Record<OpportunityTier, string> = {
  high: "高匹配",
  related: "相关机会",
  explore: "拓展机会",
};

type PrimaryAction = "saved" | "ignored" | "applied";

const MATCH_REASON_LABELS = {
  role: "命中目标方向",
  location: "命中城市",
  keyword: "命中技能",
  company: "命中目标公司",
} satisfies Record<Exclude<MatchReason["type"], "freshness">, string>;

function matchReasonText(reason: MatchReason): string {
  if (reason.type === "freshness") return reason.value;
  return `${MATCH_REASON_LABELS[reason.type]}：${reason.value}`;
}

// 招聘类型（实习/校招/社招）= 强特征，三色区分，每张卡片必显示。
function recruitTypeStyle(t: string): string {
  if (t === "实习")
    return "border border-[#e7c98a] bg-[#fbeecb] text-[#8a6312] dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]";
  if (t === "校招")
    return "border border-[#bcdcae] bg-[#e6f2d6] text-[#4f6f2a] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]";
  return "border border-[#b7d2ee] bg-[#dceafa] text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]"; // 社招
}

// 岗位职能（产品/研发/…）= 次强特征，统一中性配色，每张卡片必显示。
const FUNCTION_STYLE =
  "border border-black/[0.08] bg-[#f0ece2] text-[#6b655a] dark:border-white/[0.1] dark:bg-white/[0.08] dark:text-[#b6ad9d]";

// 洞察按钮的点击前预告：实录(紫·有数量) / 岗位聚合派生(蓝·与抽屉派生标记同色) / 暂无(灰) / 加载中(中性紫)。
// 让用户点击前就知道有没有内容、是实录还是聚合，降低空抽屉点击。
function insightBadge(avail: InsightAvailability | null): {
  label: string;
  title: string;
  cls: string;
  derived: boolean;
} {
  if (!avail) {
    return {
      label: "职业洞察",
      title: "查看该公司的职业洞察",
      cls: "border-[#cfc0e6] bg-[#efe9f8] text-[#6a4fa0] hover:border-[#bba9dd] hover:bg-[#e7def4] dark:border-[#c3b1e6]/[0.30] dark:bg-[#c3b1e6]/[0.15] dark:text-[#c3b1e6] dark:hover:border-[#c3b1e6]/[0.45] dark:hover:bg-[#c3b1e6]/[0.22]",
      derived: false,
    };
  }
  if (avail.real > 0) {
    return {
      label: `洞察 ${avail.real}`,
      title: `查看该公司的 ${avail.real} 条职业洞察（实录·已核验）`,
      cls: "border-[#cfc0e6] bg-[#efe9f8] text-[#6a4fa0] hover:border-[#bba9dd] hover:bg-[#e7def4] dark:border-[#c3b1e6]/[0.30] dark:bg-[#c3b1e6]/[0.15] dark:text-[#c3b1e6] dark:hover:border-[#c3b1e6]/[0.45] dark:hover:bg-[#c3b1e6]/[0.22]",
      derived: false,
    };
  }
  if (avail.derived) {
    return {
      label: "岗位聚合",
      title: "查看据本平台在招岗位聚合出的洞察（暂无实录条目）",
      cls: "border-[#b7d2ee] bg-[#dceafa] text-[#2f6299] hover:border-[#9cc3ea] hover:bg-[#cfe0f5] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8] dark:hover:border-[#7fb2e8]/[0.45] dark:hover:bg-[#7fb2e8]/[0.22]",
      derived: true,
    };
  }
  return {
    label: "暂无洞察",
    title: "该公司暂无可展示的职业洞察（点击查看说明）",
    cls: "border-black/[0.08] bg-[#f0ece2] text-[#9a9184] hover:text-[#6b655a] dark:border-white/[0.1] dark:bg-white/[0.08] dark:text-[#837c70] dark:hover:text-[#b6ad9d]",
    derived: false,
  };
}

export default function JobCard({
  job,
  onActionChange,
  sessionNew,
  variant = "library",
  opportunityTier,
  opportunityReasons,
  freshnessState,
  opportunitySignals,
  opportunityCheckedAgeHours,
}: Props) {
  const isOpportunity = variant === "opportunity";
  const [acting, setActing] = useState(false);
  // 同步去重锁：state 是异步的，同一渲染周期内的连点会同时通过 `if (acting)`；用 ref 在调用入口同步挡住。
  const actingRef = useRef(false);
  const [currentAction, setCurrentAction] = useState(job.user_action);
  const [actionError, setActionError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [insightOpen, setInsightOpen] = useState(false);
  // 「不适合 / 忽略」原因面板（§8.2）：ignored 必须选一个原因才写入。
  const [reasonOpen, setReasonOpen] = useState(false);
  // 洞察按钮点击前预告状态：null=未知/加载中，real>0=有实录，derived=有岗位聚合派生。
  const [insightAvail, setInsightAvail] = useState<InsightAvailability | null>(() =>
    getCachedAvailability(job.company),
  );

  useEffect(() => {
    setCurrentAction(job.user_action);
  }, [job.user_action]);

  // 微批拉取该公司洞察可用性（同一列表的多张卡合并成一次请求），用于按钮上预告「洞察 N / 岗位聚合 / 暂无」。
  useEffect(() => {
    requestInsightAvailability(job.company);
    const update = () => setInsightAvail(getCachedAvailability(job.company));
    update();
    return subscribeAvailability(update);
  }, [job.company]);

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

  // 主动作走服务端 API（§8.1）：乐观更新 + 失败回滚；不再前端直连 Supabase。
  // 埋点改到 **API 成功后** 才发（失败不记成功，P0-4）；actingRef 同步去重，挡同一渲染周期内的重复请求。
  async function callActionApi(
    next: PrimaryAction | null,
    prev: PrimaryAction | null,
    reasonCode?: string,
  ) {
    if (actingRef.current) return;
    actingRef.current = true;
    setActionError("");
    setCurrentAction(next);
    onActionChange(job.id, next);
    setActing(true);
    try {
      const resp = await fetch(`/api/job-actions/${job.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: next, reason_code: reasonCode ?? null }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data?.ok) throw new Error(data?.error || `HTTP ${resp.status}`);
      // 成功后才发埋点
      if (isOpportunity) {
        if (next)
          track("opportunity_feedback", {
            action: next,
            reason_code: reasonCode ?? null,
            tier: opportunityTier ?? null,
            surface: "today",
          });
        else track("opportunity_undo", { previous_action: prev, surface: "today" });
      } else if (next) {
        track("job_action", { action: next, job_id: job.id });
      }
    } catch (e) {
      console.error("[job-card] action failed", e);
      setCurrentAction(prev);
      onActionChange(job.id, prev);
      setActionError("操作失败，已恢复原状态");
      setTimeout(() => setActionError(""), 2500);
    } finally {
      setActing(false);
      actingRef.current = false;
    }
  }

  // 值得投 / 已投递：点已选则取消（action=null）
  function handlePrimary(action: "saved" | "applied") {
    if (acting) return;
    const prev = currentAction as PrimaryAction | null;
    void callActionApi(prev === action ? null : action, prev);
  }

  // 不适合 / 忽略：已选则取消；否则先开原因面板（ignored 必须带原因）
  function handleIgnore() {
    if (acting) return;
    if (currentAction === "ignored") {
      void callActionApi(null, "ignored");
      return;
    }
    setReasonOpen(true);
  }

  function pickReason(code: string) {
    setReasonOpen(false);
    const prev = currentAction as PrimaryAction | null;
    void callActionApi("ignored", prev, code);
  }

  function handleView() {
    // 直接跳官网，瞬间打开——质量校验**不放在点击路径**（历史教训：同步核验门已废）。
    window.open(job.jd_url, "_blank", "noopener,noreferrer");
    if (isOpportunity) {
      track("opportunity_click", { job_id: job.id, tier: opportunityTier ?? null, surface: "today" });
      // 点击有效率埋点（01 spec §5）：记录点开那刻的核验年龄/新鲜度。
      track("opportunity_official_opened", {
        job_id: job.id,
        adapter: job.source_adapter ?? null,
        checked_age_hours: opportunityCheckedAgeHours ?? null,
        freshness: freshnessState ?? null,
        surface: "today",
      });
      // 背景单岗核验（非阻塞、封顶 2.5s）：判死标 expired + 服务端顺带打 job_liveness_at_click（分母）。
      void fetch(`/api/jobs/${job.id}/liveness`, { method: "POST", keepalive: true }).catch(() => {});
    } else track("job_click", { job_id: job.id });
    void fetch(`/api/job-actions/${job.id}/view`, { method: "POST" }).catch(() => {});
  }

  const isNew =
    job.first_seen_at &&
    (Date.now() - new Date(job.first_seen_at).getTime()) / 86400000 <= 3;
  const posted = job.posted_at
    ? new Date(job.posted_at).toLocaleDateString("zh-CN")
    : "未知";
  // 无量纲匹配分 → 可解释三档徽标（阈值在 lib/scoring.ts，前端只消费）。
  const tier = matchTier(job.match_score);
  const matchReasons = job.match_reasons || [];

  return (
    <article
      className={cn(
        // cv-auto = content-visibility 性能护栏；glass-card = 暖光液态玻璃；
        // 去掉常驻 will-change-transform（几百张卡片各自占一个 GPU 层会撑爆显存→崩页），hover 位移交给 transition。
        "group cursor-target bento-glow cv-auto glass-card rounded-[1.35rem] border p-5 text-[#1a1714] transition duration-300 ease-out hover:-translate-y-1 motion-reduce:hover:translate-y-0 dark:text-[#f3ecdf]",
        sessionNew
          ? "border-[#bcdcae] bg-[#eef6e0]/75 ring-1 ring-[#cfe6b0] hover:bg-[#eef6e0]/90 hover:shadow-[0_26px_56px_-28px_rgba(60,90,30,0.4)] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.08] dark:ring-[#a3d06a]/[0.25] dark:hover:bg-[#a3d06a]/[0.12]"
          : "border-black/[0.06] bg-white/55 shadow-[0_18px_44px_-30px_rgba(40,34,28,0.32)] hover:border-black/[0.1] hover:bg-white/80 hover:shadow-[0_26px_56px_-26px_rgba(40,34,28,0.42)] dark:border-white/[0.1] dark:bg-white/[0.05] dark:hover:border-white/20 dark:hover:bg-white/[0.08]",
      )}
    >
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-[#8a8275] dark:text-[#b6ad9d]">{job.company}</span>
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
            {job.sponsorship_signal === "available" && (
              <span className="inline-flex items-center gap-1 rounded-full border border-[#bcdcae] bg-[#eef6e0] px-2.5 py-1 text-xs font-semibold text-[#4d6b2f] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.15] dark:text-[#d2f0ad]">
                <CheckCircle size={12} weight="fill" aria-hidden="true" />
                提供 Sponsorship
              </span>
            )}
            {job.sponsorship_signal === "none" && (
              <span className="inline-flex items-center gap-1 rounded-full border border-[#f0d9a8] bg-[#fbf1de] px-2.5 py-1 text-xs font-semibold text-[#9a6a1f] dark:border-[#e8b87f]/[0.30] dark:bg-[#e8b87f]/[0.15] dark:text-[#e8b87f]">
                <XCircle size={12} weight="fill" aria-hidden="true" />
                不提供 Sponsorship
              </span>
            )}
            {sessionNew && (
              <span className="inline-flex items-center gap-1 rounded-full bg-[#dcefb4] px-2.5 py-1 text-xs font-semibold text-[#4f6f2a] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]">
                <Sparkle size={12} weight="fill" aria-hidden="true" />
                本次新发现
              </span>
            )}
            {isNew && !sessionNew && (
              <span className="rounded-full bg-[#cfe2f8] px-2.5 py-1 text-xs font-semibold text-[#2f6299] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]">
                新发现
              </span>
            )}
            {currentAction && (
              <span className="rounded-full bg-[#1a1714] px-2.5 py-1 text-xs font-semibold text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]">
                {currentAction === "saved"
                  ? "已加入值得投"
                  : currentAction === "applied"
                    ? "已投递"
                    : currentAction === "ignored"
                      ? "已忽略"
                      : ""}
              </span>
            )}
            {(() => {
              const badge = insightBadge(insightAvail);
              return (
                <button
                  type="button"
                  onClick={() => setInsightOpen(true)}
                  title={badge.title}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium transition",
                    badge.cls,
                  )}
                >
                  {badge.derived ? (
                    <ChartBar size={12} weight="fill" aria-hidden="true" />
                  ) : (
                    <Sparkle size={12} weight="fill" aria-hidden="true" />
                  )}
                  {badge.label}
                </button>
              );
            })()}
          </div>

          <button
            type="button"
            onClick={handleView}
            className="mt-2 block max-w-full text-left text-xl font-semibold leading-snug text-[#1a1714] transition-colors hover:text-[#3f7cc0] dark:text-[#f3ecdf] dark:hover:text-[#7fb2e8]"
          >
            <span className="text-balance">{job.title}</span>
          </button>

          <div className="mt-4 grid grid-cols-2 gap-2 text-sm xl:grid-cols-3">
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
                freshness.stale ? "text-[#9a6a2a] dark:text-[#e0b15a]" : "text-[#8a8275] dark:text-[#9a9184]",
              )}
            >
              {freshness.label}
            </p>
          )}

          {summary && (
            <div className="mt-4">
              <p
                className={cn(
                  "whitespace-pre-line text-pretty text-sm leading-6 text-[#5f594e] dark:text-[#b6ad9d]",
                  !expanded && "line-clamp-3",
                )}
              >
                {summary}
              </p>
              {summary.length > 80 && (
                <button
                  type="button"
                  onClick={() => setExpanded((v) => !v)}
                  className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-[#3f7cc0] transition-colors hover:text-[#2f6299] dark:text-[#7fb2e8] dark:hover:text-[#a8cdf0]"
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

          {isOpportunity ? (
            <>
              {opportunitySignals && opportunitySignals.length > 0 && (
                <div className="mt-4 flex flex-wrap items-center gap-1.5">
                  {opportunitySignals.map((s, i) => (
                    <span
                      key={`${s.type}:${i}`}
                      className={cn("rounded-full border px-2.5 py-1 text-xs font-semibold", SIGNAL_STYLE[s.type])}
                    >
                      {s.isCritical ? "● " : ""}
                      {s.label}
                    </span>
                  ))}
                </div>
              )}
              {opportunityTier && (
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  <span
                    title="按你的目标、简历与岗位新鲜度评估的匹配档位"
                    className={cn(
                      "rounded-full px-2.5 py-1 text-xs font-semibold",
                      opportunityTier === "high"
                        ? "bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                        : "border border-black/[0.08] bg-[#f0ece2] text-[#6b655a] dark:border-white/[0.1] dark:bg-white/[0.08] dark:text-[#b6ad9d]",
                    )}
                  >
                    {OPPORTUNITY_TIER_LABEL[opportunityTier]}
                  </span>
                </div>
              )}
              {opportunityReasons && opportunityReasons.length > 0 && (
                <ul className="mt-3 flex flex-wrap gap-1.5">
                  {opportunityReasons.map((r, i) => (
                    <li
                      key={`${r.type}:${i}`}
                      className="inline-flex items-center gap-1 rounded-full border border-[#cfe0f5] bg-[#e8f1fc] px-2.5 py-1 text-xs font-medium text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.12] dark:text-[#7fb2e8]"
                    >
                      <Sparkle size={11} weight="fill" aria-hidden="true" />
                      {r.label}
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <>
              {(tier.label || job.matched_keywords.length > 0) && (
                <div className="mt-4 flex flex-wrap items-center gap-1.5">
                  {tier.label && (
                    <span
                      title="根据你的求职偏好与简历画像评估的匹配档位"
                      className={cn(
                        "rounded-full px-2.5 py-1 text-xs font-semibold",
                        tier.level === "high"
                          ? "bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                          : "border border-black/[0.08] bg-[#f0ece2] text-[#6b655a] dark:border-white/[0.1] dark:bg-white/[0.08] dark:text-[#b6ad9d]",
                      )}
                    >
                      {tier.label}
                    </span>
                  )}
                  {job.matched_keywords.slice(0, 3).map((kw) => (
                    <span
                      key={kw}
                      className="rounded-full border border-[#cfe0f5] bg-[#e8f1fc] px-2.5 py-1 text-xs font-medium text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.12] dark:text-[#7fb2e8]"
                    >
                      {kw}
                    </span>
                  ))}
                </div>
              )}

              {tier.level !== "none" && matchReasons.length > 0 && (
                <details className="mt-3 rounded-xl border border-black/[0.07] bg-white/45 px-3.5 py-2.5 open:bg-white/65 [&[open]_.match-reason-caret]:rotate-180 dark:border-white/[0.1] dark:bg-white/[0.04] dark:open:bg-white/[0.07]">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-[#5f594e] transition-colors hover:text-[#1a1714] [&::-webkit-details-marker]:hidden dark:text-[#b6ad9d] dark:hover:text-[#f3ecdf]">
                    <span className="inline-flex items-center gap-1.5">
                      <Sparkle size={14} weight="fill" aria-hidden="true" />
                      为什么推荐
                    </span>
                    <CaretDown
                      className="match-reason-caret size-4 shrink-0 transition-transform"
                      aria-hidden="true"
                    />
                  </summary>
                  <ul className="mt-2.5 space-y-1.5 border-t border-black/[0.06] pt-2.5 text-sm text-[#5f594e] dark:border-white/[0.08] dark:text-[#b6ad9d]">
                    {matchReasons.map((reason, index) => (
                      <li
                        key={`${reason.type}:${reason.value}:${index}`}
                        className="flex items-start gap-2"
                      >
                        <span
                          className="mt-[0.45rem] size-1.5 shrink-0 rounded-full bg-[#7aa84b] dark:bg-[#a3d06a]"
                          aria-hidden="true"
                        />
                        <span>{matchReasonText(reason)}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </div>

        {/* 移动端：官网详情整宽 + 三个操作并排一行；桌面端（lg）回到右侧竖排。 */}
        <div className="flex shrink-0 flex-col gap-2 lg:w-36">
          <button
            type="button"
            onClick={handleView}
            className="inline-flex items-center justify-center gap-2 rounded-full bg-[#1a1714] px-4 py-2.5 text-sm font-semibold text-[#f7f1e6] transition duration-200 hover:bg-[#2b2520] active:scale-[0.98] lg:py-2 dark:bg-[#f3ecdf] dark:text-[#16130f] dark:hover:bg-[#e8ddca]"
          >
            官网详情
            <ArrowSquareOut size={16} weight="bold" aria-hidden="true" />
          </button>
          <div className="grid grid-cols-3 gap-2 lg:grid-cols-1">
            <ActionButton
              active={currentAction === "saved"}
              disabled={acting}
              onClick={() => handlePrimary("saved")}
              icon={BookmarkSimple}
              label={currentAction === "saved" ? "已加入值得投" : "值得投"}
            />
            <ActionButton
              active={currentAction === "applied"}
              disabled={acting}
              onClick={() => handlePrimary("applied")}
              icon={CheckCircle}
              label={currentAction === "applied" ? "已投递" : "标记投递"}
            />
            <ActionButton
              muted
              active={currentAction === "ignored"}
              disabled={acting}
              onClick={handleIgnore}
              icon={XCircle}
              label={currentAction === "ignored" ? "已忽略" : isOpportunity ? "不适合" : "忽略"}
            />
          </div>

          {reasonOpen && (
            <div className="rounded-xl border border-black/[0.08] bg-white/95 p-2 shadow-lg dark:border-white/[0.12] dark:bg-[#16130f]/95">
              <p className="px-1 pb-1 text-xs font-medium text-[#8a8275] dark:text-[#9a9184]">
                为什么不适合？
              </p>
              <div className="flex flex-col gap-0.5">
                {IGNORE_REASONS.map((r) => (
                  <button
                    key={r.code}
                    type="button"
                    onClick={() => pickReason(r.code)}
                    className="rounded-lg px-2 py-1.5 text-left text-xs text-[#3f3a33] transition hover:bg-black/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.06]"
                  >
                    {r.label}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setReasonOpen(false)}
                  className="mt-0.5 rounded-lg px-2 py-1.5 text-left text-xs font-medium text-[#8a8275] transition hover:bg-black/[0.05] dark:text-[#9a9184] dark:hover:bg-white/[0.06]"
                >
                  取消
                </button>
              </div>
            </div>
          )}
          {actionError && (
            <span className="rounded-lg border border-[#e0b4ac] bg-[#f7e6e1] px-2 py-1 text-xs text-[#9c4a3c] lg:text-right dark:border-[#7a392e]/[0.60] dark:bg-[#3a201a] dark:text-[#e6a99f]">
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
    <div className="flex min-w-0 items-center gap-2 rounded-xl border border-black/[0.06] bg-white/55 px-3 py-2 dark:border-white/[0.12] dark:bg-white/[0.07]">
      <Icon size={16} className="shrink-0 text-[#a39a8c] dark:text-[#a89f90]" aria-hidden="true" />
      <div className="min-w-0">
        <span className="mr-1 text-[#9a9184] dark:text-[#aaa093]">{label}</span>
        <span className="truncate font-medium text-[#3f3a33] dark:text-[#f3ecdf]">{value}</span>
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
        "inline-flex items-center justify-center gap-1 rounded-full px-2 py-2.5 text-[12px] font-medium transition duration-200 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 sm:gap-2 sm:px-4 sm:py-2 sm:text-sm",
        active
          ? "bento-selected bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
          : muted
            ? "text-[#8a8275] hover:bg-black/[0.05] hover:text-[#1a1714] dark:text-[#9a9184] dark:hover:bg-white/[0.05] dark:hover:text-[#f3ecdf]"
            : "border border-black/[0.07] bg-white/70 text-[#3f3a33] hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.08]",
      )}
    >
      <Icon size={16} weight={active ? "fill" : "regular"} className="shrink-0" aria-hidden="true" />
      {label}
    </button>
  );
}

"use client";

// 校招专区客户端：公司卡 + 徽章 + 校招/实习切换 + 城市/学历/职能筛选 + 展开分组渲染 JobCard + 展示时探活。
// 数据已由服务端按必投清单公司聚合好（app/campus/page.tsx → getCampusZone），本组件只做客户端交互层。
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Briefcase,
  CaretDown,
  Flag,
  GraduationCap,
  MapPin,
} from "@phosphor-icons/react";
import { EmptyPanel } from "@/components/ProductChrome";
import CompanyLogo from "@/components/CompanyLogo";
import CompanyInsightDrawer from "@/components/CompanyInsightDrawer";
import JobCard from "@/components/JobCard";
import SaveToast, { type SaveState } from "@/components/SaveToast";
import { classifyJobFunction } from "@/lib/china-keyword-expansion";
import {
  requestInsightAvailability,
  getCachedAvailability,
  subscribeAvailability,
} from "@/lib/insight-client";
import { groupCampusJobs } from "@/lib/campus-zone";
import { cn } from "@/lib/utils";
import type { CampusCompanyRow } from "@/lib/jobs-store/read";
import type { WindowState } from "@/lib/campus-zone";
import type { ScoredJob } from "@/lib/types";
import type { CampusTimeline } from "@/lib/recruitment-cycle";

export type CampusCardData = CampusCompanyRow & {
  window: WindowState;
  nearestDeadlineMs: number | null;
  timeline: CampusTimeline | null;
};

type RecruitMode = "campus" | "intern";
type PrimaryAction = "saved" | "ignored" | "applied";

const WINDOW_BADGE: Record<
  WindowState["state"],
  { icon: string; label: string; className: string }
> = {
  hiring: {
    icon: "🟢",
    label: "招聘中",
    className:
      "border border-[#bcdcae] dark:border-[#a3d06a]/[0.30] bg-[#e6f2d6] dark:bg-[#a3d06a]/[0.15] text-[#4f6f2a] dark:text-[#a3d06a]",
  },
  no_campus_now: {
    icon: "⚪",
    label: "当前未观测到在招校招岗",
    className:
      "border border-black/[0.08] dark:border-white/[0.1] bg-[#f4efe6] dark:bg-[#16130f] text-[#8a8275] dark:text-[#9a9184]",
  },
  stale: {
    icon: "⏳",
    label: "数据待更新",
    className:
      "border border-[#e7c98a] dark:border-[#e0b15a]/[0.30] bg-[#fbeecb] dark:bg-[#e0b15a]/[0.15] text-[#8a6312] dark:text-[#e0b15a]",
  },
  not_ingested: {
    icon: "⚙️",
    label: "待接入",
    className:
      "border border-[#b7d2ee] dark:border-[#7fb2e8]/[0.30] bg-[#dceafa] dark:bg-[#7fb2e8]/[0.15] text-[#2f6299] dark:text-[#7fb2e8]",
  },
};

// ⚙️ 待接入卡不向用户暴露子原因（no_source / source_only_social）——只在 tooltip 里说一句通用文案。
const NOT_INGESTED_TOOLTIP = "该公司校招源接入中";

function WindowBadge({ window }: { window: WindowState }) {
  const badge = WINDOW_BADGE[window.state];
  const title = window.state === "not_ingested" ? NOT_INGESTED_TOOLTIP : undefined;
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-medium ${badge.className}`}
    >
      <span aria-hidden="true">{badge.icon}</span>
      {badge.label}
    </span>
  );
}

// 把校招专区聚合 SQL 返回的原始岗位行（snake_case，无打分字段）适配成 JobCard 需要的 ScoredJob 形状。
// 该查询没有取 user_action/salary_text/source_id 等字段（专区场景不需要个性化打分），一律填安全默认值；
// match_score=0 + matched_keywords=[] → JobCard 不渲染匹配档位徽标（本区靠窗口徽章，不是相关性打分）。
function toScoredJob(job: any): ScoredJob {
  return {
    id: job.id,
    source_id: job.source_id ?? null,
    company: job.company,
    title: job.title,
    location: job.city ?? null,
    country_code: job.country_code ?? null,
    job_scope: job.job_scope ?? null,
    job_type: job.job_type ?? null,
    summary: job.summary ?? null,
    sponsorship_signal: job.sponsorship_signal ?? null,
    jd_url: job.jd_url,
    apply_url: job.apply_url ?? null,
    salary_text: job.salary_text ?? null,
    posted_at: job.posted_at ?? null,
    experience: job.experience ?? null,
    education: job.education ?? null,
    deadline: job.deadline ?? null,
    first_seen_at: job.first_seen_at,
    last_seen_at: job.last_seen_at,
    enrich_checked_at: job.enrich_checked_at ?? null,
    confirmed_closed_at: job.confirmed_closed_at ?? null,
    status: job.status || "active",
    content_hash: job.content_hash ?? null,
    created_at: job.created_at || job.first_seen_at,
    match_score: 0,
    matched_keywords: [],
    hidden_reason: null,
    user_action: null,
    source_adapter: job.source_adapter ?? null,
  };
}

interface CampusFilters {
  city: string;
  education: string;
  jobFunction: string;
}

const EMPTY_FILTERS: CampusFilters = { city: "", education: "", jobFunction: "" };

type DisputeReason = "not_campus" | "dead_link" | "closed";

const DISPUTE_REASONS: { reason: DisputeReason; label: string }[] = [
  { reason: "not_campus", label: "这不是校招" },
  { reason: "dead_link", label: "链接失效" },
  { reason: "closed", label: "已结束" },
];

export default function CampusClient({
  cards,
  industries,
  hasIndustry,
}: {
  cards: CampusCardData[];
  industries: string[];
  hasIndustry: boolean;
}) {
  const [mode, setMode] = useState<RecruitMode>("campus");
  const [filters, setFilters] = useState<CampusFilters>(EMPTY_FILTERS);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // 公司洞察抽屉（P3a 外露）：公司卡级只拉一次可用性（比每个 JobCard 各拉更省），暂无实录/派生的公司不给点。
  const [insightCompany, setInsightCompany] = useState<string | null>(null);
  const [, forceAvailTick] = useState(0);
  useEffect(() => {
    cards.forEach((c) => requestInsightAvailability(c.company));
    const unsub = subscribeAvailability(() => forceAvailTick((n) => n + 1));
    return unsub;
  }, [cards]);

  function toggleExpand(pattern: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(pattern)) next.delete(pattern);
      else next.add(pattern);
      return next;
    });
  }

  // 当前态（校招/实习）下每家公司的原始岗位列表——先按 mode 取桶，其余步骤共用。
  const jobsByMode = useMemo(
    () => cards.map((c) => (mode === "campus" ? c.campusJobs : c.internJobs)),
    [cards, mode],
  );

  // 筛选下拉的候选值：从当前态全部岗位里收集真实出现过的城市/学历，避免造出库里没有的空选项。
  // 职能改用 classifyJobFunction 现算（岗位表没有结构化职能列，标题/summary 分类是唯一可信来源）。
  const { cityOptions, educationOptions, functionOptions } = useMemo(() => {
    const cities = new Set<string>();
    const edus = new Set<string>();
    const fns = new Set<string>();
    for (const jobs of jobsByMode) {
      for (const j of jobs) {
        if (j.city) cities.add(String(j.city).trim());
        if (j.education) edus.add(String(j.education).trim());
        fns.add(classifyJobFunction({ title: j.title, job_type: j.job_type, summary: j.summary }));
      }
    }
    return {
      cityOptions: Array.from(cities).filter(Boolean).sort(),
      educationOptions: Array.from(edus).filter(Boolean).sort(),
      functionOptions: Array.from(fns).filter(Boolean).sort(),
    };
  }, [jobsByMode]);

  function passesFilters(job: any): boolean {
    if (filters.city && String(job.city || "").trim() !== filters.city) return false;
    if (filters.education && String(job.education || "").trim() !== filters.education) return false;
    if (
      filters.jobFunction &&
      classifyJobFunction({ title: job.title, job_type: job.job_type, summary: job.summary }) !== filters.jobFunction
    )
      return false;
    return true;
  }

  // 每家公司在当前态 + 当前筛选下真正会展示的岗位（供卡面计数与展开区共用，口径统一）。
  const filteredJobsByPattern = useMemo(() => {
    const map = new Map<string, any[]>();
    cards.forEach((card, i) => {
      map.set(card.pattern, jobsByMode[i].filter(passesFilters));
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cards, jobsByMode, filters]);

  const hasActiveFilter = Boolean(filters.city || filters.education || filters.jobFunction);

  // 展示时探活（②层，复刻 app/jobs/jobs-client.tsx）：对当前展开公司里可见的岗位批量探活，
  // 死的当场从渲染里隐藏。deadIds 全局共享（同一岗位 id 不会同时出现在两家公司下）。
  const [deadIds, setDeadIds] = useState<Set<string>>(new Set());
  const livenessRequested = useRef<Set<string>>(new Set());
  useEffect(() => {
    const visibleIds: string[] = [];
    expanded.forEach((pattern) => {
      const jobs = filteredJobsByPattern.get(pattern) || [];
      for (const j of jobs) {
        if (j.id) visibleIds.push(j.id);
      }
    });
    const ids = visibleIds
      .filter((id) => !livenessRequested.current.has(id) && !deadIds.has(id))
      .slice(0, 25);
    if (ids.length === 0) return;
    ids.forEach((id) => livenessRequested.current.add(id));
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/jobs/liveness-check", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids }),
        });
        const data = await resp.json();
        if (!cancelled && data?.ok && Array.isArray(data.dead) && data.dead.length) {
          setDeadIds((prev) => {
            const next = new Set(prev);
            (data.dead as string[]).forEach((id: string) => next.add(id));
            return next;
          });
        }
      } catch {
        // 静默：探不动就不动，后台 sweep/审计兜底
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded, filteredJobsByPattern]);

  // JobCard 要求的回调；本区岗位不预取 job_actions（专区场景无需个性化打分/回填 user_action），
  // 值得投/已投递/忽略仍会经 JobCard 内部走 /api/job-actions 真实写库，只是不需要在此处再镜像一份状态。
  function handleActionChange(_jobId: string, _action: PrimaryAction | null) {}

  // 用户纠错入口（这不是校招/链接失效/已结束）：写 /api/campus-zone/dispute → events 复核队列。
  // 只跟踪「哪张卡的反馈菜单展开」+ 一个共享 SaveToast 提交态，不镜像已反馈的岗位集合（允许重复反馈）。
  const [disputeOpenId, setDisputeOpenId] = useState<string | null>(null);
  const [disputeSaveState, setDisputeSaveState] = useState<SaveState>("idle");

  async function submitDispute(jobId: string, reason: DisputeReason) {
    setDisputeOpenId(null);
    setDisputeSaveState("saving");
    try {
      const resp = await fetch("/api/campus-zone/dispute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId, reason }),
      });
      const data = await resp.json().catch(() => null);
      setDisputeSaveState(resp.ok && data?.ok ? "done" : "error");
    } catch {
      setDisputeSaveState("error");
    }
  }

  return (
    <div className="mt-8 space-y-6 text-[#1a1714] dark:text-[#f3ecdf]">
      {!hasIndustry && (
        <p className="rounded-xl border border-[#cfe0f5] dark:border-[#7fb2e8]/[0.30] bg-[#e8f1fc] dark:bg-[#7fb2e8]/[0.15] px-4 py-3 text-sm leading-6 text-[#2f6299] dark:text-[#7fb2e8]">
          你还没设置简历行业，当前按默认行业展示。到
          <Link href="/preferences" className="mx-1 underline underline-offset-2 hover:text-[#1a1714] dark:hover:text-[#f3ecdf]">
            偏好设置
          </Link>
          完善简历行业，可精准锁定你的目标公司。
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-[#5f594e] dark:text-[#b6ad9d]">
          已接入官方校招源并持续验证的岗位 · 按行业「{industries.join("、")}」匹配 {cards.length} 家必投目标公司
        </p>
        {/* 校招 / 实习切换：驱动卡面计数、展开区与探活取哪个桶。 */}
        <div className="inline-flex shrink-0 rounded-full border border-black/[0.08] bg-white/60 p-1 dark:border-white/[0.1] dark:bg-white/[0.05]">
          {(["campus", "intern"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={cn(
                "rounded-full px-3.5 py-1.5 text-sm font-medium transition",
                mode === m
                  ? "bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                  : "text-[#8a8275] hover:text-[#1a1714] dark:text-[#9a9184] dark:hover:text-[#f3ecdf]",
              )}
            >
              {m === "campus" ? "校招" : "实习"}
            </button>
          ))}
        </div>
      </div>

      {/* 筛选条：城市/学历/职能三个下拉，选项来自当前态真实出现过的值——不造空筛选。
          届别（应届 xxxx 届）：jobs 表没有结构化届别字段（爬虫未落库），本轮不做，避免拿标题正则臆造出不准的届别筛选。 */}
      <div className="surface flex flex-wrap items-end gap-3 p-4 sm:p-5">
        <FilterSelect
          icon={MapPin}
          label="城市"
          value={filters.city}
          onChange={(v) => setFilters((f) => ({ ...f, city: v }))}
          options={cityOptions}
          allLabel="全部城市"
        />
        <FilterSelect
          icon={GraduationCap}
          label="学历"
          value={filters.education}
          onChange={(v) => setFilters((f) => ({ ...f, education: v }))}
          options={educationOptions}
          allLabel="学历不限"
        />
        <FilterSelect
          icon={Briefcase}
          label="职能"
          value={filters.jobFunction}
          onChange={(v) => setFilters((f) => ({ ...f, jobFunction: v }))}
          options={functionOptions}
          allLabel="全部职能"
        />
        {hasActiveFilter && (
          <button
            type="button"
            onClick={() => setFilters(EMPTY_FILTERS)}
            className="rounded-full border border-black/[0.08] bg-white/70 px-3.5 py-2 text-sm font-medium text-[#5f594e] transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d] dark:hover:bg-white/[0.08]"
          >
            清空筛选
          </button>
        )}
      </div>

      {cards.length === 0 ? (
        <EmptyPanel title="暂无匹配公司" description="当前行业下没有必投清单公司，换一个行业试试。" />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {cards.map((card) => {
            const isExpanded = expanded.has(card.pattern);
            const totalCount = mode === "campus" ? card.campusJobs.length : card.internJobs.length;
            const filteredJobs = filteredJobsByPattern.get(card.pattern) || [];
            const groups = isExpanded ? groupCampusJobs(filteredJobs) : [];
            const modeLabel = mode === "campus" ? "校招" : "实习";

            return (
              <div key={card.pattern} className="contents">
                <div className="surface flex flex-col gap-3 p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <CompanyLogo company={card.company} size={28} />
                      <h3 className="min-w-0 truncate text-[15px] font-semibold leading-tight">{card.company}</h3>
                    </div>
                    <WindowBadge window={card.window} />
                  </div>
                  {card.timeline && (
                    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12px] leading-5 text-[#8a8275] dark:text-[#9a9184]">
                      <span className="inline-flex items-center gap-1 rounded-md border border-[#b7d2ee] bg-[#dceafa] px-1.5 py-0.5 font-medium text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]">
                        据往年
                      </span>
                      <span>{card.timeline.gradClass}</span>
                      {card.timeline.batchBits.map((bit) => (
                        <span key={bit}>· {bit}</span>
                      ))}
                      {card.timeline.phaseLabel && (
                        <span className="font-medium text-[#8a6312] dark:text-[#e0b15a]">
                          · {card.timeline.phaseLabel}
                        </span>
                      )}
                    </div>
                  )}
                  <p className="text-sm text-[#5f594e] dark:text-[#b6ad9d]">
                    {totalCount > 0
                      ? `${totalCount} 个${modeLabel}在招岗位${
                          hasActiveFilter && isExpanded ? ` · 筛选后 ${filteredJobs.length} 个` : ""
                        }`
                      : `暂无${modeLabel}在招岗位`}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    {totalCount > 0 && (
                      <button
                        type="button"
                        onClick={() => toggleExpand(card.pattern)}
                        aria-expanded={isExpanded}
                        className="inline-flex items-center justify-center gap-1.5 rounded-full border border-black/[0.08] bg-white/70 px-3.5 py-1.5 text-sm font-medium text-[#3f3a33] transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.08]"
                      >
                        {isExpanded ? "收起岗位" : "展开岗位"}
                        <CaretDown
                          className={cn("size-4 transition-transform", isExpanded && "rotate-180")}
                          aria-hidden="true"
                        />
                      </button>
                    )}
                    {(() => {
                      // P3a：公司卡级洞察入口。有实录(real>0)或岗位聚合派生才显，避免空抽屉。
                      const avail = getCachedAvailability(card.company);
                      if (!avail || (!avail.real && !avail.derived)) return null;
                      return (
                        <button
                          type="button"
                          onClick={() => setInsightCompany(card.company)}
                          className="inline-flex items-center justify-center gap-1.5 rounded-full border border-black/[0.08] bg-white/70 px-3.5 py-1.5 text-sm font-medium text-[#3f3a33] transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.08]"
                        >
                          {avail.real > 0 ? `公司洞察 ${avail.real}` : "公司洞察 · 岗位聚合"}
                        </button>
                      );
                    })()}
                  </div>
                </div>

                {isExpanded && (
                  <div className="sm:col-span-2 lg:col-span-3">
                    {groups.length === 0 ? (
                      <EmptyPanel title="当前筛选下没有匹配岗位" description="换一个城市/学历/职能试试，或清空筛选。" />
                    ) : (
                      <div className="space-y-5">
                        {groups.map((group) => {
                          const visibleJobs = group.jobs.filter((j: any) => !deadIds.has(j.id));
                          if (visibleJobs.length === 0) return null;
                          return (
                            <div key={group.key} className="space-y-3">
                              <h4 className="flex items-center gap-1.5 text-sm font-semibold text-[#8a8275] dark:text-[#9a9184]">
                                <MapPin size={14} weight="fill" aria-hidden="true" />
                                {group.label} · {visibleJobs.length}
                              </h4>
                              <div className="space-y-3">
                                {visibleJobs.map((job: any) => (
                                  <div key={job.id} className="space-y-1.5">
                                    <JobCard job={toScoredJob(job)} onActionChange={handleActionChange} />
                                    <JobDisputeControl
                                      isOpen={disputeOpenId === job.id}
                                      onToggle={() =>
                                        setDisputeOpenId((cur) => (cur === job.id ? null : job.id))
                                      }
                                      onSubmit={(reason) => submitDispute(job.id, reason)}
                                    />
                                  </div>
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                    {deadIds.size > 0 && (
                      <p className="mt-3 text-xs text-[#8a8275] dark:text-[#9a9184]">
                        实时复核拦下 {Array.from(deadIds).filter((id) => filteredJobs.some((j) => j.id === id)).length} 个
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <SaveToast
        state={disputeSaveState}
        savingText="提交中…"
        doneText="已收到，感谢反馈"
        errorText="提交失败，请重试"
        onDismiss={() => setDisputeSaveState("idle")}
      />

      {insightCompany && (
        <CompanyInsightDrawer
          company={insightCompany}
          open={!!insightCompany}
          onClose={() => setInsightCompany(null)}
        />
      )}
    </div>
  );
}

// 单个岗位的反馈入口：点「反馈」展开三个理由 chip，选中即提交。不改 JobCard，独立渲染在卡片下方。
function JobDisputeControl({
  isOpen,
  onToggle,
  onSubmit,
}: {
  isOpen: boolean;
  onToggle: () => void;
  onSubmit: (reason: DisputeReason) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 px-1">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        className="inline-flex items-center gap-1 rounded-full px-1.5 py-1 text-xs font-medium text-[#8a8275] transition hover:text-[#5f594e] dark:text-[#9a9184] dark:hover:text-[#d9d0c2]"
      >
        <Flag size={12} weight="bold" aria-hidden="true" />
        反馈
      </button>
      {isOpen &&
        DISPUTE_REASONS.map((r) => (
          <button
            key={r.reason}
            type="button"
            onClick={() => onSubmit(r.reason)}
            className="rounded-full border border-black/[0.08] bg-white/70 px-2.5 py-1 text-xs font-medium text-[#5f594e] transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d] dark:hover:bg-white/[0.08]"
          >
            {r.label}
          </button>
        ))}
    </div>
  );
}

function FilterSelect({
  icon: Icon,
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  icon: typeof MapPin;
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  allLabel: string;
}) {
  return (
    <label className="flex min-w-[9rem] flex-1 flex-col gap-1 text-xs font-medium text-[#8a8275] dark:text-[#9a9184] sm:flex-none">
      <span className="inline-flex items-center gap-1.5">
        <Icon size={14} weight="fill" aria-hidden="true" />
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-xl border border-black/[0.09] dark:border-white/[0.1] bg-white dark:bg-[#1e1a15] px-3 py-2 text-sm text-[#1a1714] dark:text-[#f3ecdf] transition duration-200 focus:border-[#1a1714]/55 dark:focus:border-white/55 focus:outline-none"
      >
        <option value="">{allLabel}</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </label>
  );
}

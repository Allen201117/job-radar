"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowSquareOut,
  Buildings,
  CalendarBlank,
  ChartLineUp,
  ClockCounterClockwise,
  Flag,
  Path,
  Scales,
  ShieldCheck,
  Sparkle,
  UsersThree,
  X,
} from "@phosphor-icons/react";
import {
  fetchCompanyInsights,
  type CompanyInsightResponse,
} from "@/lib/insight-client";
import {
  formatFinancialChips,
  formatHiringSignalChip,
  type InsightChipTone,
} from "@/lib/insight-chip-format";
import type {
  InsightDimension,
  InsightGrade,
  InsightItemView,
} from "@/lib/types";
import { freshnessFromVerifiedAt, type FreshnessLevel } from "@/lib/insight-verification";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";

// 新鲜度分级配色：越旧越偏琥珀，提示用户谨慎参考。
const FRESHNESS_TONE: Record<FreshnessLevel, string> = {
  fresh: "border border-[#bcdcae] bg-[#e6f2d6] text-[#4f6f2a] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]",
  recent: "border border-black/[0.08] bg-[#f4efe6] text-[#8a8275] dark:border-white/[0.1] dark:bg-white/[0.08] dark:text-[#9a9184]",
  aging: "border border-[#e7c98a] bg-[#fbeecb] text-[#8a6312] dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]",
  stale: "border border-[#e0a94e] bg-[#fbe6c4] text-[#8a5a12] dark:border-[#e0b15a]/[0.40] dark:bg-[#e0b15a]/[0.20] dark:text-[#e8bf72]",
};

const PAYLOAD_CHIP_TONE: Record<InsightChipTone, string> = {
  positive: "border-[#a9d8c4] bg-[#dcf2e8] text-[#2f8a63] dark:border-[#6cc99e]/[0.30] dark:bg-[#6cc99e]/[0.15] dark:text-[#6cc99e]",
  warning: "border-[#e7c98a] bg-[#fbeecb] text-[#8a6312] dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]",
  neutral: "border-black/[0.08] bg-[#f4efe6] text-[#8a8275] dark:border-white/[0.1] dark:bg-white/[0.08] dark:text-[#9a9184]",
};

interface Props {
  company: string;
  open: boolean;
  onClose: () => void;
}

// 每个维度一套强调色，让四个分区在视觉上彼此区分（章节图标用，卡片左边框仍按 grade）
const DIMENSION_META: Record<
  InsightDimension,
  { label: string; icon: typeof Scales; accent: string; iconText: string }
> = {
  timing: {
    label: "招聘时机",
    icon: CalendarBlank,
    accent: "border-[#b7d2ee] bg-[#dceafa] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15]",
    iconText: "text-[#2f6299] dark:text-[#7fb2e8]",
  },
  hiring: {
    label: "招聘动态",
    icon: Buildings,
    accent: "border-[#a9cfd8] bg-[#dcf0f2] dark:border-[#6cc0cf]/[0.30] dark:bg-[#6cc0cf]/[0.15]",
    iconText: "text-[#2f7d8a] dark:text-[#6cc0cf]",
  },
  listing: {
    label: "上市 / 股票",
    icon: ChartLineUp,
    accent: "border-[#a9d8c4] bg-[#dcf2e8] dark:border-[#6cc99e]/[0.30] dark:bg-[#6cc99e]/[0.15]",
    iconText: "text-[#2f8a63] dark:text-[#6cc99e]",
  },
  compensation_intensity: {
    label: "薪资 / 强度",
    icon: Scales,
    accent: "border-[#e7c98a] bg-[#fbeecb] dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15]",
    iconText: "text-[#8a6312] dark:text-[#e0b15a]",
  },
  path: {
    label: "进入路径",
    icon: Path,
    accent: "border-[#cfc0e6] bg-[#efe9f8] dark:border-[#c3b1e6]/[0.30] dark:bg-[#c3b1e6]/[0.15]",
    iconText: "text-[#6a4fa0] dark:text-[#c3b1e6]",
  },
  // 文化维度：合规上不用「避坑」字样，统一改为「温馨提示」
  culture: {
    label: "公司文化 / 温馨提示",
    icon: UsersThree,
    accent: "border-[#e6bcc4] bg-[#f8e6ea] dark:border-[#e09aa9]/[0.30] dark:bg-[#e09aa9]/[0.15]",
    iconText: "text-[#a84f63] dark:text-[#e09aa9]",
  },
};

const DIMENSION_ORDER: InsightDimension[] = [
  "timing",
  "hiring",
  "listing",
  "compensation_intensity",
  "path",
  "culture",
];

function gradeChip(grade: InsightGrade, sampleSize: number | null): {
  text: string;
  cls: string;
} {
  if (grade === "fact") {
    return {
      text: "事实 · 公开来源",
      cls: "border border-[#bcdcae] bg-[#e6f2d6] text-[#4f6f2a] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]",
    };
  }
  return {
    text: sampleSize ? `经验 · 据约 ${sampleSize} 条反馈` : "经验 · 群体反馈",
    cls: "border border-[#e7c98a] bg-[#fbeecb] text-[#8a6312] dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]",
  };
}

export default function CompanyInsightDrawer({ company, open, onClose }: Props) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<CompanyInsightResponse | null>(null);

  useEffect(() => {
    if (!open) return;
    track("insight_drawer_open");
    let alive = true;
    setLoading(true);
    fetchCompanyInsights(company)
      .then((res) => {
        if (alive) setData(res);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [open, company]);

  // 打开时锁滚动 + 支持 Esc 关闭
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  // 通过 portal 渲染到 body：避免抽屉成为带 transform 的 JobCard <article> 的后代，
  // 否则 fixed 定位会以卡片为包含块、随 hover transform 抖动（曾导致打开后频繁闪烁）。
  if (!open || typeof document === "undefined") return null;

  const dims = data?.dimensions;
  const totalItems = dims
    ? DIMENSION_ORDER.reduce((n, d) => n + (dims[d]?.length || 0), 0)
    : 0;
  // 公司概况（T2 官方事实回填，存在才显示）
  const cp = data?.company;
  const firmoBits = cp
    ? [
        cp.founded_year ? `成立 ${cp.founded_year}` : null,
        cp.headcount_band ? `规模 ${cp.headcount_band}` : null,
        cp.hq_location ? `总部 ${cp.hq_location}` : null,
        cp.industry || null,
      ].filter(Boolean)
    : [];

  return createPortal(
    <div className="fixed inset-0 z-[60] flex justify-end">
      <button
        type="button"
        aria-label="关闭"
        onClick={onClose}
        className="absolute inset-0 bg-[#1a1714]/40 backdrop-blur-sm dark:bg-black/60"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="公司职业洞察"
        className="relative flex h-full w-full flex-col border-l border-black/[0.08] bg-[#f4efe6] text-[#1a1714] shadow-2xl sm:max-w-xl lg:max-w-2xl dark:border-white/[0.1] dark:bg-[#16130f] dark:text-[#f3ecdf]"
      >
        {/* 头部：明确「社区聚合·非官方」，与官方岗位数据视觉区分 */}
        <div className="border-b border-black/[0.06] bg-gradient-to-b from-white/60 to-transparent px-6 pb-5 pt-6 dark:border-white/[0.1] dark:from-white/[0.05]">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm text-[#8a8275] dark:text-[#9a9184]">
                <Sparkle size={16} weight="fill" className="text-[#6a4fa0] dark:text-[#c3b1e6]" />
                公司职业洞察
              </div>
              <h2 className="mt-1.5 truncate text-2xl font-semibold leading-tight">
                {data?.company?.display_name || data?.company?.company || company}
              </h2>
              {firmoBits.length > 0 && (
                <p className="mt-1 text-xs text-[#8a8275] dark:text-[#9a9184]">{firmoBits.join(" · ")}</p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="shrink-0 rounded-full bg-black/[0.05] p-2 text-[#5f594e] transition hover:bg-black/[0.08] hover:text-[#1a1714] dark:bg-white/[0.05] dark:text-[#b6ad9d] dark:hover:bg-white/[0.08] dark:hover:text-[#f3ecdf]"
            >
              <X size={18} weight="bold" />
            </button>
          </div>
          {/* 唯一一次「来源聚合·去标识」统一声明（每条卡片正文不再重复罗列媒体名） */}
          <p className="mt-4 flex gap-2.5 rounded-xl border border-[#cfc0e6] bg-[#efe9f8] px-3.5 py-3 text-[13px] leading-6 text-[#5a4a78] dark:border-[#c3b1e6]/[0.30] dark:bg-[#c3b1e6]/[0.12] dark:text-[#c3b1e6]">
            <ShieldCheck size={18} weight="fill" className="mt-0.5 shrink-0 text-[#6a4fa0] dark:text-[#c3b1e6]" />
            <span>
              下列内容部分来自<strong>本平台在招岗位的聚合统计</strong>（带「本平台岗位聚合」标记，属事实数据），部分来自<strong>公开报道与网络讨论的聚合</strong>并经<strong>去标识化</strong>处理（属社区参考、非官方，也不针对任何个人）。每条结论的依据见卡片下方，<strong>仅供参考</strong>，请结合官方岗位信息与面试沟通自行判断。
            </span>
          </p>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          {loading && <p className="text-sm text-[#8a8275] dark:text-[#9a9184]">正在加载洞察…</p>}

          {!loading && totalItems === 0 && (
            <div className="rounded-xl border border-black/[0.06] bg-white/55 p-5 text-[15px] leading-7 text-[#5f594e] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d]">
              {failureMessage(data?.failure_reason)}
            </div>
          )}

          {!loading && totalItems > 0 && (
            <div className="space-y-8">
              {DIMENSION_ORDER.map((dim) => {
                const items = dims?.[dim] || [];
                if (items.length === 0) return null;
                const Meta = DIMENSION_META[dim];
                return (
                  <section key={dim}>
                    <header className="mb-3 flex items-center gap-2.5">
                      <span
                        className={cn(
                          "grid size-8 place-items-center rounded-xl border",
                          Meta.accent,
                        )}
                      >
                        <Meta.icon size={17} weight="bold" className={Meta.iconText} />
                      </span>
                      <h3 className="text-base font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{Meta.label}</h3>
                      <span className="rounded-full bg-black/[0.05] px-2 py-0.5 text-xs font-medium text-[#8a8275] dark:bg-white/[0.08] dark:text-[#9a9184]">
                        {items.length}
                      </span>
                    </header>
                    <div className="space-y-3.5">
                      {items.map((item) => (
                        <InsightCard key={item.id} item={item} />
                      ))}
                    </div>
                  </section>
                );
              })}
            </div>
          )}
        </div>
      </aside>
    </div>,
    document.body,
  );
}

function failureMessage(reason: string | null | undefined): string {
  if (reason === "insight_outdated") {
    return "该公司暂无当前有效的洞察（已有信息可能已过时）。我们仅展示经核实、在有效期内的内容。";
  }
  return "该公司暂无经核实的职业洞察信息。我们只展示通过分级与时效校验的内容，宁缺毋滥。";
}

// 上市维度的「投递视角」：把上市状态翻成对求职者的股权含金量提示（行业通行的判断，非投资建议）。
// 不落库易变行情，建议文案由 status + unicorn 标志在前端确定性生成。
const EQUITY_ANGLE: Record<
  string,
  { tone: string; label: string; text: string }
> = {
  listed: {
    tone: "border-[#a9d8c4] bg-[#dcf2e8] text-[#2f8a63] dark:border-[#6cc99e]/[0.30] dark:bg-[#6cc99e]/[0.15] dark:text-[#6cc99e]",
    label: "投递视角 · 股权可估值",
    text: "已上市：期权/RSU 可按公开股价估值，含金量较透明。结合下方近期行情自行判断——行情向好通常意味着手中股权更值钱。",
  },
  filed: {
    tone: "border-[#b7d2ee] bg-[#dceafa] text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]",
    label: "投递视角 · 临近上市",
    text: "已递交招股书：临近上市，期权有潜在流动性预期，是较好的进入窗口；留意行权价、锁定期与上市不确定性。",
  },
  pre_ipo: {
    tone: "border-[#b7d2ee] bg-[#dceafa] text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]",
    label: "投递视角 · 筹备上市",
    text: "筹备上市：股权有上市后变现预期，适合看好者提前进入；上市时间表未定，存在不确定性。",
  },
  unicorn: {
    tone: "border-[#cfc0e6] bg-[#efe9f8] text-[#6a4fa0] dark:border-[#c3b1e6]/[0.30] dark:bg-[#c3b1e6]/[0.15] dark:text-[#c3b1e6]",
    label: "投递视角 · 独角兽股权",
    text: "未上市独角兽：估值高、市场看好，股权激励潜在含金量高，常是值得投递的标的；但短期不可变现、依赖后续融资或上市兑现。",
  },
  private: {
    tone: "border-black/[0.08] bg-[#f4efe6] text-[#8a8275] dark:border-white/[0.1] dark:bg-white/[0.08] dark:text-[#9a9184]",
    label: "投递视角 · 重看现金",
    text: "未上市且暂无明确上市计划：股权短期难变现，评估 offer 时建议以现金薪酬为主、股权为辅。",
  },
};

function EquityAngle({ payload }: { payload: Record<string, unknown> }) {
  const status = typeof payload?.status === "string" ? payload.status : "";
  if (!status) return null;
  const key = status === "private" && payload?.unicorn === true ? "unicorn" : status;
  const angle = EQUITY_ANGLE[key];
  if (!angle) return null;
  return (
    <div className={cn("mt-2.5 rounded-xl border px-3.5 py-2.5 text-[13px] leading-6", angle.tone)}>
      <span className="font-semibold">{angle.label}</span>
      <span className="mt-0.5 block opacity-90">{angle.text}</span>
    </div>
  );
}

// 上市维度的「近期行情」：易变数据不落库为数字，只给一个公开行情页链接（payload.quote_url）。
function QuoteLink({ payload }: { payload: Record<string, unknown> }) {
  const quoteUrl = typeof payload?.quote_url === "string" ? payload.quote_url : "";
  if (!quoteUrl || !/^https?:\/\//i.test(quoteUrl)) return null;
  const exchange = typeof payload?.exchange === "string" ? payload.exchange : "";
  const ticker = typeof payload?.ticker === "string" ? payload.ticker : "";
  const label = [exchange, ticker].filter(Boolean).join(" ") || "公开行情";
  return (
    <a
      href={quoteUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="mt-2.5 inline-flex items-center gap-1.5 rounded-lg border border-[#a9d8c4] bg-[#dcf2e8] px-2.5 py-1 text-[12px] font-medium text-[#2f8a63] transition hover:bg-[#cdebde] dark:border-[#6cc99e]/[0.30] dark:bg-[#6cc99e]/[0.15] dark:text-[#6cc99e] dark:hover:bg-[#6cc99e]/[0.22]"
    >
      <ChartLineUp size={13} weight="bold" />
      近期行情 · {label}
      <ArrowSquareOut size={11} weight="bold" />
    </a>
  );
}

function PayloadChips({ item }: { item: InsightItemView }) {
  const payload = item.payload || {};
  const chips =
    item.dimension === "hiring"
      ? (() => {
          const chip = formatHiringSignalChip(payload.hiring_signal as Record<string, unknown> | null | undefined);
          return chip ? [{ ...chip, icon: Buildings }] : [];
        })()
      : item.dimension === "listing"
        ? formatFinancialChips(payload.financials as Record<string, unknown> | null | undefined)
            .map((chip) => ({ ...chip, icon: ChartLineUp }))
        : [];

  if (chips.length === 0) return null;
  return (
    <div className="mt-2.5 flex flex-wrap gap-1.5">
      {chips.map((chip) => {
        const Icon = chip.icon;
        return (
          <span
            key={chip.text}
            className={cn(
              "inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-[12px] font-medium",
              PAYLOAD_CHIP_TONE[chip.tone],
            )}
          >
            <Icon size={13} weight="bold" />
            {chip.text}
          </span>
        );
      })}
    </div>
  );
}

function InsightCard({ item }: { item: InsightItemView }) {
  const [disputing, setDisputing] = useState(false);
  const [reason, setReason] = useState("");
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);
  const chip = item.derived
    ? {
        text: "本平台岗位聚合",
        cls: "border border-[#b7d2ee] bg-[#dceafa] text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]",
      }
    : gradeChip(item.grade, item.sample_size);
  const freshness = freshnessFromVerifiedAt(item.last_verified_at);

  async function submitDispute() {
    setSending(true);
    try {
      const res = await fetch("/api/insights/dispute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: item.id, reason }),
      });
      if (res.ok) {
        setSent(true);
        setDisputing(false);
      }
    } catch (e) {
      console.error("[insight-drawer] 申诉失败", (e as Error).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <article
      className={cn(
        "rounded-xl border border-black/[0.06] border-l-2 bg-white/60 p-5 pl-4 text-[15px] dark:border-white/[0.1] dark:bg-white/[0.05]",
        item.grade === "fact" ? "border-l-[#6f9a3a] dark:border-l-[#a3d06a]" : "border-l-[#e0a94e] dark:border-l-[#e0b15a]",
        item.outdated && "opacity-70",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded-full px-2.5 py-0.5 text-[11px] font-semibold", chip.cls)}>
          {chip.text}
        </span>
        {item.outdated && (
          <span className="rounded-full border border-black/[0.08] bg-[#f4efe6] px-2 py-0.5 text-[11px] text-[#8a8275] dark:border-white/[0.1] dark:bg-white/[0.08] dark:text-[#9a9184]">
            可能已过时
          </span>
        )}
      </div>

      {item.title && <p className="mt-2.5 text-base font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{item.title}</p>}
      <p className="mt-1.5 leading-7 text-[#3f3a33] dark:text-[#d9d0c2]">{item.content}</p>
      <PayloadChips item={item} />
      <EquityAngle payload={item.payload} />
      <QuoteLink payload={item.payload} />

      <div className="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[#8a8275] dark:text-[#9a9184]">
        {item.time_window && (
          <span className="inline-flex items-center gap-1">
            <CalendarBlank size={13} />
            {item.time_window}
          </span>
        )}
        {item.last_verified_at && freshness && (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5",
              FRESHNESS_TONE[freshness.level],
            )}
          >
            <ClockCounterClockwise size={12} weight="bold" />
            {freshness.text} · {new Date(item.last_verified_at).toLocaleDateString("zh-CN")}
          </span>
        )}
      </div>

      {item.sources.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {item.sources.map((s) => (
            <a
              key={s.id}
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-md border border-black/[0.08] bg-white/70 px-2 py-0.5 text-[11px] text-[#5f594e] transition hover:bg-white hover:text-[#1a1714] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d] dark:hover:bg-white/[0.08] dark:hover:text-[#f3ecdf]"
            >
              {s.publisher || "来源"}
              <ArrowSquareOut size={11} weight="bold" />
            </a>
          ))}
        </div>
      )}

      {!item.derived && (
      <div className="mt-3.5 border-t border-black/[0.06] pt-2.5 dark:border-white/[0.1]">
        {sent ? (
          <span className="text-[11px] text-[#4f6f2a] dark:text-[#a3d06a]">已收到反馈，我们会尽快核实。</span>
        ) : disputing ? (
          <div className="space-y-2">
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="说明哪里有误（选填）"
              rows={2}
              className="w-full rounded-lg border border-black/[0.09] bg-white/70 px-2.5 py-1.5 text-xs text-[#1a1714] outline-none placeholder:text-[#a39a8c] focus:border-[#1a1714]/55 focus:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#f3ecdf] dark:placeholder:text-[#8b8478] dark:focus:border-white/40 dark:focus:bg-white/[0.08]"
            />
            <div className="flex gap-2">
              <button
                type="button"
                disabled={sending}
                onClick={submitDispute}
                className="rounded-full bg-[#1a1714] px-3 py-1 text-[11px] font-semibold text-[#f7f1e6] transition hover:bg-[#2b2520] disabled:opacity-50 dark:bg-[#f3ecdf] dark:text-[#16130f] dark:hover:bg-[#e8ddca]"
              >
                提交
              </button>
              <button
                type="button"
                onClick={() => setDisputing(false)}
                className="rounded-full px-3 py-1 text-[11px] text-[#8a8275] hover:text-[#1a1714] dark:text-[#9a9184] dark:hover:text-[#f3ecdf]"
              >
                取消
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setDisputing(true)}
            className="inline-flex items-center gap-1 text-[11px] text-[#9a9184] transition hover:text-[#1a1714] dark:text-[#837c70] dark:hover:text-[#f3ecdf]"
          >
            <Flag size={12} />
            这条有误?
          </button>
        )}
      </div>
      )}
    </article>
  );
}

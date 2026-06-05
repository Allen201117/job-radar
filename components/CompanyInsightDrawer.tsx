"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowSquareOut,
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
import type {
  InsightDimension,
  InsightGrade,
  InsightItemView,
} from "@/lib/types";
import { freshnessFromVerifiedAt, type FreshnessLevel } from "@/lib/insight-verification";
import { cn } from "@/lib/utils";

// 新鲜度分级配色：越旧越偏琥珀，提示用户谨慎参考。
const FRESHNESS_TONE: Record<FreshnessLevel, string> = {
  fresh: "border border-[#bcdcae] bg-[#e6f2d6] text-[#4f6f2a]",
  recent: "border border-black/[0.08] bg-[#f4efe6] text-[#8a8275]",
  aging: "border border-[#e7c98a] bg-[#fbeecb] text-[#8a6312]",
  stale: "border border-[#e0a94e] bg-[#fbe6c4] text-[#8a5a12]",
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
    accent: "border-[#b7d2ee] bg-[#dceafa]",
    iconText: "text-[#2f6299]",
  },
  listing: {
    label: "上市 / 股票",
    icon: ChartLineUp,
    accent: "border-[#a9d8c4] bg-[#dcf2e8]",
    iconText: "text-[#2f8a63]",
  },
  compensation_intensity: {
    label: "薪资 / 强度",
    icon: Scales,
    accent: "border-[#e7c98a] bg-[#fbeecb]",
    iconText: "text-[#8a6312]",
  },
  path: {
    label: "进入路径",
    icon: Path,
    accent: "border-[#cfc0e6] bg-[#efe9f8]",
    iconText: "text-[#6a4fa0]",
  },
  // 文化维度：合规上不用「避坑」字样，统一改为「温馨提示」
  culture: {
    label: "公司文化 / 温馨提示",
    icon: UsersThree,
    accent: "border-[#e6bcc4] bg-[#f8e6ea]",
    iconText: "text-[#a84f63]",
  },
};

const DIMENSION_ORDER: InsightDimension[] = [
  "timing",
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
      cls: "border border-[#bcdcae] bg-[#e6f2d6] text-[#4f6f2a]",
    };
  }
  return {
    text: sampleSize ? `经验 · 据约 ${sampleSize} 条反馈` : "经验 · 群体反馈",
    cls: "border border-[#e7c98a] bg-[#fbeecb] text-[#8a6312]",
  };
}

export default function CompanyInsightDrawer({ company, open, onClose }: Props) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<CompanyInsightResponse | null>(null);

  useEffect(() => {
    if (!open) return;
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

  return createPortal(
    <div className="fixed inset-0 z-[60] flex justify-end">
      <button
        type="button"
        aria-label="关闭"
        onClick={onClose}
        className="absolute inset-0 bg-[#1a1714]/40 backdrop-blur-sm"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="公司职业洞察"
        className="relative flex h-full w-full flex-col border-l border-black/[0.08] bg-[#f4efe6] text-[#1a1714] shadow-2xl sm:max-w-xl lg:max-w-2xl"
      >
        {/* 头部：明确「社区聚合·非官方」，与官方岗位数据视觉区分 */}
        <div className="border-b border-black/[0.06] bg-gradient-to-b from-white/60 to-transparent px-6 pb-5 pt-6">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm text-[#8a8275]">
                <Sparkle size={16} weight="fill" className="text-[#6a4fa0]" />
                公司职业洞察
              </div>
              <h2 className="mt-1.5 truncate text-2xl font-semibold leading-tight">
                {data?.company?.display_name || data?.company?.company || company}
              </h2>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="shrink-0 rounded-full bg-black/[0.05] p-2 text-[#5f594e] transition hover:bg-black/[0.08] hover:text-[#1a1714]"
            >
              <X size={18} weight="bold" />
            </button>
          </div>
          {/* 唯一一次「来源聚合·去标识」统一声明（每条卡片正文不再重复罗列媒体名） */}
          <p className="mt-4 flex gap-2.5 rounded-xl border border-[#cfc0e6] bg-[#efe9f8] px-3.5 py-3 text-[13px] leading-6 text-[#5a4a78]">
            <ShieldCheck size={18} weight="fill" className="mt-0.5 shrink-0 text-[#6a4fa0]" />
            <span>
              下列内容均来自<strong>公开报道与网络讨论的聚合</strong>、并经<strong>去标识化</strong>处理，属社区参考、非官方信息，也不针对任何个人。每条结论的具体出处见卡片下方「来源」，<strong>仅供参考</strong>，请结合官方岗位信息与面试沟通自行判断。
            </span>
          </p>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          {loading && <p className="text-sm text-[#8a8275]">正在加载洞察…</p>}

          {!loading && totalItems === 0 && (
            <div className="rounded-xl border border-black/[0.06] bg-white/55 p-5 text-[15px] leading-7 text-[#5f594e]">
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
                      <h3 className="text-base font-semibold text-[#1a1714]">{Meta.label}</h3>
                      <span className="rounded-full bg-black/[0.05] px-2 py-0.5 text-xs font-medium text-[#8a8275]">
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
      className="mt-2.5 inline-flex items-center gap-1.5 rounded-lg border border-[#a9d8c4] bg-[#dcf2e8] px-2.5 py-1 text-[12px] font-medium text-[#2f8a63] transition hover:bg-[#cdebde]"
    >
      <ChartLineUp size={13} weight="bold" />
      近期行情 · {label}
      <ArrowSquareOut size={11} weight="bold" />
    </a>
  );
}

function InsightCard({ item }: { item: InsightItemView }) {
  const [disputing, setDisputing] = useState(false);
  const [reason, setReason] = useState("");
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);
  const chip = gradeChip(item.grade, item.sample_size);
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
        "rounded-xl border border-black/[0.06] border-l-2 bg-white/60 p-5 pl-4 text-[15px]",
        item.grade === "fact" ? "border-l-[#6f9a3a]" : "border-l-[#e0a94e]",
        item.outdated && "opacity-70",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded-full px-2.5 py-0.5 text-[11px] font-semibold", chip.cls)}>
          {chip.text}
        </span>
        {item.outdated && (
          <span className="rounded-full border border-black/[0.08] bg-[#f4efe6] px-2 py-0.5 text-[11px] text-[#8a8275]">
            可能已过时
          </span>
        )}
      </div>

      {item.title && <p className="mt-2.5 text-base font-semibold text-[#1a1714]">{item.title}</p>}
      <p className="mt-1.5 leading-7 text-[#3f3a33]">{item.content}</p>
      <QuoteLink payload={item.payload} />

      <div className="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[#8a8275]">
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
              className="inline-flex items-center gap-1 rounded-md border border-black/[0.08] bg-white/70 px-2 py-0.5 text-[11px] text-[#5f594e] transition hover:bg-white hover:text-[#1a1714]"
            >
              {s.publisher || "来源"}
              <ArrowSquareOut size={11} weight="bold" />
            </a>
          ))}
        </div>
      )}

      <div className="mt-3.5 border-t border-black/[0.06] pt-2.5">
        {sent ? (
          <span className="text-[11px] text-[#4f6f2a]">已收到反馈，我们会尽快核实。</span>
        ) : disputing ? (
          <div className="space-y-2">
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="说明哪里有误（选填）"
              rows={2}
              className="w-full rounded-lg border border-black/[0.09] bg-white/70 px-2.5 py-1.5 text-xs text-[#1a1714] outline-none placeholder:text-[#a39a8c] focus:border-[#1a1714]/55 focus:bg-white"
            />
            <div className="flex gap-2">
              <button
                type="button"
                disabled={sending}
                onClick={submitDispute}
                className="rounded-full bg-[#1a1714] px-3 py-1 text-[11px] font-semibold text-[#f7f1e6] transition hover:bg-[#2b2520] disabled:opacity-50"
              >
                提交
              </button>
              <button
                type="button"
                onClick={() => setDisputing(false)}
                className="rounded-full px-3 py-1 text-[11px] text-[#8a8275] hover:text-[#1a1714]"
              >
                取消
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setDisputing(true)}
            className="inline-flex items-center gap-1 text-[11px] text-[#9a9184] transition hover:text-[#1a1714]"
          >
            <Flag size={12} />
            这条有误?
          </button>
        )}
      </div>
    </article>
  );
}

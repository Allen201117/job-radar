"use client";

// 最小可渲染版：只负责把服务端算好的公司卡（窗口态 + 校招岗数）铺成列表。
// 不做筛选 / 展开 / 探活 / 纠错 —— 那些是 Task 8 的活，会来充实这个文件。
import Link from "next/link";
import { EmptyPanel } from "@/components/ProductChrome";
import type { CampusCompanyRow } from "@/lib/jobs-store/read";
import type { WindowState } from "@/lib/campus-zone";

export type CampusCardData = CampusCompanyRow & {
  window: WindowState;
  nearestDeadlineMs: number | null;
};

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

function WindowBadge({ window }: { window: WindowState }) {
  const badge = WINDOW_BADGE[window.state];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-medium ${badge.className}`}>
      <span aria-hidden="true">{badge.icon}</span>
      {badge.label}
    </span>
  );
}

export default function CampusClient({
  cards,
  industries,
  hasIndustry,
}: {
  cards: CampusCardData[];
  industries: string[];
  hasIndustry: boolean;
}) {
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
      </div>

      {cards.length === 0 ? (
        <EmptyPanel title="暂无匹配公司" description="当前行业下没有必投清单公司，换一个行业试试。" />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {cards.map((card) => (
            <div key={card.pattern} className="surface flex flex-col gap-3 p-5">
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-[15px] font-semibold leading-tight">{card.company}</h3>
                <WindowBadge window={card.window} />
              </div>
              <p className="text-sm text-[#5f594e] dark:text-[#b6ad9d]">
                {card.campusJobs.length > 0 ? `${card.campusJobs.length} 个校招在招岗位` : "暂无校招在招岗位"}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

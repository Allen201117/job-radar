"use client";

// 已投递页客户端：投递进展跟踪（漏斗中段最小版）。
// 每张卡一排阶段切换（已投递→笔试→面试→Offer→已结束），乐观更新 + 失败回滚；
// 顶部漏斗小结让用户一眼看到自己的求职管道，不用回 Excel 记进展。
import { useMemo, useState } from "react";
import { ArrowSquareOut, MapPin } from "@phosphor-icons/react";

export type AppliedItem = {
  jobId: string;
  createdAt: string | null;
  company: string;
  title: string;
  location: string | null;
  jdUrl: string | null;
  down: boolean;
  stage: string | null; // null = 未设置（等同「已投递」初始态）
};

const STAGE_ORDER = ["applied", "assessment", "interview", "offer", "closed"] as const;
type Stage = (typeof STAGE_ORDER)[number];

const STAGE_LABEL: Record<Stage, string> = {
  applied: "已投递",
  assessment: "笔试/测评",
  interview: "面试中",
  offer: "Offer",
  closed: "已结束",
};

// 漏斗小结只统计推进中的阶段（closed 单独显示，不算管道内）
const FUNNEL_STAGES: Stage[] = ["applied", "assessment", "interview", "offer"];

function normalizeStage(stage: string | null): Stage {
  return (STAGE_ORDER as readonly string[]).includes(stage || "") ? (stage as Stage) : "applied";
}

export default function AppliedClient({ items }: { items: AppliedItem[] }) {
  const [stages, setStages] = useState<Record<string, Stage>>(() =>
    Object.fromEntries(items.map((it) => [it.jobId, normalizeStage(it.stage)])),
  );
  const [failedId, setFailedId] = useState<string | null>(null);

  const funnel = useMemo(() => {
    const counts: Record<Stage, number> = { applied: 0, assessment: 0, interview: 0, offer: 0, closed: 0 };
    for (const it of items) counts[stages[it.jobId] ?? "applied"] += 1;
    return counts;
  }, [items, stages]);

  async function setStage(jobId: string, next: Stage) {
    const prev = stages[jobId] ?? "applied";
    if (prev === next) return;
    setStages((s) => ({ ...s, [jobId]: next }));
    setFailedId(null);
    try {
      const resp = await fetch(`/api/job-actions/${jobId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: next }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    } catch {
      setStages((s) => ({ ...s, [jobId]: prev })); // 失败回滚，不让 UI 与数据库长期相反
      setFailedId(jobId);
    }
  }

  return (
    <div>
      {items.length > 1 && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-[13px] text-[#6b655a] dark:text-[#b6ad9d]">
          <span className="font-medium">你的求职管道：</span>
          {FUNNEL_STAGES.map((s) => (
            <span
              key={s}
              className="rounded-full border border-black/[0.06] bg-white/60 px-2.5 py-1 tabular-nums dark:border-white/[0.1] dark:bg-white/[0.05]"
            >
              {STAGE_LABEL[s]} {funnel[s]}
            </span>
          ))}
          {funnel.closed > 0 && (
            <span className="rounded-full border border-black/[0.06] bg-white/40 px-2.5 py-1 tabular-nums text-[#9a9184] dark:border-white/[0.08] dark:bg-white/[0.03] dark:text-[#837c70]">
              已结束 {funnel.closed}
            </span>
          )}
        </div>
      )}

      <div className="space-y-3">
        {items.map((item) => {
          const cur = stages[item.jobId] ?? "applied";
          return (
            <div key={item.jobId} className="surface surface-hover p-5 text-[#1a1714] dark:text-[#f3ecdf]">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <span className="text-xs font-medium text-[#8a8275] dark:text-[#9a9184]">{item.company}</span>
                  <h3 className="mt-1 text-lg font-semibold">{item.title}</h3>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[#8a8275] dark:text-[#9a9184]">
                    {item.location && (
                      <span className="inline-flex items-center gap-1 rounded-full border border-black/[0.06] dark:border-white/[0.1] bg-[#f4efe6] dark:bg-[#16130f] px-2 py-1">
                        <MapPin size={13} weight="fill" aria-hidden="true" />
                        {item.location}
                      </span>
                    )}
                    投递于 {item.createdAt ? new Date(item.createdAt).toLocaleDateString("zh-CN") : "—"}
                  </div>
                </div>
                {item.down ? (
                  <span className="inline-flex w-full shrink-0 items-center justify-center gap-2 rounded-full border border-black/[0.08] bg-[#f0ece2] px-4 py-2.5 text-sm font-medium text-[#9a9184] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#837c70] sm:w-auto sm:py-2">
                    原岗位已下线
                  </span>
                ) : (
                  <a
                    href={item.jdUrl!}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex w-full shrink-0 items-center justify-center gap-2 rounded-full bg-[#1a1714] dark:bg-[#f3ecdf] px-4 py-2.5 text-sm font-semibold text-[#f7f1e6] dark:text-[#16130f] transition duration-200 hover:bg-[#2b2520] dark:hover:bg-[#e8ddca] active:scale-[0.98] sm:w-auto sm:py-2"
                  >
                    查看官网
                    <ArrowSquareOut size={16} weight="bold" aria-hidden="true" />
                  </a>
                )}
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-black/[0.05] pt-3 dark:border-white/[0.06]">
                <span className="mr-1 text-xs text-[#8a8275] dark:text-[#9a9184]">进展</span>
                {STAGE_ORDER.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStage(item.jobId, s)}
                    aria-pressed={cur === s}
                    className={
                      cur === s
                        ? "rounded-full bg-[#1a1714] px-3 py-1.5 text-xs font-semibold text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                        : "rounded-full border border-black/[0.08] bg-white/60 px-3 py-1.5 text-xs font-medium text-[#6b655a] transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d] dark:hover:bg-white/[0.08]"
                    }
                  >
                    {STAGE_LABEL[s]}
                  </button>
                ))}
                {failedId === item.jobId && (
                  <span className="text-xs text-[#9c4a3c] dark:text-[#e6a99f]">保存失败，已还原，请重试</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

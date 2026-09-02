"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import ActionToast, { jobActionToastText, useActionToast } from "@/components/ActionToast";
import JobCard from "@/components/JobCard";
import SavedCompare from "@/components/SavedCompare";
import { formatDateLabel } from "@/lib/relative-time";
import { track } from "@/lib/track";
import type { ScoredJob } from "@/lib/types";
import { CheckCircle, MapPin, Scales } from "@phosphor-icons/react";

type PrimaryAction = "saved" | "ignored" | "applied";

// 已被物理清理、只剩 job_snapshot 的「值得投」记录
export type DeletedSaved = {
  jobId: string;
  company: string;
  title: string;
  location: string | null;
  createdAt: string;
};

export default function SavedClient({
  initialJobs,
  deletedSaved = [],
  hasPreferences = false,
}: {
  initialJobs: ScoredJob[];
  deletedSaved?: DeletedSaved[];
  hasPreferences?: boolean;
}) {
  const [jobs, setJobs] = useState(initialJobs);
  const [deleted, setDeleted] = useState(deletedSaved);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [compareOpen, setCompareOpen] = useState(false);
  const router = useRouter();

  useEffect(() => {
    setJobs(initialJobs);
  }, [initialJobs]);
  useEffect(() => {
    const liveIds = new Set(initialJobs.map((job) => job.id));
    setSelectedIds((prev) => new Set(Array.from(prev).filter((id) => liveIds.has(id))));
  }, [initialJobs]);
  useEffect(() => {
    setDeleted(deletedSaved);
  }, [deletedSaved]);

  const { toast, show: showToast, dismiss: dismissToast } = useActionToast();
  // 已下线岗位的「取消值得投」正在提交的 id：给按钮一个 pending 态，别让用户以为没点上。
  const [cancelingId, setCancelingId] = useState<string | null>(null);

  const selectedJobs = jobs.filter((job) => selectedIds.has(job.id));
  const selectedCount = selectedIds.size;
  const compareLimitReached = selectedCount >= 4;

  function handleActionChange(jobId: string, action: PrimaryAction | null) {
    if (action !== "saved") {
      setJobs((items) => items.filter((job) => job.id !== jobId));
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(jobId);
        return next;
      });
    }
    router.refresh();
  }

  function toggleCompare(jobId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) {
        next.delete(jobId);
      } else if (next.size < 4) {
        next.add(jobId);
      }
      return next;
    });
  }

  function openCompare() {
    if (selectedCount < 2) return;
    track("saved_compare_opened", { job_count: selectedCount });
    setCompareOpen(true);
  }

  // 下线岗位仍可取消「值得投」（action=null）。乐观移除；失败则恢复。
  async function cancelDeleted(jobId: string) {
    if (cancelingId) return;
    const prev = deleted;
    setCancelingId(jobId);
    setDeleted((d) => d.filter((x) => x.jobId !== jobId));
    try {
      const resp = await fetch(`/api/job-actions/${jobId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: null }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      showToast({ text: "已取消值得投" });
    } catch {
      setDeleted(prev); // 恢复
      // 之前失败是静默回滚的：卡片自己跳回来，用户只会以为「点了没用」。
      showToast({ text: "取消失败，请重试", tone: "error" });
    } finally {
      setCancelingId(null);
    }
  }

  return (
    <div className="space-y-3">
      {jobs.length > 0 && (
        <div className="flex flex-col gap-2 rounded-[1.1rem] border border-black/[0.06] bg-white/45 px-4 py-3 text-sm ink-2 sm:flex-row sm:items-center sm:justify-between dark:border-white/[0.1] dark:bg-white/[0.05]">
          <span className="inline-flex items-center gap-2">
            <Scales size={15} weight="bold" className="text-[#3f7cc0] dark:text-[#7fb2e8]" aria-hidden="true" />
            选择 2-4 个岗位后，可打开对比决策桌横向查看匹配度、薪资和风险。
          </span>
        </div>
      )}

      {jobs.map((job) => (
        <div key={job.id} className="space-y-2">
          <div className="flex justify-end">
            <button
              type="button"
              aria-pressed={selectedIds.has(job.id)}
              onClick={() => toggleCompare(job.id)}
              disabled={compareLimitReached && !selectedIds.has(job.id)}
              className={
                selectedIds.has(job.id)
                  ? "inline-flex h-8 items-center justify-center gap-1.5 rounded-full border border-[#a9d8c4] bg-[#dcf2e8] px-3 text-xs font-semibold text-[#2f8a63] transition hover:bg-[#cdebde] dark:border-[#6cc99e]/[0.30] dark:bg-[#6cc99e]/[0.15] dark:text-[#6cc99e] dark:hover:bg-[#6cc99e]/[0.22]"
                  : "inline-flex h-8 items-center justify-center gap-1.5 rounded-full border border-black/[0.08] bg-white/70 px-3 text-xs font-semibold ink-2 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-45 dark:border-white/[0.12] dark:bg-white/[0.05] dark:hover:bg-white/[0.08]"
              }
            >
              {selectedIds.has(job.id) && <CheckCircle size={15} weight="fill" aria-hidden="true" />}
              {selectedIds.has(job.id) ? "已加入" : compareLimitReached ? "最多 4 个" : "加入对比"}
            </button>
          </div>
          <JobCard
            job={job}
            onActionChange={handleActionChange}
            onActionResult={({ action, ok }) =>
              showToast({ text: jobActionToastText(action, ok), tone: ok ? "default" : "error" })
            }
          />
        </div>
      ))}

      {deleted.map((d) => (
        <div key={d.jobId} className="surface p-5 ink-1">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <span className="text-xs font-medium ink-3">{d.company}</span>
              <h3 className="mt-1 text-lg font-semibold">{d.title}</h3>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs ink-3">
                {d.location && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-black/[0.06] bg-[#f4efe6] px-2 py-1 dark:border-white/[0.1] dark:bg-[#16130f]">
                    <MapPin size={13} weight="fill" aria-hidden="true" />
                    {d.location}
                  </span>
                )}
                加入于 {formatDateLabel(d.createdAt) ?? "—"}
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-stretch gap-2 sm:items-end">
              <span className="inline-flex items-center justify-center gap-2 rounded-full border border-black/[0.08] bg-[#f0ece2] px-4 py-2 text-sm font-medium ink-3 dark:border-white/[0.1] dark:bg-white/[0.05]">
                原岗位已下线
              </span>
              <button
                type="button"
                onClick={() => cancelDeleted(d.jobId)}
                disabled={cancelingId === d.jobId}
                className="text-xs font-medium ink-3 underline underline-offset-2 transition hover:opacity-80 disabled:opacity-50"
              >
                {cancelingId === d.jobId ? "取消中…" : "取消值得投"}
              </button>
            </div>
          </div>
        </div>
      ))}

      {selectedCount > 0 && (
        <div className="above-mobile-nav fixed inset-x-0 z-50 flex justify-center px-4">
          <div className="flex w-full max-w-xl flex-col gap-3 rounded-[1.25rem] border border-black/[0.1] bg-[#1a1714] px-4 py-3 text-sm text-[#f7f1e6] shadow-lg sm:flex-row sm:items-center sm:justify-between dark:border-white/[0.12] dark:bg-[#f3ecdf] dark:text-[#16130f]">
            <span className="font-semibold tabular-nums">已选 {selectedCount}/4</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={openCompare}
                disabled={selectedCount < 2}
                className="inline-flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-full bg-[#f7f1e6] px-4 py-2 font-semibold ink-1 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-45 sm:flex-none dark:bg-[#16130f] dark:hover:bg-[#2b2520]"
              >
                <Scales size={15} weight="bold" aria-hidden="true" />
                开始对比
              </button>
              <button
                type="button"
                onClick={() => setSelectedIds(new Set<string>())}
                className="min-h-10 rounded-full border border-white/20 px-4 py-2 font-semibold transition hover:bg-white/10 dark:border-black/[0.12] dark:hover:bg-black/[0.06]"
              >
                清空
              </button>
            </div>
          </div>
        </div>
      )}

      <SavedCompare
        open={compareOpen}
        jobs={selectedJobs}
        hasPreferences={hasPreferences}
        onClose={() => setCompareOpen(false)}
        onRemove={(jobId) =>
          setSelectedIds((prev) => {
            const next = new Set(prev);
            next.delete(jobId);
            return next;
          })
        }
      />

      <ActionToast toast={toast} onDismiss={dismissToast} />
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import JobCard from "@/components/JobCard";
import type { Job, ScoredJob } from "@/lib/types";
import { MapPin } from "@phosphor-icons/react";

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
}: {
  initialJobs: Job[];
  deletedSaved?: DeletedSaved[];
}) {
  const [jobs, setJobs] = useState(initialJobs);
  const [deleted, setDeleted] = useState(deletedSaved);
  const router = useRouter();

  useEffect(() => {
    setJobs(initialJobs);
  }, [initialJobs]);
  useEffect(() => {
    setDeleted(deletedSaved);
  }, [deletedSaved]);

  const scored = jobs.map((job) => ({
    ...job,
    match_score: 0,
    matched_keywords: [],
    hidden_reason: null,
    user_action: "saved" as const,
  })) as ScoredJob[];

  function handleActionChange(jobId: string, action: PrimaryAction | null) {
    if (action !== "saved") {
      setJobs((items) => items.filter((job) => job.id !== jobId));
    }
    router.refresh();
  }

  // 下线岗位仍可取消「值得投」（action=null）。乐观移除；失败则恢复。
  async function cancelDeleted(jobId: string) {
    const prev = deleted;
    setDeleted((d) => d.filter((x) => x.jobId !== jobId));
    try {
      const resp = await fetch(`/api/job-actions/${jobId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: null }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    } catch {
      setDeleted(prev); // 恢复
    }
  }

  return (
    <div className="space-y-3">
      {scored.map((job) => (
        <JobCard key={job.id} job={job} onActionChange={handleActionChange} />
      ))}

      {deleted.map((d) => (
        <div key={d.jobId} className="surface p-5 text-[#1a1714] dark:text-[#f3ecdf]">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <span className="text-xs font-medium text-[#8a8275] dark:text-[#9a9184]">{d.company}</span>
              <h3 className="mt-1 text-lg font-semibold">{d.title}</h3>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[#8a8275] dark:text-[#9a9184]">
                {d.location && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-black/[0.06] bg-[#f4efe6] px-2 py-1 dark:border-white/[0.1] dark:bg-[#16130f]">
                    <MapPin size={13} weight="fill" aria-hidden="true" />
                    {d.location}
                  </span>
                )}
                收藏于 {d.createdAt ? new Date(d.createdAt).toLocaleDateString("zh-CN") : "—"}
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-stretch gap-2 sm:items-end">
              <span className="inline-flex items-center justify-center gap-2 rounded-full border border-black/[0.08] bg-[#f0ece2] px-4 py-2 text-sm font-medium text-[#9a9184] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#837c70]">
                原岗位已下线
              </span>
              <button
                type="button"
                onClick={() => cancelDeleted(d.jobId)}
                className="text-xs font-medium text-[#8a8275] underline underline-offset-2 transition hover:text-[#1a1714] dark:text-[#9a9184] dark:hover:text-[#f3ecdf]"
              >
                取消值得投
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

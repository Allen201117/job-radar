"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import JobCard from "@/components/JobCard";
import type { ScoredJob } from "@/lib/types";

type PrimaryAction = "saved" | "ignored" | "applied";

export default function TodayClient({
  initialJobs,
}: {
  initialJobs: ScoredJob[];
}) {
  const [jobs, setJobs] = useState(initialJobs);
  const router = useRouter();

  // 展示时校验（②层）：给今日看板的岗位异步探活，死的当场隐藏（同 Jobs 页，复用 /api/jobs/liveness-check）。
  const [deadIds, setDeadIds] = useState<Set<string>>(new Set());
  const livenessRequested = useRef<Set<string>>(new Set());
  useEffect(() => {
    const ids = jobs
      .filter((j) => j.id && !livenessRequested.current.has(j.id) && !deadIds.has(j.id))
      .map((j) => j.id)
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
            (data.dead as string[]).forEach((id) => next.add(id));
            return next;
          });
        }
      } catch {
        // 静默：探不动就不动，点击门 + 后台扫兜底
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs]);

  function handleActionChange(jobId: string, action: PrimaryAction | null) {
    setJobs((items) =>
      items.map((job) =>
        job.id === jobId
          ? {
              ...job,
              user_action: action,
              hidden_reason:
                action === "ignored"
                  ? "ignored"
                  : action === "applied"
                    ? "applied_by_default"
                    : null,
            }
          : job,
      ),
    );
    router.refresh();
  }

  return (
    <>
      {jobs
        .filter((job) => !deadIds.has(job.id))
        .map((job) => (
          <JobCard
            key={job.id}
            job={job}
            onActionChange={handleActionChange}
          />
        ))}
    </>
  );
}

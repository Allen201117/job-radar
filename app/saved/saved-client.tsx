"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import JobCard from "@/components/JobCard";
import type { Job, ScoredJob } from "@/lib/types";

type PrimaryAction = "saved" | "ignored" | "applied";

export default function SavedClient({ initialJobs }: { initialJobs: Job[] }) {
  const [jobs, setJobs] = useState(initialJobs);
  const router = useRouter();

  useEffect(() => {
    setJobs(initialJobs);
  }, [initialJobs]);

  // 给 saved 的岗位简单标记
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

  return (
    <div className="space-y-3">
      {scored.map((job) => (
        <JobCard
          key={job.id}
          job={job}
          onActionChange={handleActionChange}
        />
      ))}
    </div>
  );
}

"use client";

import { useState } from "react";
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
      {jobs.map((job) => (
        <JobCard
          key={job.id}
          job={job}
          onActionChange={handleActionChange}
        />
      ))}
    </>
  );
}

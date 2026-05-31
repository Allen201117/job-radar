"use client";

import { useEffect, useState } from "react";
import { createBrowserClient } from "@/lib/supabaseClient";
import type { ScoredJob } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  job: ScoredJob;
  onActionChange: (jobId: string, action: PrimaryAction | null) => void;
}

type PrimaryAction = "saved" | "ignored" | "applied";

const ACTION_CONFIG = {
  saved: { label: "收藏", icon: "☆", variant: "outline" },
  ignored: { label: "忽略", icon: "✕", variant: "ghost" },
  applied: { label: "已投递", icon: "✓", variant: "default" },
} as const;

export default function JobCard({ job, onActionChange }: Props) {
  const [acting, setActing] = useState<string | null>(null);
  const [currentAction, setCurrentAction] = useState(job.user_action);
  const [actionError, setActionError] = useState("");
  const supabase = createBrowserClient();

  useEffect(() => {
    setCurrentAction(job.user_action);
  }, [job.user_action]);

  async function handleAction(action: PrimaryAction) {
    setActing(action);
    setActionError("");

    try {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        setActionError("请先登录后再操作");
        return;
      }

      // toggle: 如果已存在该 action，则删除；否则 upsert
      if (currentAction === action) {
        const { error } = await supabase
          .from("job_actions")
          .delete()
          .eq("user_id", user.id)
          .eq("job_id", job.id)
          .eq("action", action);
        if (error) throw error;
        setCurrentAction(null);
        onActionChange(job.id, null);
      } else {
        // 先删掉旧的不同 action（每人每岗位只能有一个主操作）
        const { error: deleteError } = await supabase
          .from("job_actions")
          .delete()
          .eq("user_id", user.id)
          .eq("job_id", job.id)
          .neq("action", "viewed");
        if (deleteError) throw deleteError;

        const { error: upsertError } = await supabase
          .from("job_actions")
          .upsert(
            {
              user_id: user.id,
              job_id: job.id,
              action,
            },
            { onConflict: "user_id,job_id,action" },
          );
        if (upsertError) throw upsertError;
        setCurrentAction(action);
        onActionChange(job.id, action);
      }
    } catch (error) {
      console.error("[job-card] action failed", error);
      setActionError("操作失败，请稍后重试");
    } finally {
      setActing(null);
    }
  }

  async function handleView() {
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) return;

    await supabase.from("job_actions").upsert(
      {
        user_id: user.id,
        job_id: job.id,
        action: "viewed",
      },
      { onConflict: "user_id,job_id,action" },
    );

    window.open(job.jd_url, "_blank", "noopener,noreferrer");
    onActionChange(job.id, currentAction as PrimaryAction | null);
  }

  const isNew =
    job.first_seen_at &&
    (Date.now() - new Date(job.first_seen_at).getTime()) / 86400000 <= 3;

  return (
    <div className="rounded-lg border bg-card p-4 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">
              {job.company}
            </span>
            {isNew && (
              <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                新
              </span>
            )}
            {job.job_type && (
              <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground">
                {job.job_type}
              </span>
            )}
          </div>
          <h3 className="mt-1 font-medium leading-snug">{job.title}</h3>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {job.location && <span>{job.location}</span>}
            {job.salary_text && <span>{job.salary_text}</span>}
            {!job.salary_text && <span>官网未披露</span>}
            <span>
              发现于{" "}
              {job.first_seen_at
                ? new Date(job.first_seen_at).toLocaleDateString("zh-CN")
                : "—"}
            </span>
          </div>
          {job.summary && (
            <p className="mt-2 text-sm text-muted-foreground line-clamp-2">
              {job.summary}
            </p>
          )}
          {job.matched_keywords.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {job.matched_keywords.map((kw) => (
                <span
                  key={kw}
                  className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
                >
                  {kw}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1.5">
          {job.match_score > 0 && (
            <span
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs font-semibold",
                job.match_score >= 50
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary text-muted-foreground",
              )}
            >
              {job.match_score}
            </span>
          )}
          {currentAction && (
            <span className="rounded-full bg-secondary px-2 py-0.5 text-xs">
              {currentAction === "saved"
                ? "已收藏"
                : currentAction === "applied"
                  ? "已投递"
                  : currentAction === "ignored"
                    ? "已忽略"
                    : ""}
            </span>
          )}
          <button
            onClick={handleView}
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90"
          >
            查看官网
          </button>
          <button
            onClick={() => handleAction("saved")}
            disabled={acting === "saved"}
            className={cn(
              "w-full rounded-md border px-3 py-1.5 text-xs font-medium",
              currentAction === "saved"
                ? "border-primary bg-primary/5 text-primary"
                : "hover:bg-muted",
            )}
          >
            {currentAction === "saved" ? "★ 已收藏" : "☆ 收藏"}
          </button>
          <button
            onClick={() => handleAction("applied")}
            disabled={acting === "applied"}
            className={cn(
              "w-full rounded-md border px-3 py-1.5 text-xs font-medium",
              currentAction === "applied"
                ? "border-green-500 bg-green-50 text-green-700"
                : "hover:bg-muted",
            )}
          >
            {currentAction === "applied" ? "✓ 已投递" : "标记已投递"}
          </button>
          <button
            onClick={() => handleAction("ignored")}
            disabled={acting === "ignored"}
            className="w-full rounded-md px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
          >
            {currentAction === "ignored" ? "已忽略" : "忽略"}
          </button>
          {actionError && (
            <span className="max-w-24 text-right text-xs text-destructive">
              {actionError}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

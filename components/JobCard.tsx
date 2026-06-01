"use client";

import { useEffect, useMemo, useState } from "react";
import { createBrowserClient } from "@/lib/supabaseClient";
import type { ScoredJob } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  job: ScoredJob;
  onActionChange: (jobId: string, action: PrimaryAction | null) => void;
}

type PrimaryAction = "saved" | "ignored" | "applied";

// 从 JD 文本里启发式抽经验/学历（无结构化字段时的兜底，抽不到显示「未知」）
function extractExperience(text?: string | null): string {
  if (!text) return "未知";
  const t = text.replace(/\s+/g, "");
  if (/应届|无经验要求|经验不限|不限经验/.test(t)) return "应届/不限";
  const m = t.match(/(\d+)[-~至](\d+)\s*年/) || t.match(/(\d+)\s*年(?:以上)?(?:工作)?经验/);
  if (m) return m[2] ? `${m[1]}-${m[2]}年` : `${m[1]}年+`;
  return "未知";
}
function extractEducation(text?: string | null): string {
  if (!text) return "未知";
  if (/博士/.test(text)) return "博士";
  if (/硕士|研究生/.test(text)) return "硕士";
  if (/本科/.test(text)) return "本科";
  if (/大专|专科/.test(text)) return "大专";
  if (/学历不限|不限学历/.test(text)) return "不限";
  return "未知";
}

export default function JobCard({ job, onActionChange }: Props) {
  const [acting, setActing] = useState(false);
  const [currentAction, setCurrentAction] = useState(job.user_action);
  const [actionError, setActionError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const supabase = createBrowserClient();

  useEffect(() => {
    setCurrentAction(job.user_action);
  }, [job.user_action]);

  const exp = useMemo(() => extractExperience(job.summary), [job.summary]);
  const edu = useMemo(() => extractEducation(job.summary), [job.summary]);

  // 后台落库，失败回滚（乐观更新已在 handleAction 中先行完成）
  async function writeAction(action: PrimaryAction | null, prev: PrimaryAction | null) {
    try {
      const {
        data: { session },
      } = await supabase.auth.getSession(); // 本地读取，无网络往返
      const uid = session?.user?.id;
      if (!uid) throw new Error("未登录");
      await supabase
        .from("job_actions")
        .delete()
        .eq("user_id", uid)
        .eq("job_id", job.id)
        .neq("action", "viewed");
      if (action) {
        const { error } = await supabase
          .from("job_actions")
          .upsert(
            { user_id: uid, job_id: job.id, action },
            { onConflict: "user_id,job_id,action" },
          );
        if (error) throw error;
      }
    } catch (e) {
      console.error("[job-card] action failed", e);
      setCurrentAction(prev);
      onActionChange(job.id, prev);
      setActionError("操作失败，已回退");
      setTimeout(() => setActionError(""), 2500);
    } finally {
      setActing(false);
    }
  }

  function handleAction(action: PrimaryAction) {
    if (acting) return;
    setActionError("");
    const prev = currentAction as PrimaryAction | null;
    const next = prev === action ? null : action;
    setCurrentAction(next); // 乐观：点击即变
    onActionChange(job.id, next);
    setActing(true);
    void writeAction(next, prev);
  }

  function handleView() {
    window.open(job.jd_url, "_blank", "noopener,noreferrer");
    supabase.auth.getSession().then(({ data: { session } }) => {
      const uid = session?.user?.id;
      if (uid) {
        void supabase.from("job_actions").upsert(
          { user_id: uid, job_id: job.id, action: "viewed" },
          { onConflict: "user_id,job_id,action" },
        );
      }
    });
  }

  const isNew =
    job.first_seen_at &&
    (Date.now() - new Date(job.first_seen_at).getTime()) / 86400000 <= 3;
  const seen = job.first_seen_at
    ? new Date(job.first_seen_at).toLocaleDateString("zh-CN")
    : "—";

  return (
    <div className="rounded-lg border bg-card p-4 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">{job.company}</span>
            {job.job_type && (
              <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground">
                {job.job_type}
              </span>
            )}
            {isNew && (
              <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                新
              </span>
            )}
          </div>
          <h3
            className="mt-1 cursor-pointer font-medium leading-snug hover:text-primary"
            onClick={handleView}
          >
            {job.title}
          </h3>

          {/* 关键信息结构化 */}
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
            <Field label="城市" value={job.location || "未知"} />
            <Field label="薪资" value={job.salary_text || "官网未披露"} />
            <Field label="经验" value={exp} />
            <Field label="学历" value={edu} />
            <Field label="发现" value={seen} />
            <Field label="截止投递" value="未知" />
          </div>

          {/* JD 介绍，可展开/收起 */}
          {job.summary && (
            <div className="mt-2">
              <p
                className={cn(
                  "whitespace-pre-line text-sm text-muted-foreground",
                  !expanded && "line-clamp-3",
                )}
              >
                {job.summary}
              </p>
              {job.summary.length > 80 && (
                <button
                  onClick={() => setExpanded((v) => !v)}
                  className="mt-1 text-xs font-medium text-primary hover:underline"
                >
                  {expanded ? "收起" : "展开全文"}
                </button>
              )}
            </div>
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
              title="根据你的求职偏好与简历画像计算的匹配度（越高越契合）"
              className={cn(
                "rounded-md px-2.5 py-1 text-center text-xs font-semibold leading-tight",
                job.match_score >= 50
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary text-muted-foreground",
              )}
            >
              <span className="block text-[10px] font-normal opacity-80">匹配度</span>
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

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="truncate">
      <span className="text-muted-foreground/60">{label} </span>
      <span className="text-foreground/80">{value}</span>
    </div>
  );
}

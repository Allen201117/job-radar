"use client";

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { mapApiSearchJobsToScoredJobs } from "@/lib/client-job-mapping";
import { track } from "@/lib/track";
import type { ScoredJob } from "@/lib/types";
import type { Filters } from "./useJobFilters";

export type DiscoveryPhase = "idle" | "queued" | "running" | "done" | "failed";
export type BrowserDiscoveryState = {
  phase: DiscoveryPhase;
  runId: string | null;
  startedAt: number | null;
  elapsedSec: number;
  note: string;
  // 「刷新公司库」流式：真实进度 X/N 家公司（浏览器发现时为 null，进度条退化为阶段近似）
  progress?: { done: number; total: number } | null;
  // 任务类型：refresh=刷新已收录公司库 / discovery=发现新公司（影响进度条文案）
  kind?: "refresh" | "discovery";
};

const DISCOVERY_POLL_MS = 6000;
// 给到 20min 硬上限（> 典型刷新 1–5min；卡死由 status 端读时 staleness 15min 兜底终态）。
// 关键防丢数据靠「流式每轮并入 officialJobs」——即便超时，已入列的新岗位不清空。
const DISCOVERY_TIMEOUT_MS = 20 * 60 * 1000;
// 后台「浏览器发现」任务跨页面持久化的 localStorage 键（切到别的页面再回来不丢任务）
const DISCOVERY_STORAGE_KEY = "jobradar:browser-discovery";

function saveDiscoveryTask(runId: string, startedAt: number, query: string) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(
      DISCOVERY_STORAGE_KEY,
      JSON.stringify({ runId, startedAt, query }),
    );
  } catch {
    // localStorage 不可用（隐私模式等）时静默降级，不影响当前会话内轮询
  }
}

function clearDiscoveryTask() {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(DISCOVERY_STORAGE_KEY);
  } catch {
    // 同上
  }
}

type UseDiscoveryPollArgs = {
  // 当前筛选（读 keyword/city/jobType/company 作为抓取范围）
  filters: Filters;
  // 把流式产出的新岗位并入会话列表（调用方持有 officialJobs 状态）
  setOfficialJobs: Dispatch<SetStateAction<ScoredJob[]>>;
  // 触发/完成/失败/超时时的提示文案出口
  setSearchInfo: Dispatch<SetStateAction<string>>;
};

// BrowserDiscovery 状态机 + 轮询 setInterval + localStorage 任务持久化 + 超时/staleness 处理。
// 从 jobs-client 抽出，行为保持不变（轮询间隔/超时常量、流式并入语义均未改）。
export function useDiscoveryPoll({
  filters,
  setOfficialJobs,
  setSearchInfo,
}: UseDiscoveryPollArgs) {
  const [refreshing, setRefreshing] = useState(false);
  const [discovery, setDiscovery] = useState<BrowserDiscoveryState>({
    phase: "idle",
    runId: null,
    startedAt: null,
    elapsedSec: 0,
    note: "",
  });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const discoveryActive = discovery.phase === "queued" || discovery.phase === "running";

  // 按需「浏览器发现」：触发后台 Playwright 抓取官方 SPA 招聘站，前端轮询状态。
  async function startDiscovery() {
    const query = filters.keyword;
    if (!query) {
      setSearchInfo("请先在「关键词」里输入要发现的方向（如 算法 / 产品 / 数据分析）。");
      return;
    }
    setSearchInfo("");
    const startedAt = Date.now();
    setDiscovery({
      phase: "queued",
      runId: null,
      startedAt,
      elapsedSec: 0,
      note: "正在触发后台浏览器抓取…",
    });
    try {
      const resp = await fetch("/api/discovery/dispatch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          city: filters.city || "",
          jobType: filters.jobType || "",
          limit: 30,
        }),
      });
      const data = await resp.json();
      if (!data.ok || !data.run_id) {
        setDiscovery({ phase: "idle", runId: null, startedAt: null, elapsedSec: 0, note: "" });
        clearDiscoveryTask();
        setSearchInfo(formatDispatchError(data));
        return;
      }
      // 持久化任务：切到别的页面再回到岗位库时能恢复轮询、不丢任务
      saveDiscoveryTask(data.run_id, startedAt, query);
      setDiscovery((prev) => ({
        ...prev,
        phase: "queued",
        runId: data.run_id,
        note: "已进入后台队列，等待浏览器抓取…",
      }));
    } catch {
      setDiscovery({ phase: "idle", runId: null, startedAt: null, elapsedSec: 0, note: "" });
      clearDiscoveryTask();
      setSearchInfo("按需发现触发失败，请稍后再试。");
    }
  }

  // 流式并入：把本次轮询已产出的岗位增量并进列表（去重）。刷新/发现共用，每轮调用 →
  // 即便前端超时也不丢已入列的新岗位（修对抗审查 blocker 2「8min 超时 vs 55min CI 静默丢数据」）。
  function mergeStreamedJobs(data: any) {
    const scored = mapApiSearchJobsToScoredJobs(
      data.jobs || [],
      data.query || filters.keyword,
    ) as ScoredJob[];
    // 用户主动触发：只并入有职位描述的可靠岗位（宁缺毋滥，request 1）
    const reliable = scored.filter(hasReliableSummary);
    if (!reliable.length) return;
    setOfficialJobs((prev) => {
      const seen = new Set(prev.map((j) => j.jd_url || j.id));
      const fresh = reliable.filter((j) => !seen.has(j.jd_url || j.id));
      return fresh.length ? [...fresh, ...prev] : prev;
    });
  }

  function finishBrowserDiscovery(data: any) {
    mergeStreamedJobs(data); // 终态兜底再并一次
    setSearchInfo(formatBrowserDiscoveryResult(data));
    setDiscovery({ phase: "idle", runId: null, startedAt: null, elapsedSec: 0, note: "", progress: null });
    clearDiscoveryTask();
  }

  // 跨页面恢复（修「点了发现后切到别的页面、任务就看不到了」的 bug）：
  // 回到岗位库时若 localStorage 里有未超时的发现任务，恢复 runId → 下方轮询 effect 自动续上。
  useEffect(() => {
    if (typeof window === "undefined") return;
    let saved: { runId?: string; startedAt?: number; query?: string } | null = null;
    try {
      const raw = localStorage.getItem(DISCOVERY_STORAGE_KEY);
      saved = raw ? JSON.parse(raw) : null;
    } catch {
      saved = null;
    }
    if (!saved?.runId || !saved.startedAt) return;
    const elapsed = Date.now() - saved.startedAt;
    if (elapsed >= DISCOVERY_TIMEOUT_MS) {
      clearDiscoveryTask();
      return;
    }
    setDiscovery({
      phase: "running",
      runId: saved.runId,
      startedAt: saved.startedAt,
      elapsedSec: Math.floor(elapsed / 1000),
      note: "已恢复后台发现任务，继续等待结果…",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 轮询 + 计时：runId 一旦确定就开始，终态/卸载时清理。
  useEffect(() => {
    if (!discovery.runId) return;
    const runId = discovery.runId;
    let stopped = false;

    tickRef.current = setInterval(() => {
      setDiscovery((prev) =>
        prev.startedAt
          ? { ...prev, elapsedSec: Math.floor((Date.now() - prev.startedAt) / 1000) }
          : prev,
      );
    }, 1000);

    async function poll() {
      try {
        const resp = await fetch(`/api/discovery/status?runId=${runId}`);
        const data = await resp.json();
        if (stopped) return;
        if (!data.ok) return; // 暂时性错误，下次轮询再试
        mergeStreamedJobs(data); // 流式：每轮把已产出岗位增量并入列表
        if (data.is_terminal) {
          finishBrowserDiscovery(data);
          return;
        }
        // 进度条用真实 X/N（status 端返回 diagnostics.progress）。
        setDiscovery((prev) =>
          prev.runId === runId
            ? { ...prev, phase: "running", progress: data.progress || prev.progress }
            : prev,
        );
      } catch {
        // 网络抖动忽略，等下次轮询
      }
    }

    pollRef.current = setInterval(poll, DISCOVERY_POLL_MS);
    poll();

    const timeout = setTimeout(() => {
      if (stopped) return;
      // 不清空已流式入列的新岗位；仅收起进度并提示后台可能仍在补充。
      setDiscovery({ phase: "idle", runId: null, startedAt: null, elapsedSec: 0, note: "", progress: null });
      clearDiscoveryTask();
      setSearchInfo("后台仍在刷新，已入库的新岗位见列表；可稍后刷新页面查看其余。");
    }, DISCOVERY_TIMEOUT_MS);

    return () => {
      stopped = true;
      if (pollRef.current) clearInterval(pollRef.current);
      if (tickRef.current) clearInterval(tickRef.current);
      clearTimeout(timeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [discovery.runId]);

  // 「刷新公司库」（全异步·流式）：触发后台 CI 刷新用户范围内全部公司源（含飞书/北森/Moka 等浏览器源），
  // 复用 discovery 轮询轨道，结果实时流式并入列表。取代只覆盖少数源(~11)的旧同步 /api/search。
  async function startRefresh() {
    if (refreshing || discoveryActive) return; // 进行中不重复触发（后端另有节流/幂等兜底）
    track("refresh_click");
    setRefreshing(true);
    setSearchInfo("正在触发刷新你的公司库…");
    const startedAt = Date.now();
    try {
      const resp = await fetch("/api/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company: filters.company || "",
          keyword: filters.keyword || "",
          city: filters.city || "",
          jobType: filters.jobType || "",
        }),
      });
      const data = await resp.json();
      if (resp.status === 429) {
        setSearchInfo(data?.hint || `刚刷过，约 ${data?.retry_after_sec ?? 60} 秒后可再刷。`);
        return;
      }
      if (!data.ok || !data.run_id) {
        setSearchInfo(data?.hint || data?.error || "刷新触发失败，请稍后再试。");
        return;
      }
      const total = Number(data.scope?.total || 0);
      saveDiscoveryTask(data.run_id, startedAt, filters.keyword || "");
      setDiscovery({
        phase: "queued",
        runId: data.run_id,
        startedAt,
        elapsedSec: 0,
        note: data.reused ? "已有一次刷新在进行中，继续等待…" : `已排队，正在刷新 ${total} 家公司…`,
        progress: { done: 0, total },
        kind: "refresh",
      });
    } catch {
      setSearchInfo("刷新触发失败，请稍后再试。");
    } finally {
      setRefreshing(false);
    }
  }

  return { discovery, refreshing, discoveryActive, startDiscovery, startRefresh };
}

// 用户主动触发的爬取必须返回有职位描述的可靠卡片（request 1）：过滤 summary 为空/过短的岗位。
function hasReliableSummary(job: ScoredJob) {
  return (job.summary ?? "").trim().length >= 10;
}

function formatDispatchError(data: any) {
  const MAP: Record<string, string> = {
    dispatch_not_configured:
      "按需「浏览器发现」未启用：服务端缺少 GITHUB_DISPATCH_TOKEN / GITHUB_DISPATCH_REPO 配置。",
    run_insert_failed: "发现任务创建失败：请确认已应用数据库迁移 009（discovery_runs 异步列）。",
    dispatch_failed: `触发后台抓取失败：${data?.detail || ""}`,
    invalid_input: "入参不合法，请检查关键词后重试。",
    Unauthorized: "未登录或会话已过期，请重新登录后再试。",
  };
  return MAP[data?.error] || data?.error_message || data?.error || "按需发现触发失败，请稍后再试。";
}

function formatBrowserDiscoveryResult(data: any) {
  const isDone =
    data?.phase === "done" || data?.status === "success" || data?.status === "partial_success";
  if (isDone) {
    const created = data?.jobs_created ?? 0;
    const updated = data?.jobs_updated ?? 0;
    const shown = data?.total ?? 0;
    if (created > 0 || updated > 0 || shown > 0) {
      return `浏览器发现完成：新增 ${created} / 更新 ${updated} 个官方岗位，本次展示 ${shown} 个（已入共享库）。`;
    }
    return "浏览器发现完成，但本次没有命中该关键词的官方岗位——换个关键词或去掉城市再试。";
  }
  const MAP: Record<string, string> = {
    no_recipe_matched: "暂无匹配的平台配方（当前覆盖字节 / 飞书系：蔚来·小鹏·地平线·小米）。",
    no_spa_sources_in_db: "未找到可抓取的官方源——请先应用迁移 010（seed SPA 源）。",
    no_jobs_passed_quality: "抓到岗位但未通过质量门 / 未命中关键词，未入库。",
    dispatch_failed: "后台抓取触发失败。",
    discovery_exception: `后台抓取异常：${data?.error_message || ""}`,
  };
  const reason = data?.failure_reason || "";
  return (
    MAP[reason] ||
    `本次发现未成功（${data?.status || "failed"}）：${data?.error_message || reason || "未写入岗位"}。`
  );
}

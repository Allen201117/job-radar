"use client";

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { mapApiSearchJobsToScoredJobs } from "@/lib/client-job-mapping";
import { track } from "@/lib/track";
import type { ScoredJob } from "@/lib/types";
import type { Filters } from "./useJobFilters";

export type DiscoveryPhase = "idle" | "queued" | "running" | "done" | "failed";
// 三个检索（本地查库 / 更新关注公司 / 扩大官方搜索）完成后的「显式完成提示」载荷。
export type RetrievalKind = "local" | "refresh" | "discovery";
export type RetrievalResult = {
  kind: RetrievalKind;
  // success=有结果（绿色）；empty=完成但本轮无新结果（中性）。失败仍走 searchInfo 错误文案，不进此处。
  tone: "success" | "empty";
  title: string;
  detail: string;
};
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
  // 触发/进行中/失败/超时时的过程文案出口（不再承载「完成」语义，完成走 setResult）
  setSearchInfo: Dispatch<SetStateAction<string>>;
  // 终态显式「完成提示」出口：成功/空结果时写入，失败置空保留 searchInfo 错误文案
  setResult: Dispatch<SetStateAction<RetrievalResult | null>>;
};

// BrowserDiscovery 状态机 + 轮询 setInterval + localStorage 任务持久化 + 超时/staleness 处理。
// 从 jobs-client 抽出，行为保持不变（轮询间隔/超时常量、流式并入语义均未改）。
export function useDiscoveryPoll({
  filters,
  setOfficialJobs,
  setSearchInfo,
  setResult,
}: UseDiscoveryPollArgs) {
  const [refreshing, setRefreshing] = useState(false);
  // 当前在跑的检索类型：finish 时据此给出对应文案（poll 闭包读不到最新 discovery.kind，用 ref 兜稳）。
  const kindRef = useRef<"refresh" | "discovery">("discovery");
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
  // 按任务类型区分进行态：刷新进行时只「刷新对口公司」转圈、发掘进行时只「发掘新公司」转圈。
  // 治 bug：discoveryActive 不分 kind，导致点「刷新对口公司」时转圈错误地显示在第 3 个「发掘」按钮上。
  const refreshActive = discoveryActive && discovery.kind === "refresh";
  const discoverActive = discoveryActive && discovery.kind !== "refresh";

  // 按需「浏览器发现」：触发后台 Playwright 抓取官方 SPA 招聘站，前端轮询状态。
  async function startDiscovery() {
    const query = filters.keyword;
    if (!query) {
      setSearchInfo("请先在「关键词」里输入要发现的方向（如 算法 / 产品 / 数据分析）。");
      return;
    }
    setSearchInfo("");
    setResult(null); // 清掉上一轮的完成提示
    kindRef.current = "discovery";
    const startedAt = Date.now();
    setDiscovery({
      phase: "queued",
      runId: null,
      startedAt,
      elapsedSec: 0,
      note: "正在准备发掘…",
      kind: "discovery",
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
        note: "已排队，正在去官网搜索…",
      }));
    } catch {
      setDiscovery({ phase: "idle", runId: null, startedAt: null, elapsedSec: 0, note: "" });
      clearDiscoveryTask();
      setSearchInfo("扩大搜索触发失败，请稍后再试。");
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
    // 优先用 status 返回的真实 mode（跨页恢复时 kindRef 会丢失），兜底用本地 kindRef。
    const kind =
      data?.mode === "company_refresh"
        ? "refresh"
        : data?.mode === "browser_discovery"
          ? "discovery"
          : kindRef.current;
    const done = buildCompletion(data, kind);
    if (done) {
      setResult(done); // 显式「完成」提示（成功 / 空结果）
      setSearchInfo(""); // 清掉「正在更新…」过程文案，避免与完成提示重复
    } else {
      setSearchInfo(formatBrowserDiscoveryResult(data)); // 失败：保留错误文案
    }
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
      setSearchInfo("后台仍在更新，已找到的新岗位见列表；可稍后重开页面查看其余。");
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
    setResult(null); // 清掉上一轮的完成提示
    kindRef.current = "refresh";
    setSearchInfo("正在刷新对口公司…");
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
        setSearchInfo(data?.hint || `刚更新过，约 ${data?.retry_after_sec ?? 60} 秒后可再试。`);
        return;
      }
      if (!data.ok || !data.run_id) {
        setSearchInfo(data?.hint || friendlyFailure(data?.error, "更新触发失败，请稍后再试。"));
        return;
      }
      const total = Number(data.scope?.total || 0);
      saveDiscoveryTask(data.run_id, startedAt, filters.keyword || "");
      setDiscovery({
        phase: "queued",
        runId: data.run_id,
        startedAt,
        elapsedSec: 0,
        note: data.reused ? "已有一次更新在进行中，继续等待…" : `已排队，正在更新 ${total} 家公司…`,
        progress: { done: 0, total },
        kind: "refresh",
      });
    } catch {
      setSearchInfo("更新触发失败，请稍后再试。");
    } finally {
      setRefreshing(false);
    }
  }

  return { discovery, refreshing, discoveryActive, refreshActive, discoverActive, startDiscovery, startRefresh };
}

// 用户主动触发的爬取必须返回有职位描述的可靠卡片（request 1）：过滤 summary 为空/过短的岗位。
function hasReliableSummary(job: ScoredJob) {
  return (job.summary ?? "").trim().length >= 10;
}

// 失败原因 → 给用户看的人话。后端真实 code（dispatch error / failure_reason）一律翻成普通话，
// 绝不把 parser_missing / provider_rate_limited 这类原始代码、迁移号或环境变量名直接抛给用户。
const FRIENDLY_FAILURE: Record<string, string> = {
  parser_missing: "该招聘站暂未支持解析（已记录，会逐步覆盖）。",
  provider_rate_limited: "外部查询达到今日上限，明天再试。",
  rate_limited: "外部查询达到今日上限，明天再试。",
  daily_search_budget_exhausted: "今日官方搜索额度已用完，明天再试。",
  cooldown_active: "刚查过，请稍等一会儿再试。",
  empty_scope: "没有可更新的公司——先在上方选公司或城市，或在偏好里设置目标公司。",
  sources_lookup_failed: "读取公司源失败，请稍后再试。",
  no_recipe_matched: "这个方向暂时没有可联网抓取的官方站点。",
  no_spa_sources_in_db: "暂时没有可联网抓取的官方源。",
  no_jobs_passed_quality: "抓到一些岗位但没有可靠的职位描述，已跳过。",
  dispatch_not_configured: "扩大搜索暂时不可用（服务未配置），请稍后再试。",
  dispatch_failed: "扩大搜索触发失败，请稍后再试。",
  dispatch_rate_limited: "GitHub Actions 平台限流（非每日额度），稍等几分钟再试。",
  run_insert_failed: "任务创建失败，请稍后再试。",
  discovery_exception: "扩大搜索时后台出错了，请稍后再试。",
  invalid_input: "输入有误，请检查关键词后重试。",
  Unauthorized: "登录已过期，请重新登录后再试。",
};

function friendlyFailure(code: string | null | undefined, fallback: string): string {
  if (!code) return fallback;
  return FRIENDLY_FAILURE[code] || fallback;
}

function formatDispatchError(data: any) {
  return friendlyFailure(data?.error, "扩大搜索触发失败，请稍后再试。");
}

// 终态结果 → 显式「完成」提示载荷（成功 / 空结果）。失败返回 null（仍交给 searchInfo 错误文案）。
function buildCompletion(
  data: any,
  kind: "refresh" | "discovery",
): RetrievalResult | null {
  const isDone =
    data?.phase === "done" ||
    data?.status === "success" ||
    data?.status === "partial_success";
  if (!isDone) return null;
  const created = Number(data?.jobs_created ?? 0);
  const updated = Number(data?.jobs_updated ?? 0);
  const shown = Number(data?.total ?? 0);
  const got = created + updated;
  // 透明化漏斗：抓了多少家公司（scope）→ 实际命中筛选的有几家（产出岗位的 distinct 公司）。
  const scopeCompanies = Number(data?.scope_companies || 0);
  const producing = new Set(
    (Array.isArray(data?.jobs) ? data.jobs : [])
      .map((j: any) => String(j?.company || "").trim())
      .filter(Boolean),
  ).size;
  if (kind === "refresh") {
    if (got > 0) {
      const fresh =
        created > 0
          ? `新增 ${created} 个新岗位${producing ? `，来自 ${producing} 家公司` : ""}`
          : "暂无新岗位（已有岗位已刷到最新）";
      return {
        kind: "refresh",
        tone: "success",
        title: "刷新对口公司 · 完成",
        detail: scopeCompanies ? `刷新了 ${scopeCompanies} 家对口公司，${fresh}。` : `${fresh}。`,
      };
    }
    return {
      kind: "refresh",
      tone: "empty",
      title: "刷新对口公司 · 完成",
      detail: scopeCompanies
        ? `刷新了 ${scopeCompanies} 家对口公司，但没有同时满足 城市+类型+关键词 的新岗位——可放宽筛选，或这些方向的官方在招本就稀少。`
        : "这次没抓到新岗位，对口公司暂无更新；可换个筛选条件或稍后再试。",
    };
  }
  if (got > 0 || shown > 0) {
    return {
      kind: "discovery",
      tone: "success",
      title: "发掘新公司 · 完成",
      detail:
        created > 0
          ? `新增 ${created} 个新岗位${producing ? `，来自 ${producing} 家公司` : ""}。`
          : "这些公司的在招岗位已在库里，没有新增。",
    };
  }
  return {
    kind: "discovery",
    tone: "empty",
    title: "发掘新公司 · 完成",
    detail: "这次没找到符合该关键词的新公司岗位——换个关键词或去掉城市再试。",
  };
}

function formatBrowserDiscoveryResult(data: any) {
  const isDone =
    data?.phase === "done" || data?.status === "success" || data?.status === "partial_success";
  if (isDone) {
    const created = data?.jobs_created ?? 0;
    const updated = data?.jobs_updated ?? 0;
    const shown = data?.total ?? 0;
    if (created > 0 || updated > 0 || shown > 0) {
      return `发掘完成：新增 ${created} 个新岗位，本次展示 ${shown} 个。`;
    }
    return "发掘完成，但这次没找到符合该关键词的新公司岗位——换个关键词或去掉城市再试。";
  }
  return friendlyFailure(
    data?.failure_reason,
    "这次扩大搜索没有结果，可换个关键词或稍后再试。",
  );
}

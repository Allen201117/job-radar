"use client";

import { useEffect, useState } from "react";
import { CircleNotch } from "@phosphor-icons/react";
import { createBrowserClient } from "@/lib/supabaseClient";
import { fetchAllSources } from "@/lib/supabase-paginate";
import type { Source, CrawlRun } from "@/lib/types";

// 抓取结果的英文状态别直接甩在页面上——管理员看板的读者是产品经理，不是工程师。
const RUN_STATUS_LABEL: Record<string, string> = {
  success: "抓到了",
  partial_success: "只抓到一部分",
  failed: "抓失败",
  skipped: "按规则跳过",
};

// crawl_runs 的 running 是「已开跑未收尾」的占位符（迁移 234）。同一个值有两种含义，
// 差别只在时间：刚开跑 = 真的在抓；过了宽限期还是它 = 那轮进程死了，这个源就地失踪。
// 宽限期与 crawler/ops_watchdog.UNFINISHED_GRACE_MINUTES 同口径（近 30 天最长一轮 27 分钟）。
const RUN_UNFINISHED_GRACE_MS = 90 * 60 * 1000;

function runStatusLabel(run: CrawlRun): string {
  if (run.status === "running") {
    const startedAt = run.started_at ? new Date(run.started_at).getTime() : NaN;
    return Number.isFinite(startedAt) && Date.now() - startedAt < RUN_UNFINISHED_GRACE_MS
      ? "正在抓"
      : "跑到一半没收尾";
  }
  return (run.status && RUN_STATUS_LABEL[run.status]) || run.status || "—";
}

export default function SourceTable({ reloadSignal = 0 }: { reloadSignal?: number }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [latestRuns, setLatestRuns] = useState<Record<string, CrawlRun>>({});
  const [loading, setLoading] = useState(true);
  // 正在切换的源 id + 失败提示：这个开关原来点下去到写库返回之间毫无反应，失败还完全静默（用户以为切成功了）。
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [toggleError, setToggleError] = useState("");
  const supabase = createBrowserClient();

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadSignal]);

  async function loadData() {
    // ⚠️ 必须分页拉全量（sources 1121 行 > PostgREST 单次 1000 行上限），否则管理页只显示前 1000 个源。
    // 分页排序键固定 id（稳定），展示要的公司名序在内存里排。
    try {
      const srcData = await fetchAllSources<Source>(supabase, "*");
      srcData.sort((a, b) => (a.company || "").localeCompare(b.company || "", "zh-Hans-CN"));
      setSources(srcData);
    } catch (e) {
      console.warn("[SourceTable] sources 加载失败:", (e as Error).message);
    }

    // 取每个 source 最近一次 crawl_run
    const { data: runs } = await supabase
      .from("crawl_runs")
      .select("*")
      .order("started_at", { ascending: false })
      .limit(50);

    if (runs) {
      const map: Record<string, CrawlRun> = {};
      for (const run of runs) {
        if (run.source_id && !map[run.source_id]) {
          map[run.source_id] = run;
        }
      }
      setLatestRuns(map);
    }

    setLoading(false);
  }

  async function toggleSource(source: Source) {
    if (togglingId) return;
    setTogglingId(source.id);
    setToggleError("");
    const { error } = await supabase
      .from("sources")
      .update({ enabled: !source.enabled })
      .eq("id", source.id);

    if (error) {
      setToggleError(`${source.company}：切换失败（${error.message}），状态未改变。`);
    } else {
      setSources((prev) =>
        prev.map((s) =>
          s.id === source.id ? { ...s, enabled: !s.enabled } : s,
        ),
      );
    }
    setTogglingId(null);
  }

  if (loading) {
    return <p className="surface p-5 text-sm ink-2">加载中...</p>;
  }

  return (
    <div className="surface overflow-x-auto px-4 ink-1">
      {toggleError && (
        <p className="mt-4 rounded-xl border border-tone-rose-border bg-tone-rose-bg px-3 py-2 text-sm text-tone-rose-fg">
          {toggleError}
        </p>
      )}
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-black/[0.06] text-left text-xs font-medium ink-3 dark:border-white/[0.1]">
            <th className="py-2 pr-4">公司</th>
            <th className="py-2 pr-4">官方招聘页</th>
            <th className="py-2 pr-4">抓取方式</th>
            <th className="py-2 pr-4">启用</th>
            <th className="py-2 pr-4">上次抓取时间</th>
            <th className="py-2 pr-4">上次结果</th>
            <th className="py-2">备注</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((source) => {
            const run = latestRuns[source.id];
            return (
              <tr key={source.id} className="border-b border-black/[0.06] last:border-0 dark:border-white/[0.1]">
                <td className="py-2 pr-4 font-medium">{source.company}</td>
                <td className="max-w-[200px] truncate py-2 pr-4">
                  <a
                    href={source.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-tone-sky-fg hover:text-[#2f6299] hover:underline dark:hover:text-[#7fb2e8]"
                  >
                    {source.source_url}
                  </a>
                </td>
                <td className="py-2 pr-4">{source.crawl_method}</td>
                <td className="py-2 pr-4">
                  <button
                    onClick={() => toggleSource(source)}
                    disabled={togglingId !== null}
                    aria-busy={togglingId === source.id}
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium transition disabled:opacity-50 ${
                      source.enabled
                        ? "bg-[#cde8a0] text-[#3f5a1c] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]"
                        : "bg-[#f3d9d2] text-tone-rose-fg dark:bg-[#3a201a]"
                    }`}
                  >
                    {togglingId === source.id && (
                      <CircleNotch size={11} weight="bold" className="animate-spin" aria-hidden="true" />
                    )}
                    {togglingId === source.id ? "切换中" : source.enabled ? "启用" : "禁用"}
                  </button>
                </td>
                <td className="py-2 pr-4 text-xs ink-3">
                  {source.last_checked_at
                    ? new Date(source.last_checked_at).toLocaleString("zh-CN")
                    : "—"}
                </td>
                <td className="py-2 pr-4">
                  {run ? (
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        run.status === "success"
                          ? "bg-[#cde8a0] text-[#3f5a1c] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]"
                          : run.status === "partial_success"
                            ? "bg-[#f6d6a8] text-[#8a5a12] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]"
                            : "bg-[#f3d9d2] text-tone-rose-fg dark:bg-[#3a201a]"
                      }`}
                    >
                      {runStatusLabel(run)}
                      {run.jobs_found > 0 && `(${run.jobs_found})`}
                    </span>
                  ) : (
                    <span className="text-xs ink-3">—</span>
                  )}
                </td>
                <td className="py-2 text-xs ink-3">
                  {source.notes || "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

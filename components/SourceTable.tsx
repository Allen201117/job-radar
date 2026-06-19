"use client";

import { useEffect, useState } from "react";
import { createBrowserClient } from "@/lib/supabaseClient";
import type { Source, CrawlRun } from "@/lib/types";

export default function SourceTable({ reloadSignal = 0 }: { reloadSignal?: number }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [latestRuns, setLatestRuns] = useState<Record<string, CrawlRun>>({});
  const [loading, setLoading] = useState(true);
  const supabase = createBrowserClient();

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadSignal]);

  async function loadData() {
    const { data: srcData } = await supabase
      .from("sources")
      .select("*")
      .order("company");
    if (srcData) setSources(srcData);

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
    const { error } = await supabase
      .from("sources")
      .update({ enabled: !source.enabled })
      .eq("id", source.id);

    if (!error) {
      setSources((prev) =>
        prev.map((s) =>
          s.id === source.id ? { ...s, enabled: !s.enabled } : s,
        ),
      );
    }
  }

  if (loading) {
    return <p className="surface p-5 text-sm text-[#5f594e] dark:text-[#b6ad9d]">加载中...</p>;
  }

  return (
    <div className="surface overflow-x-auto px-4 text-[#1a1714] dark:text-[#f3ecdf]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-black/[0.06] text-left text-xs font-medium text-[#8a8275] dark:border-white/[0.1] dark:text-[#9a9184]">
            <th className="py-2 pr-4">公司</th>
            <th className="py-2 pr-4">URL</th>
            <th className="py-2 pr-4">抓取方式</th>
            <th className="py-2 pr-4">启用</th>
            <th className="py-2 pr-4">最近抓取</th>
            <th className="py-2 pr-4">最近状态</th>
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
                    className="text-[#3f7cc0] hover:text-[#2f6299] hover:underline dark:text-[#7fb2e8] dark:hover:text-[#7fb2e8]"
                  >
                    {source.source_url}
                  </a>
                </td>
                <td className="py-2 pr-4">{source.crawl_method}</td>
                <td className="py-2 pr-4">
                  <button
                    onClick={() => toggleSource(source)}
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      source.enabled
                        ? "bg-[#cde8a0] text-[#3f5a1c] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]"
                        : "bg-[#f3d9d2] text-[#9c4a3c] dark:bg-[#3a201a] dark:text-[#e6a99f]"
                    }`}
                  >
                    {source.enabled ? "启用" : "禁用"}
                  </button>
                </td>
                <td className="py-2 pr-4 text-xs text-[#8a8275] dark:text-[#9a9184]">
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
                            : "bg-[#f3d9d2] text-[#9c4a3c] dark:bg-[#3a201a] dark:text-[#e6a99f]"
                      }`}
                    >
                      {run.status}
                      {run.jobs_found > 0 && ` (${run.jobs_found})`}
                    </span>
                  ) : (
                    <span className="text-xs text-[#9a9184] dark:text-[#837c70]">—</span>
                  )}
                </td>
                <td className="py-2 text-xs text-[#8a8275] dark:text-[#9a9184]">
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

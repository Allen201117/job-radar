"use client";

import { useEffect, useState } from "react";
import { createBrowserClient } from "@/lib/supabaseClient";
import type { Source, CrawlRun } from "@/lib/types";

export default function SourceTable() {
  const [sources, setSources] = useState<Source[]>([]);
  const [latestRuns, setLatestRuns] = useState<Record<string, CrawlRun>>({});
  const [loading, setLoading] = useState(true);
  const supabase = createBrowserClient();

  useEffect(() => {
    loadData();
  }, []);

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
    return <p className="rounded-[1.35rem] border border-white/10 bg-white/[0.055] p-5 text-sm text-white/56">加载中...</p>;
  }

  return (
    <div className="overflow-x-auto rounded-[1.35rem] border border-white/10 bg-white/[0.055] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/10 text-left text-xs font-medium text-white/46">
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
              <tr key={source.id} className="border-b border-white/10 last:border-0">
                <td className="py-2 pr-4 font-medium">{source.company}</td>
                <td className="max-w-[200px] truncate py-2 pr-4">
                  <a
                    href={source.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-sky-300 hover:text-sky-200 hover:underline"
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
                        ? "bg-lime-300 text-lime-950"
                        : "bg-red-400/15 text-red-200"
                    }`}
                  >
                    {source.enabled ? "启用" : "禁用"}
                  </button>
                </td>
                <td className="py-2 pr-4 text-xs text-white/46">
                  {source.last_checked_at
                    ? new Date(source.last_checked_at).toLocaleString("zh-CN")
                    : "—"}
                </td>
                <td className="py-2 pr-4">
                  {run ? (
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        run.status === "success"
                          ? "bg-lime-300 text-lime-950"
                          : run.status === "partial_success"
                            ? "bg-orange-300 text-orange-950"
                            : "bg-red-400/15 text-red-200"
                      }`}
                    >
                      {run.status}
                      {run.jobs_found > 0 && ` (${run.jobs_found})`}
                    </span>
                  ) : (
                    <span className="text-xs text-white/42">—</span>
                  )}
                </td>
                <td className="py-2 text-xs text-white/46">
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

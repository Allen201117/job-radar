"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { MagnifyingGlass, Prohibit, ArrowCounterClockwise } from "@phosphor-icons/react";
import ActionToast, { useActionToast } from "@/components/ActionToast";
import { METRIC_LABEL } from "@/lib/insight-library";
import { ASSERTION_LABEL } from "@/lib/insight-assertion-chip";
import { formatDateLabel } from "@/lib/relative-time";

type Subject = {
  id: string;
  company: string;
  kind: "company" | "business_unit";
  name: string;
  job_count: number;
  origin: string;
  status: string;
  last_seen_at: string | null;
};

type Payload = {
  subjects: Subject[];
  metric_counts: Array<{ key: string; count: number }>;
  assertion_counts: Array<{ key: string; count: number }>;
  pending_review: number;
};

const STATUS_LABEL: Record<string, string> = {
  active: "在用",
  retired: "已退役",
  rejected: "已判噪声",
};

export default function InsightSubjectsAdmin() {
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("business_unit");
  const [status, setStatus] = useState("active");
  const [busy, setBusy] = useState<string | null>(null);
  const { toast, show, dismiss } = useActionToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/insights/admin/subjects");
      const json = await res.json();
      if (!res.ok || !json.ok) throw new Error(json?.error || "load_failed");
      setData(json);
    } catch (e: any) {
      setError(e?.message || "读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => {
    const all = data?.subjects || [];
    const needle = q.trim().toLowerCase();
    return all
      .filter((s) => (kind ? s.kind === kind : true))
      .filter((s) => (status ? s.status === status : true))
      .filter(
        (s) =>
          !needle ||
          s.name.toLowerCase().includes(needle) ||
          s.company.toLowerCase().includes(needle),
      )
      .slice(0, 200);
  }, [data, q, kind, status]);

  async function setSubjectStatus(subject: Subject, next: string) {
    setBusy(subject.id);
    try {
      const res = await fetch("/api/insights/admin/subjects", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ id: subject.id, status: next }),
      });
      const json = await res.json();
      if (!res.ok || !json.ok) throw new Error(json?.error || "failed");
      show({
        text:
          next === "rejected"
            ? `已判「${subject.name}」为噪声，下次抽取不会再抽回来（同时退役 ${json.retired_items} 条洞察）`
            : `已恢复「${subject.name}」`,
      });
      await load();
    } catch (e: any) {
      // 失败绝不静默：点了像没反应，比慢更伤信任。
      show({ text: `处理失败：${e?.message || "未知错误"}`, tone: "error" });
    } finally {
      setBusy(null);
    }
  }

  async function bulk(kindKey: "metric_key" | "assertion", value: string, label: string) {
    if (!window.confirm(`确认把全部「${label}」条目下架（retired）？可以再改回来。`)) return;
    setBusy(`${kindKey}:${value}`);
    try {
      const res = await fetch("/api/insights/admin/subjects", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ [kindKey]: value, status: "retired" }),
      });
      const json = await res.json();
      if (!res.ok || !json.ok) throw new Error(json?.error || "failed");
      show({ text: `已下架 ${json.affected} 条「${label}」` });
      await load();
    } catch (e: any) {
      show({ text: `批量处置失败：${e?.message || "未知错误"}`, tone: "error" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mt-10">
      <header className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="t-h2">洞察主体治理</h2>
        <p className="t-caption ink-3">
          业务线是从岗位标题抽出来的，停用词总会漏。判为「噪声」后**保留行不删**，
          下一轮抽取据此跳过——删行的话下次会原样抽回来。
        </p>
      </header>

      {data && data.pending_review > 0 && (
        <div className="mb-3 rounded-xl border border-[#e7c98a] bg-[#fbeecb] px-4 py-2.5 t-body-sm text-[#8a6312] dark:border-[#e0b15a]/30 dark:bg-[#e0b15a]/[0.12] dark:text-[#e0b15a]">
          有 {data.pending_review} 条 pending_review 条目在排队等人工判定（判官矛盾/低置信）。
          它们不展示给用户，但也没人看过。
        </div>
      )}

      {/* 按指标 / 强度批量处置：枚举化的直接收益——想下架某类主观内容，一键即可 */}
      {data && (
        <div className="mb-4 grid gap-3 rounded-2xl border border-black/[0.06] bg-white/55 p-4 dark:border-white/[0.1] dark:bg-white/[0.05] md:grid-cols-2">
          <div>
            <h3 className="t-h3 mb-2">按指标批量下架</h3>
            <div className="flex flex-wrap gap-1.5">
              {data.metric_counts.map((m) => (
                <button
                  key={m.key}
                  type="button"
                  disabled={busy === `metric_key:${m.key}`}
                  onClick={() => bulk("metric_key", m.key, METRIC_LABEL[m.key] || m.key)}
                  className="rounded-full border border-black/[0.08] bg-white/70 px-2.5 py-1 t-micro ink-2 transition hover:border-[#d99a8a] hover:text-[#9c4a33] disabled:opacity-50 dark:border-white/[0.1] dark:bg-white/[0.06]"
                >
                  {METRIC_LABEL[m.key] || m.key} {m.count}
                </button>
              ))}
            </div>
          </div>
          <div>
            <h3 className="t-h3 mb-2">按断言强度批量下架</h3>
            <div className="flex flex-wrap gap-1.5">
              {data.assertion_counts.map((a) => (
                <button
                  key={a.key}
                  type="button"
                  disabled={busy === `assertion:${a.key}`}
                  onClick={() =>
                    bulk("assertion", a.key, ASSERTION_LABEL[a.key as "fact"] || a.key)
                  }
                  className="rounded-full border border-black/[0.08] bg-white/70 px-2.5 py-1 t-micro ink-2 transition hover:border-[#d99a8a] hover:text-[#9c4a33] disabled:opacity-50 dark:border-white/[0.1] dark:bg-white/[0.06]"
                >
                  {ASSERTION_LABEL[a.key as "fact"] || a.key} {a.count}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="relative">
          <MagnifyingGlass
            size={15}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 ink-4"
          />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜主体或公司"
            className="w-56 rounded-full border border-black/[0.08] bg-white/70 py-1.5 pl-8 pr-3 t-label ink-1 outline-none dark:border-white/[0.1] dark:bg-white/[0.06]"
          />
        </label>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="rounded-full border border-black/[0.08] bg-white/70 px-3 py-1.5 t-label ink-2 dark:border-white/[0.1] dark:bg-white/[0.06]"
        >
          <option value="">全部类型</option>
          <option value="business_unit">业务线</option>
          <option value="company">公司</option>
        </select>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-full border border-black/[0.08] bg-white/70 px-3 py-1.5 t-label ink-2 dark:border-white/[0.1] dark:bg-white/[0.06]"
        >
          <option value="active">在用</option>
          <option value="rejected">已判噪声</option>
          <option value="retired">已退役</option>
          <option value="">全部状态</option>
        </select>
        <button
          type="button"
          onClick={load}
          className="rounded-full border border-black/[0.08] bg-white/70 px-3 py-1.5 t-label ink-2 dark:border-white/[0.1] dark:bg-white/[0.06]"
        >
          刷新
        </button>
      </div>

      {loading && <p className="t-body-sm ink-3">加载中…</p>}
      {error && (
        <p className="t-body-sm text-[#9c4a33] dark:text-[#e8b0a0]">
          读取失败：{error}
          <button type="button" onClick={load} className="ml-2 underline underline-offset-2">
            重试
          </button>
        </p>
      )}

      {!loading && !error && (
        <div className="overflow-x-auto rounded-2xl border border-black/[0.06] bg-white/55 dark:border-white/[0.1] dark:bg-white/[0.05]">
          <table className="w-full min-w-[46rem] border-collapse">
            <thead>
              <tr className="border-b border-black/[0.06] text-left dark:border-white/[0.1]">
                <th className="px-4 py-2.5 t-label ink-3">主体</th>
                <th className="px-4 py-2.5 t-label ink-3">公司</th>
                <th className="px-4 py-2.5 t-label ink-3">在招岗</th>
                <th className="px-4 py-2.5 t-label ink-3">状态</th>
                <th className="px-4 py-2.5 t-label ink-3">最近见到</th>
                <th className="px-4 py-2.5 t-label ink-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="border-b border-black/[0.04] dark:border-white/[0.06]">
                  <td className="px-4 py-2.5 t-body-sm ink-1">{s.name}</td>
                  <td className="px-4 py-2.5 t-body-sm ink-2">{s.company}</td>
                  <td className="px-4 py-2.5 t-body-sm t-num ink-2">{s.job_count}</td>
                  <td className="px-4 py-2.5 t-caption ink-3">{STATUS_LABEL[s.status] || s.status}</td>
                  <td className="px-4 py-2.5 t-caption ink-3">
                    {s.last_seen_at ? formatDateLabel(s.last_seen_at) : "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    {s.status === "rejected" ? (
                      <button
                        type="button"
                        disabled={busy === s.id}
                        onClick={() => setSubjectStatus(s, "active")}
                        className="inline-flex items-center gap-1 rounded-full border border-black/[0.08] bg-white/70 px-2.5 py-1 t-micro ink-2 disabled:opacity-50 dark:border-white/[0.1] dark:bg-white/[0.06]"
                      >
                        <ArrowCounterClockwise size={12} />
                        {busy === s.id ? "处理中…" : "恢复"}
                      </button>
                    ) : (
                      <button
                        type="button"
                        disabled={busy === s.id}
                        onClick={() => setSubjectStatus(s, "rejected")}
                        className="inline-flex items-center gap-1 rounded-full border border-[#d99a8a] bg-[#fbe9e4] px-2.5 py-1 t-micro text-[#9c4a33] disabled:opacity-50 dark:border-[#d99a8a]/30 dark:bg-[#d99a8a]/[0.12] dark:text-[#e8b0a0]"
                      >
                        <Prohibit size={12} />
                        {busy === s.id ? "处理中…" : "判为噪声"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center t-body-sm ink-3">
                    没有符合条件的主体。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <ActionToast toast={toast} onDismiss={dismiss} />
    </section>
  );
}

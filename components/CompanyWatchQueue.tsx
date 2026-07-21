"use client";

import { useCallback, useEffect, useState } from "react";
import { Buildings, CircleNotch } from "@phosphor-icons/react";
import CompanyLogo from "@/components/CompanyLogo";

type WatchItem = {
  normalized_company: string;
  company: string;
  request_count: number;
  status: string;
  resolution_note: string | null;
  first_requested: string;
  last_requested: string;
};

const STATUS_LABEL: Record<string, { label: string; tone: string }> = {
  queued: { label: "待接入", tone: "bg-[#dbe9fa] text-[#2f6299] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]" },
  researching: { label: "确认入口中", tone: "bg-[#fbe6d1] text-[#9a6326] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]" },
  covered: { label: "已覆盖", tone: "bg-[#e6f2d3] text-[#5a7a2f] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]" },
  unsupported: { label: "暂不支持", tone: "bg-[#ece7dd] text-[#6b655a] dark:bg-white/[0.08] dark:text-[#b6ad9d]" },
};

function fmtDate(s: string): string {
  try {
    return new Date(s).toLocaleDateString("zh-CN");
  } catch {
    return "—";
  }
}

export default function CompanyWatchQueue() {
  const [items, setItems] = useState<WatchItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch("/api/company-watch/admin");
      const data = await resp.json();
      if (data?.ok) setItems(data.items || []);
      else setError(data?.error || "加载失败");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function setStatus(item: WatchItem, status: string) {
    let note: string | null = null;
    if (status === "unsupported") {
      note = window.prompt("填写「暂不支持」的人话说明（用户可见）：", item.resolution_note || "");
      if (note === null) return; // 取消
    }
    setBusy(item.normalized_company);
    setError("");
    try {
      const resp = await fetch("/api/company-watch/admin", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ normalized_company: item.normalized_company, status, resolution_note: note }),
      });
      const data = await resp.json();
      if (!resp.ok || !data?.ok) throw new Error(data?.error || `HTTP ${resp.status}`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="surface p-5 text-[#1a1714] dark:text-[#f3ecdf]">
      <div className="flex items-center gap-2">
        <Buildings size={18} weight="fill" className="text-[#5f594e] dark:text-[#b6ad9d]" aria-hidden="true" />
        <h2 className="text-base font-semibold">用户希望监控的公司</h2>
      </div>
      <p className="mt-1 text-sm text-[#8a8275] dark:text-[#9a9184]">
        用户在「关注与偏好」里加的公司。已覆盖的会自动标记；其余按请求人数排队，确认官方入口后用上方「添加源」接入，再标「已覆盖」。
      </p>

      {error && (
        <p className="mt-3 rounded-xl border border-[#e0b4ac] bg-[#f7e6e1] px-3 py-2 text-sm text-[#9c4a3c] dark:border-[#7a392e]/[0.6] dark:bg-[#3a201a] dark:text-[#e6a99f]">
          {error}
        </p>
      )}

      {loading ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-[#8a8275] dark:text-[#9a9184]">
          <CircleNotch size={16} weight="bold" className="animate-spin" aria-hidden="true" />
          加载中…
        </div>
      ) : items.length === 0 ? (
        <p className="mt-4 text-sm text-[#8a8275] dark:text-[#9a9184]">暂无用户关注请求。</p>
      ) : (
        <ul className="mt-4 space-y-2.5">
          {items.map((item) => {
            const meta = STATUS_LABEL[item.status] || STATUS_LABEL.queued;
            const isBusy = busy === item.normalized_company;
            return (
              <li
                key={item.normalized_company}
                className="rounded-2xl border border-black/[0.07] bg-white/45 p-3.5 dark:border-white/[0.1] dark:bg-white/[0.04]"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="flex items-center gap-1.5 font-semibold">
                    <CompanyLogo company={item.company} size={22} />
                    {item.company}
                  </span>
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${meta.tone}`}>{meta.label}</span>
                  <span className="text-xs text-[#8a8275] dark:text-[#9a9184]">{item.request_count} 人关注</span>
                  <span className="ml-auto text-xs text-[#9a9184] dark:text-[#837c70]">
                    首次 {fmtDate(item.first_requested)} · 最近 {fmtDate(item.last_requested)}
                  </span>
                </div>
                {item.resolution_note && (
                  <p className="mt-1.5 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">说明：{item.resolution_note}</p>
                )}
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  <QueueBtn disabled={isBusy} onClick={() => setStatus(item, "researching")}>标记确认入口中</QueueBtn>
                  <QueueBtn disabled={isBusy} onClick={() => setStatus(item, "covered")}>标记已覆盖</QueueBtn>
                  <QueueBtn disabled={isBusy} onClick={() => setStatus(item, "unsupported")}>标记暂不支持</QueueBtn>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function QueueBtn({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-full border border-black/[0.08] bg-white/70 px-3 py-1.5 text-xs font-medium text-[#3f3a33] transition hover:bg-white active:scale-[0.98] disabled:opacity-50 dark:border-white/[0.12] dark:bg-white/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.08]"
    >
      {children}
    </button>
  );
}

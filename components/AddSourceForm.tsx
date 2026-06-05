"use client";

import { useState } from "react";
import { Plus, X } from "@phosphor-icons/react";
import {
  SOURCE_ADAPTERS,
  CRAWL_METHODS,
  type AdapterOption,
} from "@/lib/source-adapters";
import type { Source } from "@/lib/types";

interface Props {
  onAdded: (source: Source) => void;
}

const EMPTY = {
  company: "",
  source_url: "",
  adapter_name: "",
  crawl_method: "http",
  notes: "",
  enabled: true,
};

export default function AddSourceForm({ onAdded }: Props) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const selectedAdapter: AdapterOption | undefined = SOURCE_ADAPTERS.find(
    (a) => a.value === form.adapter_name,
  );

  function set<K extends keyof typeof EMPTY>(key: K, value: (typeof EMPTY)[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function reset() {
    setForm({ ...EMPTY });
    setError("");
    setFieldErrors({});
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    setFieldErrors({});
    try {
      const res = await fetch("/api/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        if (data.errors) setFieldErrors(data.errors);
        setError(
          data.error === "validation_failed"
            ? "请检查表单填写"
            : data.error || "添加失败",
        );
        return;
      }
      onAdded(data.source as Source);
      reset();
      setOpen(false);
    } catch (err) {
      setError((err as Error).message || "添加失败");
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-2 rounded-full bg-[#1a1714] px-4 py-2 text-sm font-semibold text-[#f7f1e6] transition duration-200 hover:bg-[#2b2520] active:scale-[0.98]"
      >
        <Plus size={16} weight="bold" aria-hidden="true" />
        添加源
      </button>
    );
  }

  return (
    <form
      onSubmit={submit}
      className="surface p-5 text-[#1a1714]"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">添加招聘源</h3>
        <button
          type="button"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          className="rounded-full bg-black/[0.05] p-1.5 text-[#5f594e] transition hover:bg-black/[0.08] hover:text-[#1a1714]"
        >
          <X size={16} weight="bold" />
        </button>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="公司" error={fieldErrors.company}>
          <input
            value={form.company}
            onChange={(e) => set("company", e.target.value)}
            placeholder="如 Stripe / 字节跳动"
            className={inputCls}
          />
        </Field>

        <Field label="adapter" error={fieldErrors.adapter_name}>
          <select
            value={form.adapter_name}
            onChange={(e) => set("adapter_name", e.target.value)}
            className={inputCls}
          >
            <option value="">请选择 adapter…</option>
            {SOURCE_ADAPTERS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="招聘源地址" error={fieldErrors.source_url} className="sm:col-span-2">
          <input
            value={form.source_url}
            onChange={(e) => set("source_url", e.target.value)}
            placeholder="https://boards.greenhouse.io/yourcompany"
            className={inputCls}
          />
        </Field>

        <Field label="抓取方式" error={fieldErrors.crawl_method}>
          <select
            value={form.crawl_method}
            onChange={(e) => set("crawl_method", e.target.value)}
            className={inputCls}
          >
            {CRAWL_METHODS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </Field>

        <Field label="启用">
          <label className="inline-flex items-center gap-2 text-sm text-[#5f594e]">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => set("enabled", e.target.checked)}
              className="size-4 accent-[#1a1714]"
            />
            创建后立即启用（次日抓取生效）
          </label>
        </Field>

        <Field label="备注（选填）" className="sm:col-span-2">
          <input
            value={form.notes}
            onChange={(e) => set("notes", e.target.value)}
            placeholder="给自己看的说明，如「2026Q2 新增外企 ATS」"
            className={inputCls}
          />
        </Field>
      </div>

      {selectedAdapter?.hint && (
        <p className="mt-3 rounded-lg border border-[#bcd2ed] bg-[#e8f1fc] px-3 py-2 text-xs leading-5 text-[#2f6299]">
          {selectedAdapter.hint}
        </p>
      )}

      {error && (
        <p className="mt-3 rounded-lg border border-[#e0b4ac] bg-[#f7e6e1] px-3 py-2 text-sm text-[#9c4a3c]">{error}</p>
      )}

      <div className="mt-4 flex gap-2">
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center gap-2 rounded-full bg-[#1a1714] px-4 py-2 text-sm font-semibold text-[#f7f1e6] transition hover:bg-[#2b2520] active:scale-[0.98] disabled:opacity-50"
        >
          {submitting ? "保存中…" : "保存源"}
        </button>
        <button
          type="button"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          className="rounded-full px-4 py-2 text-sm font-medium text-[#8a8275] transition hover:bg-black/[0.05] hover:text-[#1a1714]"
        >
          取消
        </button>
      </div>
    </form>
  );
}

const inputCls =
  "w-full rounded-lg border border-black/[0.09] bg-white/70 px-3 py-2 text-sm text-[#1a1714] outline-none placeholder:text-[#a39a8c] focus:border-[#1a1714]/55 focus:bg-white";

function Field({
  label,
  error,
  className,
  children,
}: {
  label: string;
  error?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={className}>
      <label className="mb-1.5 block text-xs font-medium text-[#8a8275]">{label}</label>
      {children}
      {error && <p className="mt-1 text-xs text-[#9c4a3c]">{error}</p>}
    </div>
  );
}

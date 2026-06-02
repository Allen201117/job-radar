"use client";

import { useState } from "react";

interface Props {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}

export default function TagInput({ values, onChange, placeholder }: Props) {
  const [draft, setDraft] = useState("");

  function commit() {
    const parts = draft
      .split(/[,，、\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (parts.length) {
      onChange(Array.from(new Set([...(values || []), ...parts])));
    }
    setDraft("");
  }

  function remove(v: string) {
    onChange((values || []).filter((x) => x !== v));
  }

  return (
    <div className="mt-1 flex flex-wrap items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.07] px-2 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] transition duration-200 focus-within:border-sky-300">
      {(values || []).map((v) => (
        <span
          key={v}
          className="flex items-center gap-1 rounded-full border border-sky-300/20 bg-sky-300/10 px-2.5 py-1 text-xs font-medium text-sky-100"
        >
          {v}
          <button
            type="button"
            onClick={() => remove(v)}
            className="text-sky-100/56 transition-colors hover:text-red-200"
            aria-label={`移除 ${v}`}
          >
            ×
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit();
          } else if (e.key === "Backspace" && !draft && values?.length) {
            remove(values[values.length - 1]);
          }
        }}
        onBlur={commit}
        placeholder={(values || []).length ? "" : placeholder}
        className="min-w-[90px] flex-1 border-0 bg-transparent px-1 py-0.5 text-sm text-white outline-none placeholder:text-white/32"
      />
    </div>
  );
}

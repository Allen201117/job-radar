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
    <div className="mt-1 flex flex-wrap items-center gap-1.5 rounded-md border px-2 py-1.5">
      {(values || []).map((v) => (
        <span
          key={v}
          className="flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-xs"
        >
          {v}
          <button
            type="button"
            onClick={() => remove(v)}
            className="text-muted-foreground hover:text-destructive"
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
        className="min-w-[90px] flex-1 border-0 bg-transparent px-1 py-0.5 text-sm outline-none"
      />
    </div>
  );
}

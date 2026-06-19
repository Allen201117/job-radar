"use client";

import { useState, useEffect } from "react";
import { createBrowserClient } from "@/lib/supabaseClient";
import type { UserPreferences } from "@/lib/types";
import TagInput from "./TagInput";
import SaveToast, { type SaveState } from "@/components/SaveToast";
import { CheckCircle, SlidersHorizontal } from "@phosphor-icons/react";

export default function PreferenceForm() {
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [message, setMessage] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveErr, setSaveErr] = useState("");
  const supabase = createBrowserClient();

  useEffect(() => {
    loadPrefs();
    function handleResumePreferencesUpdated() {
      loadPrefs();
    }
    window.addEventListener("resume-preferences-updated", handleResumePreferencesUpdated);
    return () => {
      window.removeEventListener("resume-preferences-updated", handleResumePreferencesUpdated);
    };
  }, []);

  async function loadPrefs() {
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) {
      setMessage("请先登录。");
      return;
    }
    const { data, error } = await supabase
      .from("user_preferences")
      .select("*")
      .eq("user_id", user.id)
      .single();
    if (data) {
      setPrefs(data);
    } else if (!error || error.code === "PGRST116") {
      setPrefs(createEmptyPrefs(user.id));
    } else {
      setMessage("加载失败: " + error.message);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaveState("saving");
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user || !prefs) {
      setSaveErr("请先登录。");
      setSaveState("error");
      return;
    }
    const { error } = await supabase.from("user_preferences").upsert(
      {
        user_id: user.id,
        target_locations: prefs.target_locations,
        target_roles: prefs.target_roles,
        target_keywords: prefs.target_keywords,
        exclude_keywords: prefs.exclude_keywords,
        target_companies: prefs.target_companies,
        daily_limit: prefs.daily_limit,
      },
      { onConflict: "user_id" },
    );
    if (error) {
      setSaveErr("保存失败：" + error.message);
      setSaveState("error");
    } else {
      setSaveState("done");
    }
  }

  function setArray(field: keyof UserPreferences, arr: string[]) {
    if (!prefs) return;
    setPrefs({ ...prefs, [field]: arr } as UserPreferences);
  }

  if (!prefs) {
    return (
      <div className="surface p-5 text-sm text-[#5f594e] dark:text-[#b6ad9d]">
        加载中...
      </div>
    );
  }

  return (
    <form onSubmit={handleSave} className="surface space-y-5 p-5 text-[#1a1714] dark:text-[#f3ecdf]">
      <div className="flex items-center gap-2">
        <div className="grid size-9 place-items-center rounded-xl bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]">
          <SlidersHorizontal size={18} weight="fill" aria-hidden="true" />
        </div>
        <div>
          <h2 className="text-base font-semibold">求职偏好</h2>
          <p className="text-sm text-[#8a8275] dark:text-[#9a9184]">这些信号会影响每日队列排序。</p>
        </div>
      </div>
      <Field label="目标城市">
        <TagInput
          values={prefs.target_locations || []}
          onChange={(v) => setArray("target_locations", v)}
          placeholder="北京、上海、深圳…（回车或逗号添加）"
        />
      </Field>
      <Field label="目标岗位方向">
        <TagInput
          values={prefs.target_roles || []}
          onChange={(v) => setArray("target_roles", v)}
          placeholder="算法、产品经理、数据分析…"
        />
      </Field>
      <Field label="命中关键词">
        <TagInput
          values={prefs.target_keywords || []}
          onChange={(v) => setArray("target_keywords", v)}
          placeholder="Python、机器学习、LLM…"
        />
      </Field>
      <Field label="排除关键词">
        <TagInput
          values={prefs.exclude_keywords || []}
          onChange={(v) => setArray("exclude_keywords", v)}
          placeholder="销售、客服…"
        />
      </Field>
      <Field label="关注公司（可加多个）">
        <TagInput
          values={prefs.target_companies || []}
          onChange={(v) => setArray("target_companies", v)}
          placeholder="Apple、百度、京东、字节…"
        />
      </Field>
      <Field label="每日展示数量">
        <input
          type="number"
          min={5}
          max={100}
          value={prefs.daily_limit}
          onChange={(e) => setPrefs({ ...prefs, daily_limit: Number(e.target.value) || 20 })}
          className="mt-1 field-soft"
        />
      </Field>

      {message && (
        <p className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm ${message.includes("失败") ? "border-[#e0b4ac] dark:border-[#7a392e]/[0.60] bg-[#f7e6e1] dark:bg-[#3a201a] text-[#9c4a3c] dark:text-[#e6a99f]" : "border-[#bcd2ed] dark:border-[#7fb2e8]/[0.30] bg-[#e8f1fc] dark:bg-[#7fb2e8]/[0.15] text-[#2f6299] dark:text-[#7fb2e8]"}`}>
          {!message.includes("失败") && <CheckCircle size={16} weight="fill" aria-hidden="true" />}
          {message}
        </p>
      )}

      <button type="submit" disabled={saveState === "saving"} className="btn-ink">
        {saveState === "saving" ? "保存中..." : "保存偏好"}
      </button>

      <SaveToast
        state={saveState}
        doneText="已保存偏好"
        errorText={saveErr || "保存失败"}
        onDismiss={() => setSaveState("idle")}
      />
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-sm font-medium text-[#5f594e] dark:text-[#b6ad9d]">{label}</label>
      {children}
    </div>
  );
}

function createEmptyPrefs(userId: string): UserPreferences {
  return {
    id: "",
    user_id: userId,
    target_locations: [],
    target_roles: [],
    target_keywords: [],
    exclude_keywords: [],
    target_companies: [],
    daily_limit: 20,
  };
}

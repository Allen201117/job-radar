"use client";

import { useState, useEffect } from "react";
import { createBrowserClient } from "@/lib/supabaseClient";
import type { UserPreferences } from "@/lib/types";
import TagInput from "./TagInput";

export default function PreferenceForm() {
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
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
    setSaving(true);
    setMessage("");
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user || !prefs) {
      setMessage("请先登录。");
      setSaving(false);
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
    setMessage(error ? "保存失败: " + error.message : "已保存");
    setSaving(false);
  }

  function setArray(field: keyof UserPreferences, arr: string[]) {
    if (!prefs) return;
    setPrefs({ ...prefs, [field]: arr } as UserPreferences);
  }

  if (!prefs) {
    return <p className="text-sm text-muted-foreground">加载中...</p>;
  }

  return (
    <form onSubmit={handleSave} className="space-y-4">
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
          className="mt-1 block w-full rounded-md border px-3 py-2 text-sm"
        />
      </Field>

      {message && (
        <p className={`text-sm ${message.includes("失败") ? "text-destructive" : "text-primary"}`}>
          {message}
        </p>
      )}

      <button
        type="submit"
        disabled={saving}
        className="rounded-md bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
      >
        {saving ? "保存中..." : "保存偏好"}
      </button>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-sm font-medium">{label}</label>
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

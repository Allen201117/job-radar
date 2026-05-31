"use client";

import { useState, useEffect } from "react";
import { createBrowserClient } from "@/lib/supabaseClient";
import type { UserPreferences } from "@/lib/types";

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

    window.addEventListener(
      "resume-preferences-updated",
      handleResumePreferencesUpdated,
    );
    return () => {
      window.removeEventListener(
        "resume-preferences-updated",
        handleResumePreferencesUpdated,
      );
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

    const { error } = await supabase
      .from("user_preferences")
      .upsert(
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
      setMessage("保存失败: " + error.message);
    } else {
      setMessage("已保存");
    }
    setSaving(false);
  }

  function updateField(field: keyof UserPreferences, value: string) {
    if (!prefs) return;
    const arr = value
      .split(/[,，、]/)
      .map((s) => s.trim())
      .filter(Boolean);
    setPrefs({
      ...prefs,
      [field]: arr,
    } as UserPreferences);
  }

  if (!prefs) {
    return <p className="text-sm text-muted-foreground">加载中...</p>;
  }

  const fieldClass = "mt-1 block w-full rounded-md border px-3 py-2 text-sm";

  function arrayValue(field: keyof UserPreferences): string {
    const val = prefs?.[field];
    if (Array.isArray(val)) return val.join(", ");
    return "";
  }

  return (
    <form onSubmit={handleSave} className="space-y-4">
      <div>
        <label className="text-sm font-medium">目标城市</label>
        <input
          value={arrayValue("target_locations")}
          onChange={(e) => updateField("target_locations", e.target.value)}
          placeholder="北京, 上海, 深圳"
          className={fieldClass}
        />
      </div>
      <div>
        <label className="text-sm font-medium">目标岗位方向</label>
        <input
          value={arrayValue("target_roles")}
          onChange={(e) => updateField("target_roles", e.target.value)}
          placeholder="算法, 产品经理, 数据分析"
          className={fieldClass}
        />
      </div>
      <div>
        <label className="text-sm font-medium">命中关键词</label>
        <input
          value={arrayValue("target_keywords")}
          onChange={(e) => updateField("target_keywords", e.target.value)}
          placeholder="Python, 机器学习, LLM"
          className={fieldClass}
        />
      </div>
      <div>
        <label className="text-sm font-medium">排除关键词</label>
        <input
          value={arrayValue("exclude_keywords")}
          onChange={(e) => updateField("exclude_keywords", e.target.value)}
          placeholder="销售, 客服"
          className={fieldClass}
        />
      </div>
      <div>
        <label className="text-sm font-medium">关注公司</label>
        <input
          value={arrayValue("target_companies")}
          onChange={(e) => updateField("target_companies", e.target.value)}
          placeholder="Apple, 百度, 京东"
          className={fieldClass}
        />
      </div>
      <div>
        <label className="text-sm font-medium">每日展示数量</label>
        <input
          type="number"
          min={5}
          max={100}
          value={prefs.daily_limit}
          onChange={(e) =>
            setPrefs({ ...prefs, daily_limit: Number(e.target.value) || 20 })
          }
          className={fieldClass}
        />
      </div>

      {message && (
        <p
          className={`text-sm ${message.includes("失败") ? "text-destructive" : "text-primary"}`}
        >
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

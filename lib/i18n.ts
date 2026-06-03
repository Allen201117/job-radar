"use client";

import { useEffect, useState } from "react";

export type Lang = "zh" | "en";

const DICT: Record<string, { zh: string; en: string }> = {
  today: { zh: "今日看板", en: "Today" },
  jobs: { zh: "岗位库", en: "Jobs" },
  path: { zh: "职业路径", en: "Career Path" },
  preferences: { zh: "求职偏好", en: "Preferences" },
  me: { zh: "个人主页", en: "Profile" },
  saved: { zh: "我的收藏", en: "Saved" },
  applied: { zh: "我的投递", en: "Applied" },
  sources: { zh: "源管理", en: "Sources" },
  insightsAdmin: { zh: "洞察管理", en: "Insights Admin" },
  logout: { zh: "退出", en: "Log out" },
};

export function getLang(): Lang {
  if (typeof window === "undefined") return "zh";
  return (localStorage.getItem("lang") as Lang) || "zh";
}

export function setLang(l: Lang) {
  if (typeof window !== "undefined") {
    localStorage.setItem("lang", l);
    window.dispatchEvent(new Event("lang-change"));
  }
}

export function t(key: string, lang: Lang): string {
  return DICT[key]?.[lang] ?? key;
}

export function useLang(): [Lang, (l: Lang) => void] {
  const [lang, setLangState] = useState<Lang>("zh");
  useEffect(() => {
    setLangState(getLang());
    const handler = () => setLangState(getLang());
    window.addEventListener("lang-change", handler);
    window.addEventListener("storage", handler);
    return () => {
      window.removeEventListener("lang-change", handler);
      window.removeEventListener("storage", handler);
    };
  }, []);
  return [lang, setLang];
}

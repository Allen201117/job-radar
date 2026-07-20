"use client";

import { useEffect, useState } from "react";

export type Lang = "zh" | "en";

const DICT: Record<string, { zh: string; en: string }> = {
  today: { zh: "今日机会", en: "Today" },
  jobs: { zh: "搜索岗位", en: "Jobs" },
  path: { zh: "职业路径", en: "Career Path" },
  campus: { zh: "校招专区", en: "Campus" },
  preferences: { zh: "关注与偏好", en: "Preferences" },
  me: { zh: "个人主页", en: "Profile" },
  saved: { zh: "值得投", en: "Saved" },
  applied: { zh: "已投递", en: "Applied" },
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

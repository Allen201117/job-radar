"use client";

import { useEffect, useState } from "react";

export type Lang = "zh" | "en";

// 导航词表 = 全站页面名的唯一权威（页头标题由 tests/loading-copy.test.js 钉着跟它走）。
//
// 2026-09-09 创始人拍板「和大厂对齐」，逐词照抄真产品的叫法，不再自造：
//   推荐      ← BOSS直聘岗位列表页的页面身份就是「推荐」；牛客列表排序 tab 也是「推荐/最新」
//   职位      ← BOSS / 智联 / 猎聘 / 牛客 一级导航都叫「职位」
//   校园招聘  ← BOSS「校园」· 猎聘「校园」· 智联「校招」· 实习僧「校招」· 牛客「校招职位」
//   投递记录  ← 猎聘移动端个人中心：我的简历 / 投递记录 / 谁看过我
//   收藏      ← 中文产品通用叫法（⚠️ 这条没拿到第一手页面，各家都在登录后）
//   个人中心  ← 同上；且「个人主页」在中文语境里通常指对外展示页，本页是设置 + 记录
// 洞察库 / 公告制招聘 / 源管理 / 洞察管理**刻意保留**：大厂没有对应模块，硬套等于编造对应关系。
//
// ⚠️ 这次把 2026 年早先「saved 全站统一叫值得投、不再出现收藏双轨」那条决定反过来了
// （原注释在 components/JobCard.tsx）。改名要连动作词一起改，别只改导航留个双轨。
const DICT: Record<string, { zh: string; en: string }> = {
  today: { zh: "推荐", en: "Recommended" },
  jobs: { zh: "职位", en: "Jobs" },
  campus: { zh: "校园招聘", en: "Campus" },
  insights: { zh: "洞察库", en: "Insights" },
  programs: { zh: "公告制招聘", en: "Announcements" },
  me: { zh: "个人中心", en: "Profile" },
  saved: { zh: "收藏", en: "Saved" },
  applied: { zh: "投递记录", en: "Applied" },
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

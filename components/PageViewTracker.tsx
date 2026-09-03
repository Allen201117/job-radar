"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { PAGE_VIEW_EVENT, normalizePagePath, track } from "@/lib/track";

// 页面浏览埋点：全站唯一一处，挂在根 layout。
//
// 为什么必须有它：留存（次日/7日/30日回访）只能靠「这个人哪几天来过」算，
// 而收藏/投递这些动作型埋点只覆盖有操作的人——只看了看就走的人在数据里等于不存在，
// 于是「72% 用户只来一天」这种结论根本算不出来。
//
// 三条不变量：
//  1) **不阻塞渲染**：track 内部 fire-and-forget，失败只 console.warn。
//  2) **同一路径不重复打**：Next 的 usePathname 在同一页面重渲染时值不变，
//     用 ref 比对上一次路径，避免 React 严格模式双调用与父级重渲染打出重复行。
//  3) **未登录不会入库**：/api/events 对未登录直接 204 丢弃（RLS 也只允许写自己），
//     所以这里不必自己判断登录态——判断了反而要多一次跨洋鉴权往返。
export default function PageViewTracker() {
  const pathname = usePathname();
  // 上一次真正打点的路径。首帧为 null，保证首次进入一定会打。
  const lastPathRef = useRef<string | null>(null);

  useEffect(() => {
    const path = normalizePagePath(pathname);
    if (lastPathRef.current === path) return;
    const from = lastPathRef.current;
    lastPathRef.current = path;
    // from = 站内上一页，用来还原「用户是按什么顺序走的」；首次进入为 null。
    track(PAGE_VIEW_EVENT, { path, from });
  }, [pathname]);

  return null;
}

"use client";

import { useEffect, useState } from "react";
import { AnimateNumber } from "@/components/ui/animated-blur-number";

// 数字翻动统计：入场时从 0 翻到目标值，之后每次 value 变化（实时数据更新 / 路由刷新）再翻一次。
// 包一层是因为 AnimateNumber 只在「值发生变化」时才有翻动动效——这里在挂载后下一帧把 0 推到
// 真实值，制造入场翻动；服务端组件（如 MetricTile）也能通过它获得翻动效果（AnimateNumber 是
// 客户端组件，可作为客户端孤岛被服务端组件渲染）。
export function AnimatedStat({
  value,
  className,
  duration = 600,
  blur = 12,
}: {
  value: number;
  className?: string;
  duration?: number;
  blur?: number;
}) {
  const [shown, setShown] = useState(0);

  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(value));
    return () => cancelAnimationFrame(id);
  }, [value]);

  return <AnimateNumber value={shown} duration={duration} blur={blur} className={className} />;
}

export default AnimatedStat;

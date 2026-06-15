import type { Metadata } from "next";
import "./globals.css";
import TargetCursor from "@/components/TargetCursor";
import MagicBentoFX from "@/components/MagicBentoFX";

export const metadata: Metadata = {
  title: "Job Radar | 官方岗位雷达",
  description: "发现真实、最新、匹配的官方岗位",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-background antialiased">
        {children}
        {/* 全站自定义鼠标指针：旋转准星 + 锁定 a/button/.cursor-target（仅桌面生效） */}
        <TargetCursor
          targetSelector="a, button, .cursor-target"
          spinDuration={2}
          hoverDuration={0.3}
          hideDefaultCursor
          parallaxOn
        />
        {/* MagicBento 悬浮光效（雷达绿）：给 .bento-glow 卡片加 指针描边发光/粒子/磁吸/点击波纹 */}
        <MagicBentoFX
          glowColor="0, 230, 118"
          spotlightRadius={300}
          particleCount={12}
          enableStars
          enableSpotlight
          enableBorderGlow
          enableMagnetism
          clickEffect
          enableTilt={false}
        />
      </body>
    </html>
  );
}

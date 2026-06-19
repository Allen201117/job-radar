import type { Metadata } from "next";
import "./globals.css";
import MagicBentoFX from "@/components/MagicBentoFX";

export const metadata: Metadata = {
  title: "职达 JobRadar | 官方岗位雷达",
  description: "只看企业官网还在招的真岗位，再帮你判断值不值得投。",
};

// no-flash：首帧绘制前按 localStorage 还原主题（默认浅色，仅用户手动切过深色才加 .dark）
const THEME_SCRIPT = `(function(){try{if(localStorage.getItem('jr-theme')==='dark')document.documentElement.classList.add('dark');}catch(e){}})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="min-h-screen bg-background antialiased">
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
        {children}
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

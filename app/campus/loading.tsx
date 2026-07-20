import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { PanelSkeleton } from "@/components/Skeletons";
import { GraduationCap } from "@phosphor-icons/react/ssr";

// 冷启动 / tab 切换即时骨架：校招专区正文（服务端聚合必投清单校招窗口）加载前占位。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero
          eyebrow="校招专区"
          title="按你的行业锁定必投目标公司的校招窗口"
          description="已接入官方校招源并持续验证的岗位；据公开信息追踪聚合必投清单公司的校招/实习岗与窗口状态，非官方、仅供参考。"
          icon={GraduationCap}
        />
        <div className="mt-8 grid gap-4">
          <PanelSkeleton />
          <PanelSkeleton />
          <PanelSkeleton />
        </div>
      </ProductPage>
    </div>
  );
}

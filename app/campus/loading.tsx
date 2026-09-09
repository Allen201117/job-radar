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
          title="校园招聘"
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

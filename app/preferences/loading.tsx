import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { PanelSkeleton } from "@/components/Skeletons";
import { SlidersHorizontal } from "@phosphor-icons/react/ssr";

// 冷启动 / tab 切换即时骨架：偏好表单 + 简历画像面板占位。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero
          eyebrow="偏好与画像"
          title="让匹配排序贴近你的目标"
          description="设置目标城市、岗位方向和关键词。简历画像只用于岗位匹配，不做自动投递或简历优化。"
          icon={SlidersHorizontal}
        />
        <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(360px,420px)]">
          <PanelSkeleton />
          <PanelSkeleton />
        </div>
      </ProductPage>
    </div>
  );
}

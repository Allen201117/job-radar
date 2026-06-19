import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { MetricTilesSkeleton, PanelSkeleton } from "@/components/Skeletons";
import { UserCircle } from "@phosphor-icons/react/ssr";

// 冷启动 / tab 切换即时骨架：计数卡 + 资料 / 简历画像面板占位。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="个人主页"
          title="你的求职雷达状态"
          description="查看收藏、投递与简历画像状态。"
          icon={UserCircle}
        >
          <MetricTilesSkeleton count={3} gridClassName="grid gap-3 sm:grid-cols-3" />
        </ProductHero>
        <div className="mt-6 grid gap-4">
          <PanelSkeleton />
          <PanelSkeleton />
        </div>
      </ProductPage>
    </div>
  );
}

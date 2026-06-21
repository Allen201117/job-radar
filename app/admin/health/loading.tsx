import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { MetricTilesSkeleton, PanelSkeleton } from "@/components/Skeletons";
import { Pulse } from "@phosphor-icons/react/ssr";

export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-6xl">
        <ProductHero
          eyebrow="今日健康"
          title="今天运营得怎么样？"
          description="正在汇总今日运行、岗位库质量与用户业务数据。"
          icon={Pulse}
        >
          <MetricTilesSkeleton count={4} gridClassName="grid grid-cols-2 gap-3 lg:grid-cols-4" />
        </ProductHero>
        <div className="mt-6 grid gap-6">
          <PanelSkeleton className="min-h-96" />
          <PanelSkeleton className="min-h-96" />
          <PanelSkeleton />
          <PanelSkeleton />
        </div>
      </ProductPage>
    </div>
  );
}

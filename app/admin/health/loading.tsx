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
          eyebrow="系统健康"
          title="今天的数据健康吗？"
          description="正在聚合岗位库、抓取、刷新发现与职业洞察。"
          icon={Pulse}
        >
          <MetricTilesSkeleton count={4} gridClassName="grid grid-cols-2 gap-3 lg:grid-cols-4" />
        </ProductHero>
        <div className="mt-6 grid gap-6">
          <PanelSkeleton />
          <PanelSkeleton className="min-h-80" />
          <PanelSkeleton />
          <PanelSkeleton />
          <PanelSkeleton />
        </div>
      </ProductPage>
    </div>
  );
}

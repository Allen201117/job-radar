import AdminNav from "@/components/AdminNav";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { MetricTilesSkeleton, PanelSkeleton } from "@/components/Skeletons";
import { ShieldCheck } from "@phosphor-icons/react/ssr";

export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <AdminNav />
      <ProductPage maxWidth="max-w-6xl">
        <ProductHero
          eyebrow="运营健康"
          title="管理员看板"
          description="按模块汇总今日真实运行与供给情况。"
          icon={ShieldCheck}
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

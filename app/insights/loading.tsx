import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { PanelSkeleton } from "@/components/Skeletons";
import { Compass } from "@phosphor-icons/react/ssr";

// 冷启动 / tab 切换即时骨架：force-dynamic 路由没有 loading 边界会「点 tab 冻屏」。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero
          eyebrow="洞察库"
          title="岗位描述里不会写的事"
          icon={Compass}
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

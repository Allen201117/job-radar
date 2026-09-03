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
          title="年终奖、加班、面试、晋升——别人怎么说的"
          description="与岗位库平级的第二个库，只放你在岗位描述里看不到的那部分。每条都标清是「官方事实」还是「公开说法」，并给出来源——是转述，不是我们的结论。"
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

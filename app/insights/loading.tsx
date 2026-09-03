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
          title="按公司与业务线看在招结构、门槛与公开说法"
          description="与岗位库平级的第二个库。每条内容都标清它是「事实」「数据」还是「说法」，并写出样本量——不够就不显示，不替你下结论。"
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

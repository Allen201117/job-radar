import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { JobListSkeleton, MetricTilesSkeleton } from "@/components/Skeletons";
import { Broadcast } from "@phosphor-icons/react/ssr";
import { TODAY_HERO } from "./hero";

// 冷启动 / tab 切换即时骨架：标题等静态内容照常渲染，仅数据区占位，待 RSC 流入替换。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero
          eyebrow={TODAY_HERO.eyebrow}
          title={TODAY_HERO.title}
          icon={Broadcast}
        >
          <MetricTilesSkeleton count={3} />
        </ProductHero>
        <section className="mt-8">
          <JobListSkeleton count={6} />
        </section>
      </ProductPage>
    </div>
  );
}

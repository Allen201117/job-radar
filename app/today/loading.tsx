import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { JobListSkeleton, MetricTilesSkeleton } from "@/components/Skeletons";
import { Broadcast } from "@phosphor-icons/react/ssr";

// 冷启动 / tab 切换即时骨架：标题等静态内容照常渲染，仅数据区占位，待 RSC 流入替换。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero
          eyebrow="今日机会"
          title="今天值得处理的官方岗位"
          description="系统已按你的目标、简历和岗位新鲜度完成筛选。先处理最相关的，再决定是否扩大搜索。"
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

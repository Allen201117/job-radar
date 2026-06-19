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
          eyebrow="今日看板"
          title="官方岗位的每日优先队列"
          description="根据你的偏好和简历画像排序，隐藏已忽略和已投递岗位，把今天最值得看的官方机会放在前面。"
          icon={Broadcast}
        >
          <MetricTilesSkeleton count={5} />
        </ProductHero>
        <section className="mt-8">
          <JobListSkeleton count={6} />
        </section>
      </ProductPage>
    </div>
  );
}

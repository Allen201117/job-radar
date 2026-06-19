import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { HeroStatSkeleton, JobListSkeleton } from "@/components/Skeletons";
import { Database } from "@phosphor-icons/react/ssr";

// 冷启动 / tab 切换即时骨架：库总数卡 + 筛选条 + 列表占位，待服务端筛选首屏流入。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero
          eyebrow="岗位库"
          title="官方岗位检索与发现"
          description="从本地岗位库开始，按需刷新已知官网源，必要时再发现新的官方招聘入口。"
          icon={Database}
          action={<HeroStatSkeleton />}
        />
        <div className="mt-8 space-y-4">
          <div className="surface h-14 w-full animate-pulse" aria-hidden="true" />
          <JobListSkeleton count={6} />
        </div>
      </ProductPage>
    </div>
  );
}

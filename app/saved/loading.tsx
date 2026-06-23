import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { JobListSkeleton } from "@/components/Skeletons";
import { BookmarkSimple } from "@phosphor-icons/react/ssr";

// 冷启动 / tab 切换即时骨架：收藏列表占位。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero eyebrow="值得投" title="待进一步比较的岗位" icon={BookmarkSimple} />
        <div className="mt-8">
          <JobListSkeleton count={5} />
        </div>
      </ProductPage>
    </div>
  );
}

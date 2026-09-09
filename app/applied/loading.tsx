import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { JobListSkeleton } from "@/components/Skeletons";
import { CheckCircle } from "@phosphor-icons/react/ssr";

// 冷启动 / tab 切换即时骨架：投递记录列表占位。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero title="已投递" icon={CheckCircle} />
        <div className="mt-6">
          <JobListSkeleton count={5} />
        </div>
      </ProductPage>
    </div>
  );
}

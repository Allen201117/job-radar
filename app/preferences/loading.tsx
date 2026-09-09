import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { PanelSkeleton } from "@/components/Skeletons";
import { UserCircle } from "@phosphor-icons/react/ssr";

// 冷启动 / tab 切换即时骨架：偏好表单 + 简历画像面板占位。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero title="个人主页" icon={UserCircle} />
        <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(360px,420px)]">
          <PanelSkeleton />
          <PanelSkeleton />
        </div>
      </ProductPage>
    </div>
  );
}

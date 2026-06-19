import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { PanelSkeleton } from "@/components/Skeletons";
import { Compass } from "@phosphor-icons/react/ssr";

// 冷启动 / tab 切换即时骨架：职业路径正文（客户端确定性引擎）加载前占位。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero
          eyebrow="职业路径"
          title="按你的目标，给出投递优先级与温馨提示"
          titleClassName="lg:whitespace-nowrap lg:text-[2.2rem] xl:text-[2.5rem]"
          description="结合你的目标公司、求职阶段与公司洞察（时机 / 性价比 / 路径 / 文化）做确定性匹配。据公开信息聚合，仅供参考，非官方、不替代你的判断。"
          icon={Compass}
        />
        <div className="mt-8 grid gap-4">
          <PanelSkeleton />
          <PanelSkeleton />
        </div>
      </ProductPage>
    </div>
  );
}

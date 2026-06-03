import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { Compass } from "@phosphor-icons/react/ssr";
import CareerPathClient from "./path-client";

export default function PathPage() {
  return (
    <div className="min-h-screen bg-[#08090c]">
      <Navbar />
      <ProductPage>
        <ProductHero
          eyebrow="职业路径"
          title="按你的目标，给出投递优先级与温馨提示"
          description="结合你的目标公司、求职阶段与公司洞察（时机 / 性价比 / 路径 / 文化）做确定性匹配。据公开信息聚合，仅供参考，非官方、不替代你的判断。"
          icon={Compass}
        />
        <CareerPathClient />
      </ProductPage>
    </div>
  );
}

import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { Megaphone } from "@phosphor-icons/react/ssr";

// force-dynamic 路由必须有 loading 边界，否则点 tab 会冻屏 + prefetch 失效
// （见 CLAUDE.md「冷启动 / tab 切换不卡」）。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-4xl">
        <ProductHero eyebrow="项目制投递" title="有些公司不按岗位挂，得从这里投" icon={Megaphone} />
        <div className="mt-10 space-y-3" aria-hidden>
          {[0, 1, 2].map((i) => (
            <div key={i} className="surface h-28 animate-pulse rounded-xl" />
          ))}
        </div>
      </ProductPage>
    </div>
  );
}

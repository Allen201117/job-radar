import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { MetricTilesSkeleton } from "@/components/Skeletons";
import { Megaphone } from "@phosphor-icons/react/ssr";

// force-dynamic 路由必须有 loading 边界，否则点 tab 会冻屏 + prefetch 失效
// （见 CLAUDE.md「冷启动 / tab 切换不卡」）。
// 骨架的形状要和真页一致（分区头 + 两列卡片网格），否则加载完会「跳一下重排」。
export default function Loading() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          title="公告制招聘"
          icon={Megaphone}
          align="center"
          action={<MetricTilesSkeleton count={1} gridClassName="grid w-full sm:w-[200px]" />}
        />
        <div className="mt-10 space-y-5" aria-hidden>
          <div className="flex items-start gap-3">
            <div className="surface-soft size-9 shrink-0 animate-pulse rounded-xl" />
            <div className="min-w-0 flex-1 space-y-2 pt-1">
              <div className="h-4 w-32 animate-pulse rounded-full bg-black/[0.07] dark:bg-white/[0.08]" />
              <div className="h-3 w-full max-w-md animate-pulse rounded-full bg-black/[0.07] dark:bg-white/[0.08]" />
            </div>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="surface h-52 animate-pulse" />
            ))}
          </div>
        </div>
      </ProductPage>
    </div>
  );
}

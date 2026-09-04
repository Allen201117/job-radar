import AdminNav from "@/components/AdminNav";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import DesignSystemClient from "@/app/design/design-client";
import { isAdmin } from "@/lib/auth";
import { redirect } from "next/navigation";
import { Palette } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

/**
 * 组件库活文档。
 *
 * 为什么是产品内的一个路由，而不是 Storybook：
 * 它跑在真实产品里、用的是同一份 globals.css 和同一套 Tailwind 配置，所以**不可能出现
 * 「文档站好看、线上不一样」**。Storybook 要单独跑一个进程、单独配一份构建，在 Next 15
 * App Router 上配置与维护成本都不小，而这个产品只有几个人在维护，不值。
 * （GitHub Primer 用 Storybook，是因为要支撑 30+ 人和多主题多色盲模式的对齐需求。）
 *
 * 门禁沿用 /sources：只有 profiles.role='admin' 能看。它不含任何用户数据，
 * 挡起来纯粹是因为这是内部工具，不该出现在产品导航里。
 */
export default async function DesignSystemPage() {
  if (!(await isAdmin())) {
    redirect("/");
  }

  return (
    <div className="min-h-screen bg-editorial">
      <AdminNav />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="设计组件库"
          title="全站在用的组件长什么样、有哪些变体、该在什么时候用哪个"
          description="这一页里的每个组件都是产品里真实运行的那一个，用的是同一份样式。改了组件库，这里立刻跟着变——所以它不会说谎。"
          icon={Palette}
        />
        <DesignSystemClient />
      </ProductPage>
    </div>
  );
}

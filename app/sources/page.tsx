import AdminNav from "@/components/AdminNav";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import SourceManager from "@/components/SourceManager";
import { isAdmin } from "@/lib/auth";
import { redirect } from "next/navigation";
import { Database } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

export default async function SourcesPage() {
  if (!(await isAdmin())) {
    redirect("/");
  }

  return (
    <div className="min-h-screen bg-editorial">
      <AdminNav />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="数据源"
          title="每家公司的官方招聘页接得怎么样、最近一次抓取的结果"
          description="在这里接入新公司的官方招聘页、看哪些已经启用，以及最近一次抓取抓到了什么。全程网页操作，不用写代码。"
          icon={Database}
        />
        <div className="mt-6">
          <SourceManager />
        </div>
      </ProductPage>
    </div>
  );
}

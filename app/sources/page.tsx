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
          title="接了哪些官网，抓得怎么样"
          icon={Database}
        />
        <div className="mt-6">
          <SourceManager />
        </div>
      </ProductPage>
    </div>
  );
}

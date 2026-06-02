import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import SourceTable from "@/components/SourceTable";
import { isAdmin } from "@/lib/auth";
import { redirect } from "next/navigation";
import { Database } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

export default async function SourcesPage() {
  if (!(await isAdmin())) {
    redirect("/");
  }

  return (
    <div className="min-h-screen bg-[#08090c]">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="数据源"
          title="企业招聘源的状态与抓取日志"
          description="查看官方招聘源是否启用，以及最近一次抓取结果。"
          icon={Database}
        />
        <div className="mt-6">
          <SourceTable />
        </div>
      </ProductPage>
    </div>
  );
}

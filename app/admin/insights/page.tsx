import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import InsightsAdminClient from "@/components/InsightsAdminClient";
import { isAdmin } from "@/lib/auth";
import { redirect } from "next/navigation";
import { Sparkle } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

export default async function InsightsAdminPage() {
  if (!(await isAdmin())) {
    redirect("/");
  }

  return (
    <div className="min-h-screen bg-[#08090c]">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="洞察管理"
          title="录入、编辑、下架职业洞察，处理申诉"
          description="新增/编辑条目时必过分级、去标识、归因、时效校验门；不过门会提示卡在哪。全程网页操作，无需写 SQL。"
          icon={Sparkle}
        />
        <InsightsAdminClient />
      </ProductPage>
    </div>
  );
}

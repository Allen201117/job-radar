import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import PreferenceForm from "@/components/PreferenceForm";
import ResumeProfilePanel from "@/components/ResumeProfilePanel";
import { SlidersHorizontal } from "@phosphor-icons/react/ssr";

export default function PreferencesPage() {
  return (
    <div className="min-h-screen bg-[#08090c]">
      <Navbar />
      <ProductPage>
        <ProductHero
          eyebrow="偏好与画像"
          title="让匹配排序贴近你的目标"
          description="设置目标城市、岗位方向和关键词。简历画像只用于岗位匹配，不做自动投递或简历优化。"
          icon={SlidersHorizontal}
        />
        <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(360px,420px)]">
          <PreferenceForm />
          <ResumeProfilePanel />
        </div>
      </ProductPage>
    </div>
  );
}

import Link from "next/link";
import Navbar from "@/components/Navbar";
import { MetricTile, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import ResumeProfilePanel from "@/components/ResumeProfilePanel";
import ProfileEditor from "@/components/ProfileEditor";
import PreferenceForm from "@/components/PreferenceForm";
import { BookmarkSimple, CheckCircle, EyeSlash, UserCircle } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

export default async function MePage() {
  const supabase = await createServerSupabase();
  const user = await getRequestUser();

  let savedCount = 0;
  let appliedCount = 0;
  let ignoredCount = 0;
  if (user) {
    const counts = await Promise.all(
      ["saved", "applied", "ignored"].map((action) =>
        supabase
          .from("job_actions")
          .select("id", { count: "exact", head: true })
          .eq("user_id", user.id)
          .eq("action", action),
      ),
    );
    savedCount = counts[0].count || 0;
    appliedCount = counts[1].count || 0;
    ignoredCount = counts[2].count || 0;
  }

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="个人主页"
          title="你的职达状态"
          description={user?.email || "账号、匹配偏好与简历画像都在这里。"}
          icon={UserCircle}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <Link href="/saved" className="block transition duration-200 hover:-translate-y-0.5">
              <MetricTile icon={BookmarkSimple} label="值得投 →" value={savedCount} tone="white" />
            </Link>
            <Link href="/applied" className="block transition duration-200 hover:-translate-y-0.5">
              <MetricTile icon={CheckCircle} label="我的投递 →" value={appliedCount} tone="orange" />
            </Link>
            <MetricTile icon={EyeSlash} label="已忽略" value={ignoredCount} tone="muted" />
          </div>
        </ProductHero>

        {/* 2026-09-03 合并「关注与偏好」进本页：两处原本各挂一份 ResumeProfilePanel，功能重复。
            /preferences 现重定向到这里，导航入口也统一成「个人主页」。
            左栏放"我要什么"（账号 + 匹配偏好），右栏放"我是谁"（简历画像），简历面板只留一份。 */}
        <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(360px,420px)] lg:items-start">
          <div className="grid gap-4">
            <ProfileEditor email={user?.email} />
            <PreferenceForm />
          </div>
          <ResumeProfilePanel />
        </div>
      </ProductPage>
    </div>
  );
}

import Link from "next/link";
import Navbar from "@/components/Navbar";
import { MetricTile, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase } from "@/lib/auth";
import ResumeProfilePanel from "@/components/ResumeProfilePanel";
import { BookmarkSimple, CheckCircle, EyeSlash, UserCircle } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

export default async function MePage() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

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
    <div className="min-h-screen bg-[#08090c]">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="个人主页"
          title="你的求职雷达状态"
          description={user?.email || "查看收藏、投递与简历画像状态。"}
          icon={UserCircle}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <Link href="/saved" className="block transition duration-200 hover:-translate-y-0.5">
              <MetricTile icon={BookmarkSimple} label="我的收藏 →" value={savedCount} tone="white" />
            </Link>
            <Link href="/applied" className="block transition duration-200 hover:-translate-y-0.5">
              <MetricTile icon={CheckCircle} label="我的投递 →" value={appliedCount} tone="orange" />
            </Link>
            <MetricTile icon={EyeSlash} label="已忽略" value={ignoredCount} tone="muted" />
          </div>
        </ProductHero>

        <section className="mt-6 rounded-[1.35rem] border border-white/10 bg-white/[0.045] p-5 text-white">
          <h2 className="mb-1 text-lg font-semibold">个人画像</h2>
          <p className="mb-3 text-xs text-white/46">
            粘贴或上传简历（支持 PDF / Word / 图片 / txt / md），系统按规则解析画像，确认后同步到求职偏好用于匹配排序。
          </p>
          <ResumeProfilePanel />
        </section>
      </ProductPage>
    </div>
  );
}

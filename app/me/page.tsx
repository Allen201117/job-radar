import Link from "next/link";
import Navbar from "@/components/Navbar";
import { MetricTile, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import ResumeProfilePanel from "@/components/ResumeProfilePanel";
import ProfileEditor from "@/components/ProfileEditor";
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
          description={user?.email || "查看收藏、投递与简历画像状态。"}
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

        <div className="mt-6 grid gap-4">
          <ProfileEditor email={user?.email} />
          <ResumeProfilePanel />
        </div>
      </ProductPage>
    </div>
  );
}

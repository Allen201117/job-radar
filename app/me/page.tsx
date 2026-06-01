import Link from "next/link";
import Navbar from "@/components/Navbar";
import { createServerSupabase } from "@/lib/auth";
import ResumeProfilePanel from "@/components/ResumeProfilePanel";

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
    <div>
      <Navbar />
      <main className="mx-auto max-w-4xl space-y-6 px-4 py-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">个人主页</h1>
          {user?.email && (
            <p className="mt-1 text-sm text-muted-foreground">{user.email}</p>
          )}
        </div>

        <div className="grid grid-cols-3 gap-4">
          <Link
            href="/saved"
            className="rounded-lg border bg-card p-4 transition-shadow hover:shadow-md"
          >
            <div className="text-2xl font-bold">{savedCount}</div>
            <div className="mt-1 text-sm text-muted-foreground">我的收藏 →</div>
          </Link>
          <Link
            href="/applied"
            className="rounded-lg border bg-card p-4 transition-shadow hover:shadow-md"
          >
            <div className="text-2xl font-bold">{appliedCount}</div>
            <div className="mt-1 text-sm text-muted-foreground">我的投递 →</div>
          </Link>
          <div className="rounded-lg border bg-card p-4">
            <div className="text-2xl font-bold">{ignoredCount}</div>
            <div className="mt-1 text-sm text-muted-foreground">已忽略</div>
          </div>
        </div>

        <section className="rounded-lg border bg-card p-4">
          <h2 className="mb-1 text-lg font-semibold">个人画像</h2>
          <p className="mb-3 text-xs text-muted-foreground">
            粘贴或上传简历（支持 PDF / Word / 图片 / txt / md），系统按规则解析画像，确认后同步到求职偏好用于匹配排序。
          </p>
          <ResumeProfilePanel />
        </section>
      </main>
    </div>
  );
}

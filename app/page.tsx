import Navbar from "@/components/Navbar";
import { createServerSupabase } from "@/lib/auth";
import { sortAndFilterJobs } from "@/lib/scoring";
import type { Job, UserPreferences, JobAction, ScoredJob } from "@/lib/types";
import TodayClient from "./today-client";

export const dynamic = "force-dynamic";

export default async function TodayPage() {
  const supabase = await createServerSupabase();
  const { data: { user } } = await supabase.auth.getUser();

  let preferences: UserPreferences | null = null;
  let actions: JobAction[] = [];

  // 加载 jobs（不需要登录）
  const { data: jobs } = await supabase
    .from("jobs")
    .select("*")
    .eq("status", "active")
    .order("first_seen_at", { ascending: false })
    .limit(200);

  // 用户登录后才加载偏好和操作
  if (user) {
    const { data: prefs } = await supabase
      .from("user_preferences")
      .select("*")
      .eq("user_id", user.id)
      .single();
    preferences = prefs as UserPreferences | null;

    const { data: acts } = await supabase
      .from("job_actions")
      .select("*")
      .eq("user_id", user.id);
    actions = (acts as JobAction[]) || [];
  }

  const scored = sortAndFilterJobs(
    (jobs as Job[]) || [],
    preferences,
    actions,
    { showIgnored: false, showApplied: false, limit: preferences?.daily_limit || 20 },
  );

  const allScored = sortAndFilterJobs(
    (jobs as Job[]) || [],
    preferences,
    actions,
    { showIgnored: true, showApplied: true },
  );

  const newCount = (jobs as Job[])?.filter((j) => {
    if (!j.first_seen_at) return false;
    return (Date.now() - new Date(j.first_seen_at).getTime()) / 86400000 <= 3;
  }).length || 0;

  const highMatchCount = scored.filter((j) => j.match_score >= 40).length;
  const savedCount = allScored.filter((j) => j.user_action === "saved").length;
  const appliedCount = allScored.filter((j) => j.user_action === "applied").length;
  const ignoredCount = allScored.filter((j) => j.user_action === "ignored").length;

  return (
    <div>
      <Navbar />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <h1 className="text-2xl font-semibold tracking-tight">今日看板</h1>

        <div className="mt-4 grid grid-cols-5 gap-3">
          <StatCard label="今日新增" value={newCount} />
          <StatCard label="高匹配" value={highMatchCount} />
          <StatCard label="已收藏" value={savedCount} />
          <StatCard label="已投递" value={appliedCount} />
          <StatCard label="已忽略" value={ignoredCount} />
        </div>

        <div className="mt-6 space-y-3">
          {scored.length === 0 ? (
            <p className="py-12 text-center text-muted-foreground">
              暂无岗位数据。等待 crawler 抓取或检查 preferences 设置。
            </p>
          ) : (
            <TodayClient initialJobs={scored as ScoredJob[]} />
          )}
        </div>
      </main>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-card p-3 text-center">
      <div className="text-2xl font-bold">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

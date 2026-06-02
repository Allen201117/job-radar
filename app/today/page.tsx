import Navbar from "@/components/Navbar";
import { EmptyPanel, MetricTile, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase } from "@/lib/auth";
import { sortAndFilterJobs } from "@/lib/scoring";
import type { Job, UserPreferences, JobAction, ScoredJob } from "@/lib/types";
import TodayClient from "../today-client";
import {
  BookmarkSimple,
  Broadcast,
  CheckCircle,
  Crosshair,
  EyeSlash,
  Sparkle,
} from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

export default async function TodayPage() {
  const supabase = await createServerSupabase();
  const { data: { user } } = await supabase.auth.getUser();

  let preferences: UserPreferences | null = null;
  let actions: JobAction[] = [];

  const { data: jobs } = await supabase
    .from("jobs")
    .select("*")
    .eq("status", "active")
    .order("first_seen_at", { ascending: false })
    .limit(200);

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
    <div className="min-h-screen bg-[#08090c]">
      <Navbar />
      <ProductPage>
        <ProductHero
          eyebrow="今日看板"
          title="官方岗位的每日优先队列 ✨"
          description="根据你的偏好和简历画像排序，隐藏已忽略和已投递岗位，把今天最值得看的官方机会放在前面。"
          icon={Broadcast}
          action={
            <div className="rounded-2xl border border-white/10 bg-white/10 px-4 py-3 text-sm text-white/72 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
              显示上限 {preferences?.daily_limit || 20} 个岗位
            </div>
          }
        >
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <MetricTile icon={Sparkle} label="今日新增" value={newCount} tone="sky" />
            <MetricTile icon={Crosshair} label="高匹配" value={highMatchCount} tone="lime" />
            <MetricTile icon={BookmarkSimple} label="已收藏" value={savedCount} tone="white" />
            <MetricTile icon={CheckCircle} label="已投递" value={appliedCount} tone="orange" />
            <MetricTile icon={EyeSlash} label="已忽略" value={ignoredCount} tone="muted" />
          </div>
        </ProductHero>

        <section className="mt-8">
          {scored.length === 0 ? (
            <EmptyPanel
              title="暂无可展示岗位"
              description="等待 crawler 抓取新岗位，或检查偏好设置是否过窄。你也可以到岗位库刷新已知官方源。"
            />
          ) : (
            <div className="space-y-3">
              <TodayClient initialJobs={scored as ScoredJob[]} />
            </div>
          )}
        </section>
      </ProductPage>
    </div>
  );
}

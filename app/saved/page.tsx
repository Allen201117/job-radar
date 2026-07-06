import Navbar from "@/components/Navbar";
import { CountBadge, EmptyPanel, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import { jobsStoreEnabled, jobsByIds } from "@/lib/jobs-store/read";
import { scoreJob } from "@/lib/scoring";
import type { Job, JobSnapshot, ScoredJob, UserPreferences } from "@/lib/types";
import SavedClient, { type DeletedSaved } from "./saved-client";
import { BookmarkSimple, Briefcase } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

export default async function SavedPage() {
  const supabase = await createServerSupabase();
  const user = await getRequestUser();

  if (!user) {
    return (
      <div className="min-h-screen bg-editorial">
        <Navbar />
        <ProductPage maxWidth="max-w-5xl">
          <ProductHero eyebrow="值得投" title="待进一步比较的岗位" icon={BookmarkSimple} />
          <div className="mt-6">
            <EmptyPanel title="加载中，请稍候" description="正在读取你的「值得投」岗位。" />
          </div>
        </ProductPage>
      </div>
    );
  }

  const [actionsRes, prefsRes] = await Promise.all([
    supabase
      .from("job_actions")
      .select("job_id, created_at, job_snapshot")
      .eq("user_id", user.id)
      .eq("action", "saved")
      .order("created_at", { ascending: false }),
    supabase.from("user_preferences").select("*").eq("user_id", user.id).maybeSingle(),
  ]);
  const actions = actionsRes.data;
  const preferences = prefsRes.data as UserPreferences | null;

  if (!actions || actions.length === 0) {
    return (
      <div className="min-h-screen bg-editorial">
        <Navbar />
        <ProductPage maxWidth="max-w-5xl">
          <ProductHero eyebrow="值得投" title="待进一步比较的岗位" icon={BookmarkSimple} />
          <div className="mt-6">
            <EmptyPanel title="还没有「值得投」的岗位" description="在今日机会或搜索岗位里点「值得投」后，岗位会出现在这里。" />
          </div>
        </ProductPage>
      </div>
    );
  }

  // 先从权威 jobs 库按 id 取仍存在的岗位（含已下线但未清理的行）；已被物理清理的用 job_snapshot 兜底，不丢历史。
  const jobIds = actions.map((a: { job_id: string }) => a.job_id);
  const liveJobs = jobsStoreEnabled()
    ? await jobsByIds(jobIds, false)
    : (await supabase.from("jobs").select("*").in("id", jobIds)).data ?? [];
  const liveMap = new Map((liveJobs || []).map((j: any) => [j.id, j as Job]));

  const live: ScoredJob[] = [];
  const deleted: DeletedSaved[] = [];
  for (const a of actions as { job_id: string; created_at: string; job_snapshot: JobSnapshot | null }[]) {
    const row = liveMap.get(a.job_id);
    if (row) {
      const result = scoreJob(row, preferences, []);
      live.push({
        ...row,
        match_score: result.score,
        matched_keywords: result.matched_keywords,
        match_reasons: result.match_reasons,
        hidden_reason: result.hidden_reason,
        user_action: "saved",
      });
    } else {
      const snap = a.job_snapshot || {};
      deleted.push({
        jobId: a.job_id,
        company: snap.company || "公司信息缺失",
        title: snap.title || "原岗位已下线",
        location: snap.location || null,
        createdAt: a.created_at,
      });
    }
  }

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="值得投"
          title="待进一步比较的岗位"
          icon={BookmarkSimple}
          action={
            <CountBadge>
              <Briefcase size={16} weight="fill" aria-hidden="true" />
              <span className="tabular-nums">{live.length + deleted.length} 个</span>
            </CountBadge>
          }
        />
        <div className="mt-8">
          <SavedClient initialJobs={live} deletedSaved={deleted} hasPreferences={Boolean(preferences)} />
        </div>
      </ProductPage>
    </div>
  );
}

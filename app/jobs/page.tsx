import Navbar from "@/components/Navbar";
import { CountBadge, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase } from "@/lib/auth";
import { sortAndFilterJobs } from "@/lib/scoring";
import type { Job, UserPreferences, JobAction, ScoredJob } from "@/lib/types";
import JobsClient from "./jobs-client";
import { Briefcase, Database } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

// 从用户已保存偏好（简历画像 + 偏好表）算筛选器初值：城市/类型/关键词。
function buildInitialFilters(prefs: any, cp: any): { city: string; jobType: string; keyword: string } {
  const STAGES = ["实习", "校招", "社招"];
  const first = (...arrs: any[]): string => {
    for (const a of arrs) {
      const v = (Array.isArray(a) ? a : []).map((s: any) => String(s || "").trim()).find(Boolean);
      if (v) return v;
    }
    return "";
  };
  const stage = String(cp?.experience_stage || "").trim();
  return {
    city: first(cp?.target_locations, prefs?.target_locations),
    jobType: STAGES.includes(stage) ? stage : "",
    keyword: first(prefs?.target_keywords, cp?.target_roles, prefs?.target_roles),
  };
}

// 服务端筛选版：SSR 只取最新一屏作「即时首屏种子」，并查活跃总数；
// 真正的筛选/分页由前端挂载后调 /api/jobs/search 在服务端跑（库 10万+，不再前端全量加载）。
const PAGE1 = 60;

async function fetchFirstPageAndTotal(
  supabase: Awaited<ReturnType<typeof createServerSupabase>>,
): Promise<{ jobs: Job[]; total: number }> {
  const [page, head] = await Promise.all([
    supabase
      .from("jobs")
      .select("*")
      .eq("status", "active")
      .order("first_seen_at", { ascending: false })
      .range(0, PAGE1 - 1),
    supabase
      .from("jobs")
      .select("id", { count: "exact", head: true })
      .eq("status", "active"),
  ]);
  return { jobs: (page.data as Job[]) || [], total: head.count ?? 0 };
}

export default async function JobsPage() {
  const supabase = await createServerSupabase();
  const { data: { user } } = await supabase.auth.getUser();

  let preferences: UserPreferences | null = null;
  let actions: JobAction[] = [];
  let candidate: any = null;

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

    // 简历画像（偏好底层逻辑来源之一）：用于把筛选器从用户保存的偏好预填。
    const { data: cp } = await supabase
      .from("candidate_profiles")
      .select("experience_stage, target_locations, target_roles")
      .eq("user_id", user.id)
      .maybeSingle();
    candidate = cp;
  }

  // 默认按用户已保存偏好预填筛选器（城市/类型/关键词）；用户手动改即覆盖。
  const initialFilters = buildInitialFilters(preferences, candidate);

  const { jobs, total } = await fetchFirstPageAndTotal(supabase);

  const scored = sortAndFilterJobs(
    jobs,
    preferences,
    actions,
    { showIgnored: true, showApplied: true },
  );

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero
          eyebrow="岗位库"
          title="官方岗位检索与发现"
          description="从本地岗位库开始，按需刷新已知官网源，必要时再发现新的官方招聘入口。"
          icon={Database}
          action={
            <CountBadge>
              <Briefcase size={16} weight="fill" aria-hidden="true" />
              <span className="tabular-nums">{total} 个岗位</span>
            </CountBadge>
          }
        />
        <div className="mt-8">
          <JobsClient
            initialJobs={scored as ScoredJob[]}
            initialTotal={total}
            initialFilters={initialFilters}
          />
        </div>
      </ProductPage>
    </div>
  );
}

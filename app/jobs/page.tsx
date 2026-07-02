import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import JobLibraryStat from "@/components/JobLibraryStat";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import { jobsStoreEnabled, listLatestActive, countActiveForScope, countValidActive } from "@/lib/jobs-store/read";
import { sortAndFilterJobs } from "@/lib/scoring";
import type { Job, UserPreferences, JobAction, ScoredJob } from "@/lib/types";
import JobsClient from "./jobs-client";
import { Database } from "@phosphor-icons/react/ssr";

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
  preferences: UserPreferences | null,
): Promise<{ jobs: Job[]; total: number; libraryTotal: number }> {
  // jobs 已迁自建香港 PG（Phase 1）：配了 JOBS_DATABASE_URL 走 jobs-store；否则回退 Supabase。
  if (jobsStoreEnabled()) {
    const [jobs, total, libraryTotal] = await Promise.all([
      listLatestActive(PAGE1, 0, preferences),
      countActiveForScope(preferences),
      countValidActive(),
    ]);
    return { jobs: (jobs as Job[]) || [], total, libraryTotal };
  }
  const [page, validCount] = await Promise.all([
    supabase
      .from("jobs")
      .select("*")
      .eq("status", "active")
      .order("first_seen_at", { ascending: false })
      .range(0, PAGE1 - 1),
    // 首屏计数 = 「有效在招」(active + 有 JD 正文)，不用裸 count(active)（含薄卡/失活会虚高）。
    supabase.rpc("count_valid_active_jobs"),
  ]);
  const total = typeof validCount.data === "number" ? validCount.data : 0;
  return { jobs: (page.data as Job[]) || [], total, libraryTotal: total };
}

export default async function JobsPage() {
  const supabase = await createServerSupabase();
  const user = await getRequestUser();

  // 首屏岗位需要先拿到用户求职范围，避免海外/国内切换后 SSR 种子混入错误 scope。
  const userData = user
    ? await Promise.all([
        supabase.from("user_preferences").select("*").eq("user_id", user.id).single(),
        supabase.from("job_actions").select("*").eq("user_id", user.id),
        supabase
          .from("candidate_profiles")
          .select("experience_stage, target_locations, target_roles")
          .eq("user_id", user.id)
          .maybeSingle(),
      ])
    : null;

  const preferences = (userData?.[0].data as UserPreferences | null) ?? null;
  const actions = (userData?.[1].data as JobAction[] | null) ?? [];
  const candidate = userData?.[2].data ?? null;
  const firstPage = await fetchFirstPageAndTotal(supabase, preferences);

  // 默认按用户已保存偏好预填筛选器（城市/类型/关键词）；用户手动改即覆盖。
  const initialFilters = buildInitialFilters(preferences, candidate);

  const { jobs, total, libraryTotal } = firstPage;

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
          eyebrow="搜索岗位"
          title="探索完整官方岗位库"
          description="按公司、城市、岗位方向和条件主动搜索。每日推荐请回到「今日机会」。"
          icon={Database}
          align="start"
          action={
            <div className="w-full sm:w-[260px] lg:w-[280px]">
              {/* 实时翻动的岗位库总数（连后端真实数据，走 /api/jobs/stats 读香港库） */}
              <JobLibraryStat initialTotal={libraryTotal} />
            </div>
          }
        />
        <div className="mt-8">
          <JobsClient
            initialJobs={scored as ScoredJob[]}
            initialTotal={total}
            initialFilters={initialFilters}
            jobScope={preferences?.job_scope ?? "domestic"}
          />
        </div>
      </ProductPage>
    </div>
  );
}

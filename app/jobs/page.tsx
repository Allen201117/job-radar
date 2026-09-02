import { unstable_cache } from "next/cache";
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
    // 关键词框是**硬 AND 筛选条件**，只能放「想做什么」（方向），不能放「会什么」（技能）。
    // 原实现优先取 target_keywords —— 但简历解析是把技能/概念原样灌进那个字段的
    // （lib/scoring.ts:137 已就此定过调：技能判不了方向，用户没填目标岗位时才回退）。
    // 于是线上出现：某画像 target_keywords[0] = 「用户旅程」，被当成默认筛选词 →
    // FTS 的 search_doc 不含 JD 正文、全库 39 万在招岗没有一个标题带这四个字 →
    // 打开 /jobs 恒定「0 个匹配岗位」（2026-09-02 香港库直查坐实：命中 0 行）。
    // 改成方向优先后同一画像同一组筛选条件召回 943 个岗（live 实测）；技能只留作最后兜底。
    keyword: first(cp?.target_roles, prefs?.target_roles, prefs?.target_keywords),
  };
}

// 服务端筛选版：SSR 只取最新一屏作「即时首屏种子」，并查活跃总数；
// 真正的筛选/分页由前端挂载后调 /api/jobs/search 在服务端跑（库 10万+，不再前端全量加载）。
const PAGE1 = 60;

/**
 * 首屏三件套（最新 60 行 + 两个计数）按「求职范围」缓存，跨请求**跨实例**复用。
 *
 * 为什么值得缓存：`count_valid_active_jobs()` 要全扫 41 万行，香港库实测**冷 4.3s / 热 313ms**，
 * 而它是个**全局**数字（谁看都一样）、只在爬虫写入时才变（按天级）——以前每打开一次 /jobs 就重算一遍。
 * 三个查询里没有任何一项依赖「此刻」或用户私有数据。
 *
 * ⚠️ key 只取真正影响结果集的两项，且取**原始值**而非归一化后的值：`appendJobScopeWhere` 只读
 * `job_scope` + `target_regions`（见 lib/job-scope.ts），原样传回去重建即可产出逐字节相同的 SQL，
 * 不依赖「归一化是幂等的」这个假设。不含任何用户私有字段 → 跨用户共享安全。
 * ⚠️ 函数体内不得读 cookies()/headers()（unstable_cache 限制）；这里只调 jobs-store，安全。
 */
const loadJobsFirstScreen = unstable_cache(
  async (
    jobScope: string | null,
    targetRegions: string[],
  ): Promise<{ jobs: Job[]; total: number; libraryTotal: number }> => {
    const scopePrefs = { job_scope: jobScope, target_regions: targetRegions } as UserPreferences;
    const [jobs, total, libraryTotal] = await Promise.all([
      listLatestActive(PAGE1, 0, scopePrefs),
      countActiveForScope(scopePrefs),
      countValidActive(),
    ]);
    return { jobs: (jobs as Job[]) || [], total, libraryTotal };
  },
  ["jobs-first-screen-v1"],
  // 5 分钟：岗位库按天级写入，滞后用户感知不到；但足以让绝大多数请求不再全扫 41 万行。
  { revalidate: 300, tags: ["jobs-first-screen"] },
);

async function fetchFirstPageAndTotal(
  supabase: Awaited<ReturnType<typeof createServerSupabase>>,
  preferences: UserPreferences | null,
): Promise<{ jobs: Job[]; total: number; libraryTotal: number }> {
  // jobs 已迁自建香港 PG（Phase 1）：配了 JOBS_DATABASE_URL 走 jobs-store；否则回退 Supabase。
  if (jobsStoreEnabled()) {
    return loadJobsFirstScreen(
      preferences?.job_scope ?? null,
      (preferences?.target_regions as string[] | undefined) ?? [],
    );
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
        >
          {/* 岗位库数据条：从「报头右侧的竖卡」改到「标题下的横条」。旧形态把筛选器压到 y≈550，
              1440×900 首屏一条岗位都看不到；横条省下 ~150px，让筛选器和首批结果进首屏。 */}
          <JobLibraryStat initialTotal={libraryTotal} />
        </ProductHero>
        <div className="mt-6">
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

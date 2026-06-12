import Navbar from "@/components/Navbar";
import { EmptyPanel, MetricTile, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase } from "@/lib/auth";
import { matchTier, sortAndFilterJobs } from "@/lib/scoring";
import { mergeRecallJobs } from "@/lib/today-recall";
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

type ServerSupabase = Awaited<ReturnType<typeof createServerSupabase>>;

// 页面与 JobCard 实际渲染用到的列（从 select * 收窄）
const JOB_COLUMNS =
  "id,company,title,location,job_type,summary,jd_url,salary_text,posted_at,experience,education,deadline,first_seen_at";

// or/ilike 过滤串里的保留字符（% , ( )）替换为空格，避免破坏 PostgREST 过滤语法
function escapeLike(value: string) {
  return value.replace(/[%,()]/g, " ").trim();
}

// 最新 active 岗位（未登录 / 无偏好 / 预筛失败 / 预筛不足时的兜底来源）
async function fetchLatestActive(supabase: ServerSupabase): Promise<Job[]> {
  const { data } = await supabase
    .from("jobs")
    .select(JOB_COLUMNS)
    .eq("status", "active")
    .order("first_seen_at", { ascending: false })
    .limit(200);
  return (data as Job[]) || [];
}

// 两段召回：① 按偏好 SQL 预筛——location 命中任一 target_location 且 title 命中任一
// target_role/target_keyword（中文直接子串，无需分词），status='active'，最新 200 条；
// ② 预筛不足 50 条再补「最新 active」兜底（去重在 mergeRecallJobs 内完成）。
// 无偏好信号或查询失败一律回退最新 200，绝不让页面 500。
async function recallTodayJobs(
  supabase: ServerSupabase,
  preferences: UserPreferences | null,
): Promise<Job[]> {
  const locTerms = (preferences?.target_locations || [])
    .map(escapeLike)
    .filter(Boolean)
    .slice(0, 10);
  // 偏好关键词条数多时只取前 10，规避 supabase or/ilike 组合的 URL 长度限制
  const titleTerms = Array.from(
    new Set([
      ...(preferences?.target_roles || []),
      ...(preferences?.target_keywords || []),
    ]),
  )
    .map(escapeLike)
    .filter(Boolean)
    .slice(0, 10);

  // 没有任何可用于预筛的偏好信号 → 维持现状（最新 200）
  if (!locTerms.length && !titleTerms.length) {
    return fetchLatestActive(supabase);
  }

  try {
    let builder = supabase
      .from("jobs")
      .select(JOB_COLUMNS)
      .eq("status", "active");
    // 两次 .or() 在 PostgREST 中按 AND 组合 →（命中任一城市）AND（命中任一职位词）
    if (locTerms.length) {
      builder = builder.or(
        locTerms.map((t) => `location.ilike.%${t}%`).join(","),
      );
    }
    if (titleTerms.length) {
      builder = builder.or(
        titleTerms.map((t) => `title.ilike.%${t}%`).join(","),
      );
    }
    const { data, error } = await builder
      .order("first_seen_at", { ascending: false })
      .limit(200);
    if (error) throw error;

    const preferred = (data as Job[]) || [];
    // 预筛不足 50 条才补一段最新 active 兜底；多取的兜底由合并函数去重 + 截断
    const fallback =
      preferred.length < 50 ? await fetchLatestActive(supabase) : [];
    return mergeRecallJobs(preferred, fallback, {
      target: 200,
      minPreferred: 50,
    });
  } catch (err) {
    console.error(
      "[today] 偏好预筛失败，回退最新 200 条",
      (err as Error).message,
    );
    return fetchLatestActive(supabase);
  }
}

export default async function TodayPage() {
  const supabase = await createServerSupabase();
  const { data: { user } } = await supabase.auth.getUser();

  let preferences: UserPreferences | null = null;
  let actions: JobAction[] = [];

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

  // 偏好预筛 + 最新兜底两段召回（取代旧的盲取最新 200 条，详见 recallTodayJobs）。
  // 偏好此前只参与排序、未参与召回，导致看板被最后爬完的大厂批量岗位刷屏。
  const jobs = await recallTodayJobs(supabase, preferences);

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

  const highMatchCount = scored.filter(
    (j) => matchTier(j.match_score).level === "high",
  ).length;
  const savedCount = allScored.filter((j) => j.user_action === "saved").length;
  const appliedCount = allScored.filter((j) => j.user_action === "applied").length;
  const ignoredCount = allScored.filter((j) => j.user_action === "ignored").length;

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero
          eyebrow="今日看板"
          title="官方岗位的每日优先队列"
          description="根据你的偏好和简历画像排序，隐藏已忽略和已投递岗位，把今天最值得看的官方机会放在前面。"
          icon={Broadcast}
          action={
            <div className="rounded-2xl border border-black/[0.07] bg-white/70 px-4 py-3 text-[14px] font-medium text-[#5f594e]">
              显示上限 {preferences?.daily_limit || 20} 个岗位
            </div>
          }
        >
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
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

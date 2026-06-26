import Navbar from "@/components/Navbar";
import { CountBadge, EmptyPanel, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import { jobsStoreEnabled, jobsByIds } from "@/lib/jobs-store/read";
import { ArrowSquareOut, Briefcase, CheckCircle, MapPin } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

type Snapshot = { company?: string | null; title?: string | null; location?: string | null; jd_url?: string | null };

export default async function AppliedPage() {
  const supabase = await createServerSupabase();
  const user = await getRequestUser();

  if (!user) {
    return (
      <div className="min-h-screen bg-editorial">
        <Navbar />
        <ProductPage maxWidth="max-w-5xl">
          <ProductHero eyebrow="已投递" title="已完成投递的岗位" icon={CheckCircle} />
          <div className="mt-6">
            <EmptyPanel title="加载中，请稍候" description="正在读取你的投递记录。" />
          </div>
        </ProductPage>
      </div>
    );
  }

  const { data: actions } = await supabase
    .from("job_actions")
    .select("job_id, created_at, job_snapshot")
    .eq("user_id", user.id)
    .eq("action", "applied")
    .order("created_at", { ascending: false });

  if (!actions || actions.length === 0) {
    return (
      <div className="min-h-screen bg-editorial">
        <Navbar />
        <ProductPage maxWidth="max-w-5xl">
          <ProductHero eyebrow="已投递" title="已完成投递的岗位" icon={CheckCircle} />
          <div className="mt-6">
            <EmptyPanel title="还没有标记任何已投递岗位" description="在岗位卡片里点击「已投递」后，这里会形成你的投递记录。" />
          </div>
        </ProductPage>
      </div>
    );
  }

  // 先从权威 jobs 库按 id 取仍存在的岗位；已被物理清理的用 job_actions.job_snapshot 兜底，不丢投递历史。
  const jobIds = actions.map((a: { job_id: string }) => a.job_id);
  const liveJobs = jobsStoreEnabled()
    ? await jobsByIds(jobIds, false)
    : (await supabase.from("jobs").select("*").in("id", jobIds)).data ?? [];
  const liveMap = new Map((liveJobs || []).map((j: any) => [j.id, j]));

  const items = actions.map((a: { job_id: string; created_at: string; job_snapshot: Snapshot | null }) => {
    const live = liveMap.get(a.job_id);
    const snap = (a.job_snapshot || {}) as Snapshot;
    return {
      jobId: a.job_id,
      createdAt: a.created_at,
      company: live?.company || snap.company || "公司信息缺失",
      title: live?.title || snap.title || "原岗位已下线",
      location: live?.location || snap.location || null,
      jdUrl: live?.jd_url || null, // 已下线岗位不提供失效官网链接
      down: !live,
    };
  });

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="已投递"
          title="已完成投递的岗位"
          icon={CheckCircle}
          action={
            <CountBadge>
              <Briefcase size={16} weight="fill" aria-hidden="true" />
              <span className="tabular-nums">{items.length} 个</span>
            </CountBadge>
          }
        />
        <div className="mt-6 space-y-3">
          {items.map((item) => (
            <div key={item.jobId} className="surface surface-hover p-5 text-[#1a1714] dark:text-[#f3ecdf]">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <span className="text-xs font-medium text-[#8a8275] dark:text-[#9a9184]">{item.company}</span>
                  <h3 className="mt-1 text-lg font-semibold">{item.title}</h3>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[#8a8275] dark:text-[#9a9184]">
                    {item.location && (
                      <span className="inline-flex items-center gap-1 rounded-full border border-black/[0.06] dark:border-white/[0.1] bg-[#f4efe6] dark:bg-[#16130f] px-2 py-1">
                        <MapPin size={13} weight="fill" aria-hidden="true" />
                        {item.location}
                      </span>
                    )}
                    投递于 {item.createdAt ? new Date(item.createdAt).toLocaleDateString("zh-CN") : "—"}
                  </div>
                </div>
                {item.down ? (
                  <span className="inline-flex w-full shrink-0 items-center justify-center gap-2 rounded-full border border-black/[0.08] bg-[#f0ece2] px-4 py-2.5 text-sm font-medium text-[#9a9184] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#837c70] sm:w-auto sm:py-2">
                    原岗位已下线
                  </span>
                ) : (
                  <a
                    href={item.jdUrl!}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex w-full shrink-0 items-center justify-center gap-2 rounded-full bg-[#1a1714] dark:bg-[#f3ecdf] px-4 py-2.5 text-sm font-semibold text-[#f7f1e6] dark:text-[#16130f] transition duration-200 hover:bg-[#2b2520] dark:hover:bg-[#e8ddca] active:scale-[0.98] sm:w-auto sm:py-2"
                  >
                    查看官网
                    <ArrowSquareOut size={16} weight="bold" aria-hidden="true" />
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      </ProductPage>
    </div>
  );
}

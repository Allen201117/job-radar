import Navbar from "@/components/Navbar";
import { CountBadge, EmptyPanel, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase } from "@/lib/auth";
import { ArrowSquareOut, Briefcase, CheckCircle, MapPin } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

export default async function AppliedPage() {
  const supabase = await createServerSupabase();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    return (
      <div className="min-h-screen bg-[#08090c]">
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
    .select("job_id, created_at")
    .eq("user_id", user.id)
    .eq("action", "applied")
    .order("created_at", { ascending: false });

  if (!actions || actions.length === 0) {
    return (
      <div className="min-h-screen bg-[#08090c]">
        <Navbar />
        <ProductPage maxWidth="max-w-5xl">
          <ProductHero eyebrow="已投递" title="已完成投递的岗位" icon={CheckCircle} />
          <div className="mt-6">
            <EmptyPanel title="还没有标记任何已投递岗位" description="在岗位卡片里点击标记投递后，这里会形成你的投递记录。" />
          </div>
        </ProductPage>
      </div>
    );
  }

  const jobIds = actions.map((a: { job_id: string }) => a.job_id);
  const appliedMap = new Map(actions.map((a: { job_id: string; created_at: string }) => [a.job_id, a.created_at]));

  const { data: jobs } = await supabase.from("jobs").select("*").in("id", jobIds);

  return (
    <div className="min-h-screen bg-[#08090c]">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="已投递"
          title="已完成投递的岗位"
          icon={CheckCircle}
          action={
            <CountBadge>
              <Briefcase size={16} weight="fill" aria-hidden="true" />
              <span className="tabular-nums">{(jobs || []).length} 个</span>
            </CountBadge>
          }
        />
        <div className="mt-6 space-y-3">
          {(jobs || []).map((job: any) => (
            <div key={job.id} className="rounded-[1.35rem] border border-white/10 bg-white/[0.065] p-5 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] transition duration-200 hover:-translate-y-0.5 hover:border-white/18 hover:bg-white/[0.085]">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <span className="text-xs font-medium text-white/50">{job.company}</span>
                  <h3 className="mt-1 text-lg font-semibold">{job.title}</h3>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-white/50">
                    {job.location && (
                      <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/10 px-2 py-1">
                        <MapPin size={13} weight="fill" aria-hidden="true" />
                        {job.location}
                      </span>
                    )}
                    {job.job_type && <span>{job.job_type} · </span>}
                    投递于 {appliedMap.get(job.id) ? new Date(appliedMap.get(job.id)!).toLocaleDateString("zh-CN") : "—"}
                  </div>
                </div>
                <a href={job.jd_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-full bg-sky-300 px-4 py-2 text-sm font-semibold text-sky-950 transition duration-200 hover:bg-sky-200 active:scale-[0.98]">
                  查看官网
                  <ArrowSquareOut size={16} weight="bold" aria-hidden="true" />
                </a>
              </div>
            </div>
          ))}
        </div>
      </ProductPage>
    </div>
  );
}

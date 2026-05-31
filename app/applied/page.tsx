import Navbar from "@/components/Navbar";
import { createServerSupabase } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function AppliedPage() {
  const supabase = await createServerSupabase();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    return (
      <div>
        <Navbar />
        <main className="mx-auto max-w-4xl px-4 py-8">
          <h1 className="text-2xl font-semibold tracking-tight">已投递</h1>
          <p className="mt-6 py-12 text-center text-muted-foreground">加载中，请稍候...</p>
        </main>
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
      <div>
        <Navbar />
        <main className="mx-auto max-w-4xl px-4 py-8">
          <h1 className="text-2xl font-semibold tracking-tight">已投递</h1>
          <p className="mt-6 py-12 text-center text-muted-foreground">还没有标记任何已投递岗位。</p>
        </main>
      </div>
    );
  }

  const jobIds = actions.map((a: { job_id: string }) => a.job_id);
  const appliedMap = new Map(actions.map((a: { job_id: string; created_at: string }) => [a.job_id, a.created_at]));

  const { data: jobs } = await supabase.from("jobs").select("*").in("id", jobIds);

  return (
    <div>
      <Navbar />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <h1 className="text-2xl font-semibold tracking-tight">
          已投递 <span className="ml-2 text-base font-normal text-muted-foreground">({(jobs || []).length} 个)</span>
        </h1>
        <div className="mt-6 space-y-3">
          {(jobs || []).map((job: any) => (
            <div key={job.id} className="rounded-lg border bg-card p-4 shadow-sm">
              <div className="flex items-start justify-between">
                <div>
                  <span className="text-xs font-medium text-muted-foreground">{job.company}</span>
                  <h3 className="font-medium">{job.title}</h3>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {job.location && <span>{job.location} · </span>}
                    {job.job_type && <span>{job.job_type} · </span>}
                    投递于 {appliedMap.get(job.id) ? new Date(appliedMap.get(job.id)!).toLocaleDateString("zh-CN") : "—"}
                  </div>
                </div>
                <a href={job.jd_url} target="_blank" rel="noreferrer" className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90">
                  查看官网
                </a>
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

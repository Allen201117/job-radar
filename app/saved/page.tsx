import Navbar from "@/components/Navbar";
import { createServerSupabase } from "@/lib/auth";
import SavedClient from "./saved-client";

export const dynamic = "force-dynamic";

export default async function SavedPage() {
  const supabase = await createServerSupabase();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    return (
      <div>
        <Navbar />
        <main className="mx-auto max-w-4xl px-4 py-8">
          <h1 className="text-2xl font-semibold tracking-tight">已收藏</h1>
          <p className="mt-6 py-12 text-center text-muted-foreground">
            加载中，请稍候...
          </p>
        </main>
      </div>
    );
  }

  const { data: actions } = await supabase
    .from("job_actions")
    .select("job_id")
    .eq("user_id", user.id)
    .eq("action", "saved");

  if (!actions || actions.length === 0) {
    return (
      <div>
        <Navbar />
        <main className="mx-auto max-w-4xl px-4 py-8">
          <h1 className="text-2xl font-semibold tracking-tight">已收藏</h1>
          <p className="mt-6 py-12 text-center text-muted-foreground">
            还没有收藏任何岗位。
          </p>
        </main>
      </div>
    );
  }

  const jobIds = actions.map((a: { job_id: string }) => a.job_id);
  const { data: jobs } = await supabase.from("jobs").select("*").in("id", jobIds).eq("status", "active");

  return (
    <div>
      <Navbar />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <h1 className="text-2xl font-semibold tracking-tight">
          已收藏 <span className="ml-2 text-base font-normal text-muted-foreground">({(jobs || []).length} 个)</span>
        </h1>
        <div className="mt-6">
          <SavedClient initialJobs={jobs || []} />
        </div>
      </main>
    </div>
  );
}

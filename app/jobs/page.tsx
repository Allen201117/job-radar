import Navbar from "@/components/Navbar";
import { createServerSupabase } from "@/lib/auth";
import { sortAndFilterJobs } from "@/lib/scoring";
import type { Job, UserPreferences, JobAction, ScoredJob } from "@/lib/types";
import JobsClient from "./jobs-client";

export const dynamic = "force-dynamic";

export default async function JobsPage() {
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

  const { data: jobs } = await supabase
    .from("jobs")
    .select("*")
    .eq("status", "active")
    .order("first_seen_at", { ascending: false })
    .limit(500);

  const scored = sortAndFilterJobs(
    (jobs as Job[]) || [],
    preferences,
    actions,
    { showIgnored: true, showApplied: true },
  );

  const companies = Array.from(
    new Set((jobs as Job[])?.map((j) => j.company).filter(Boolean)),
  ) as string[];

  return (
    <div>
      <Navbar />
      <main className="mx-auto max-w-5xl px-4 py-8">
        <h1 className="text-2xl font-semibold tracking-tight">
          岗位库
          <span className="ml-2 text-base font-normal text-muted-foreground">
            ({scored.length} 个岗位)
          </span>
        </h1>
        <div className="mt-6">
          <JobsClient initialJobs={scored as ScoredJob[]} companies={companies} />
        </div>
      </main>
    </div>
  );
}

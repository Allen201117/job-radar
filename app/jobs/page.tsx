import Navbar from "@/components/Navbar";
import { CountBadge, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase } from "@/lib/auth";
import { sortAndFilterJobs } from "@/lib/scoring";
import type { Job, UserPreferences, JobAction, ScoredJob } from "@/lib/types";
import JobsClient from "./jobs-client";
import { Briefcase, Database } from "@phosphor-icons/react/ssr";

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
    <div className="min-h-screen bg-[#08090c]">
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
              <span className="tabular-nums">{scored.length} 个岗位</span>
            </CountBadge>
          }
        />
        <div className="mt-8">
          <JobsClient initialJobs={scored as ScoredJob[]} companies={companies} />
        </div>
      </ProductPage>
    </div>
  );
}

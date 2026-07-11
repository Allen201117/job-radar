import Link from "next/link";
import Navbar from "@/components/Navbar";
import { CountBadge, EmptyPanel, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import { jobsStoreEnabled, jobsByIds } from "@/lib/jobs-store/read";
import { Briefcase, CheckCircle } from "@phosphor-icons/react/ssr";
import AppliedClient, { type AppliedItem } from "./applied-client";

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

  // select * 而非点名列：stage 列由迁移 173 提供，部署与迁移有先后竞态时点名会整页报错
  const { data: actions } = await supabase
    .from("job_actions")
    .select("*")
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
            <EmptyPanel
              title="还没有标记任何已投递岗位"
              description="在岗位卡片里点击「标记投递」，这里会形成你的投递记录。"
              action={
                <Link href="/today" className="btn-ink">
                  返回今日机会
                </Link>
              }
            />
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

  const items: AppliedItem[] = actions.map(
    (a: { job_id: string; created_at: string; job_snapshot: Snapshot | null; stage?: string | null }) => {
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
        stage: a.stage ?? null,
      };
    },
  );

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
        <div className="mt-6">
          <AppliedClient items={items} />
        </div>
      </ProductPage>
    </div>
  );
}

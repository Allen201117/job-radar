import Navbar from "@/components/Navbar";
import { CountBadge, EmptyPanel, ProductHero, ProductPage } from "@/components/ProductChrome";
import { createServerSupabase } from "@/lib/auth";
import SavedClient from "./saved-client";
import { BookmarkSimple, Briefcase } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

export default async function SavedPage() {
  const supabase = await createServerSupabase();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    return (
      <div className="min-h-screen bg-editorial">
        <Navbar />
        <ProductPage maxWidth="max-w-5xl">
          <ProductHero eyebrow="已收藏" title="待进一步比较的岗位" icon={BookmarkSimple} />
          <div className="mt-6">
            <EmptyPanel title="加载中，请稍候" description="正在读取你的收藏岗位。" />
          </div>
        </ProductPage>
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
      <div className="min-h-screen bg-editorial">
        <Navbar />
        <ProductPage maxWidth="max-w-5xl">
          <ProductHero eyebrow="已收藏" title="待进一步比较的岗位" icon={BookmarkSimple} />
          <div className="mt-6">
            <EmptyPanel title="还没有收藏任何岗位" description="在今日看板或岗位库里点击收藏后，岗位会出现在这里。" />
          </div>
        </ProductPage>
      </div>
    );
  }

  const jobIds = actions.map((a: { job_id: string }) => a.job_id);
  const { data: jobs } = await supabase.from("jobs").select("*").in("id", jobIds).eq("status", "active");

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="已收藏"
          title="待进一步比较的岗位"
          icon={BookmarkSimple}
          action={
            <CountBadge>
              <Briefcase size={16} weight="fill" aria-hidden="true" />
              <span className="tabular-nums">{(jobs || []).length} 个</span>
            </CountBadge>
          }
        />
        <div className="mt-8">
          <SavedClient initialJobs={jobs || []} />
        </div>
      </ProductPage>
    </div>
  );
}

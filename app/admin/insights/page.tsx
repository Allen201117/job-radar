import AdminNav from "@/components/AdminNav";
import { eventLabel } from "@/lib/track";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import InsightsAdminClient from "@/components/InsightsAdminClient";
import InsightSubjectsAdmin from "@/components/InsightSubjectsAdmin";
import { isAdmin } from "@/lib/auth";
import { createServiceClient } from "@/lib/supabaseService";
import { aggregateEventCounts } from "@/lib/track";
import { redirect } from "next/navigation";
import { Sparkle } from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

// 近 7 天事件计数（service-role 读，按 event 分组）。失败不崩页，回退为错误提示。
async function loadEventStats(): Promise<{
  error: string | null;
  rows: Array<{ event: string; count: number }>;
}> {
  try {
    const service = createServiceClient();
    const since = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
    const { data, error } = await service
      .from("events")
      .select("event")
      .gte("created_at", since)
      .limit(50000);
    if (error) return { error: error.message, rows: [] };
    return { error: null, rows: aggregateEventCounts(data || []) };
  } catch (e) {
    return { error: (e as Error).message, rows: [] };
  }
}

export default async function InsightsAdminPage() {
  if (!(await isAdmin())) {
    redirect("/");
  }

  const stats = await loadEventStats();

  return (
    <div className="min-h-screen bg-editorial">
      <AdminNav />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="洞察管理"
          title="录入、编辑、下架职业洞察，处理申诉"
          description="新增或修改一条洞察时，会先自动检查：可信度分级够不够、有没有暴露个人信息、来源标注全不全、内容是不是过期了。任何一项不过关都会直接告诉你卡在哪。全程网页操作，不用写代码。"
          icon={Sparkle}
        />

        <section className="surface mb-6 p-5 ink-1 sm:p-6">
          <h2 className="text-base font-semibold">最近 7 天，用户都在做什么</h2>
          <p className="mt-1 text-xs ink-3 ">
            按动作统计最近 7 天的次数，用来判断哪些功能真的有人用、哪些没人碰。更完整的用户行为分析在「运营看板 → 用户行为」。
          </p>
          {stats.error ? (
            <p className="mt-4 rounded-xl border border-[#e0b4ac] bg-[#f7e6e1] px-3.5 py-2.5 text-sm text-[#9c4a3c] dark:border-[#7a392e]/[0.60] dark:bg-[#3a201a] dark:text-[#e6a99f]">
              统计暂不可用：{stats.error}
            </p>
          ) : stats.rows.length === 0 ? (
            <p className="mt-4 text-sm ink-3 ">最近 7 天没有任何用户操作记录。</p>
          ) : (
            <table className="mt-4 w-full max-w-md text-sm">
              <thead>
                <tr className="border-b border-black/[0.08] text-left text-xs ink-3 dark:border-white/[0.1] ">
                  <th className="py-2 font-medium">用户做了什么</th>
                  <th className="py-2 text-right font-medium">近 7 天次数</th>
                </tr>
              </thead>
              <tbody>
                {stats.rows.map((r) => (
                  <tr key={r.event} className="border-b border-black/[0.05] dark:border-white/[0.1]">
                    <td className="py-2 ink-2 ">{eventLabel(r.event)}</td>
                    <td className="py-2 text-right font-semibold tabular-nums">{r.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <InsightsAdminClient />
        <InsightSubjectsAdmin />
      </ProductPage>
    </div>
  );
}

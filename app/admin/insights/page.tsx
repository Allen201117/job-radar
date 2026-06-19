import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import InsightsAdminClient from "@/components/InsightsAdminClient";
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
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          eyebrow="洞察管理"
          title="录入、编辑、下架职业洞察，处理申诉"
          description="新增/编辑条目时必过分级、去标识、归因、时效校验门；不过门会提示卡在哪。全程网页操作，无需写 SQL。"
          icon={Sparkle}
        />

        <section className="surface mb-6 p-5 text-[#1a1714] dark:text-[#f3ecdf] sm:p-6">
          <h2 className="text-base font-semibold">近 7 天事件计数</h2>
          <p className="mt-1 text-xs text-[#8a8275] dark:text-[#9a9184]">
            自有最小埋点（无第三方分析 SDK）。用于判断职业洞察 / 岗位点击 / 刷新等功能是否有人用。
          </p>
          {stats.error ? (
            <p className="mt-4 rounded-xl border border-[#e0b4ac] bg-[#f7e6e1] px-3.5 py-2.5 text-sm text-[#9c4a3c] dark:border-[#7a392e]/60 dark:bg-[#3a201a] dark:text-[#e6a99f]">
              统计暂不可用：{stats.error}
            </p>
          ) : stats.rows.length === 0 ? (
            <p className="mt-4 text-sm text-[#8a8275] dark:text-[#9a9184]">近 7 天暂无事件。</p>
          ) : (
            <table className="mt-4 w-full max-w-md text-sm">
              <thead>
                <tr className="border-b border-black/[0.08] text-left text-xs text-[#8a8275] dark:border-white/[0.1] dark:text-[#9a9184]">
                  <th className="py-2 font-medium">事件</th>
                  <th className="py-2 text-right font-medium">近 7 天次数</th>
                </tr>
              </thead>
              <tbody>
                {stats.rows.map((r) => (
                  <tr key={r.event} className="border-b border-black/[0.05] dark:border-white/[0.1]">
                    <td className="py-2 font-mono text-[#3f3a33] dark:text-[#d9d0c2]">{r.event}</td>
                    <td className="py-2 text-right font-semibold tabular-nums">{r.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <InsightsAdminClient />
      </ProductPage>
    </div>
  );
}

import { NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabaseService";
import { jobsStoreEnabled, countValidActive, countRecentActive } from "@/lib/jobs-store/read";

export const dynamic = "force-dynamic";

// 岗位库定时计数（前端卡片轮询）。
// 有效在招 + 24h 确认在招走自建香港 jobs 库（Phase 1 真实数据源，配了 JOBS_DATABASE_URL 即用），
// 未配置时回退 Supabase；官方源计数始终走 Supabase（sources 表仍在 Supabase）。
// 以服务端读取取代旧的「浏览器直连 Supabase」——避免 jobs 已迁香港库后客户端读到空表/失活计数。
export async function GET() {
  const dayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

  try {
    // Publicly cached global aggregates must use one fixed server identity. A cookie-bound
    // client can expose RLS-dependent counts and let an anonymous zero poison the CDN cache.
    const supabase = createServiceClient();
    const useStore = jobsStoreEnabled();

    const [validActive, recent24h, srcRes] = await Promise.all([
      useStore
        ? countValidActive()
        : supabase
            .rpc("count_valid_active_jobs")
            .then((r) => {
              if (r.error) throw r.error;
              return typeof r.data === "number" ? r.data : 0;
            }),
      useStore
        ? countRecentActive(dayAgo)
        : supabase
            .from("jobs")
            .select("id", { count: "exact", head: true })
            .eq("status", "active")
            .gte("last_seen_at", dayAgo)
            .then((r) => {
              if (r.error) throw r.error;
              return r.count ?? 0;
            }),
      supabase.from("sources").select("id", { count: "exact", head: true }).eq("enabled", true),
    ]);

    if (srcRes.error) throw srcRes.error;

    return NextResponse.json(
      { ok: true, validActive, recent24h, sources: srcRes.count ?? 0 },
      { headers: { "Cache-Control": "public, s-maxage=60, stale-while-revalidate=300" } },
    );
  } catch (err) {
    console.error("[api/jobs/stats] 计数失败", (err as Error).message);
    return NextResponse.json(
      { ok: false, error: "stats_failed" },
      { status: 500, headers: { "Cache-Control": "no-store" } },
    );
  }
}

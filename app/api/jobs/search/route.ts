import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { createServiceClient } from "@/lib/supabaseService";
import { searchJobs } from "@/lib/job-search";
import { searchJobsStore } from "@/lib/jobs-store/search";
import { DEFAULT_FILTERS, type Filters } from "@/lib/job-filter";
import { fetchAllSources } from "@/lib/supabase-paginate";
import type { JobAction, UserPreferences } from "@/lib/types";

export const dynamic = "force-dynamic";
// 候选窗口最大 15k 行 + 打分/精筛，给足执行时间（避免大城搜索被默认 10s 砍断）。
export const maxDuration = 60;
// ⚡ 与自建香港 jobs 库同区运行：函数默认落在 iad1（美东），跨太平洋拉几千行候选是搜索慢(10~30s)的主因
// （实测 x-vercel-id=sin1::iad1，SQL 仅 130ms、JS 仅 113ms，其余全耗在跨区传输）。就近到香港/新加坡后
// 候选行传输从跨洋降到近同区。Pro 计划下 preferredRegion 生效；Hobby 计划该项被忽略，需在 Vercel
// 控制台 Settings → Functions → Region 改单区为 hkg1/sin1（见汇报说明）。
export const preferredRegion = ["hkg1", "sin1"];

// 服务端岗位库搜索：把原前端「全库塞浏览器再筛」改为服务端有界筛选 + 分页。
// 筛选/排序逻辑复用 lib/job-filter（与浏览器端同一份），结果逐字段一致。
export async function GET(request: NextRequest) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const p = request.nextUrl.searchParams;
  const bool = (k: string) => p.get(k) === "1" || p.get(k) === "true";
  const filters: Filters = {
    ...DEFAULT_FILTERS,
    company: p.get("company") || "",
    city: p.get("city") || "",
    jobType: p.get("jobType") || "",
    keyword: p.get("keyword") || "",
    capitalOrigin: p.get("capitalOrigin") || "",
    region: p.get("region") || "",
    education: p.get("education") || "",
    salaryOnly: bool("salaryOnly"),
    sponsorshipOnly: bool("sponsorshipOnly"),
    showIgnored: bool("showIgnored"),
    showApplied: bool("showApplied"),
    showNewOnly: bool("showNewOnly"),
    sortBy: p.get("sortBy") === "newest" ? "newest" : "match",
  };
  const offset = Math.max(0, Number(p.get("offset") || 0));
  const limit = Math.min(Math.max(1, Number(p.get("limit") || 60)), 100);

  // 匿名也可浏览（与岗位库页一致）：无用户则偏好为空、打分为 0，不报 401。
  let preferences: UserPreferences | null = null;
  let actions: JobAction[] = [];
  if (user) {
    // 偏好与操作互不依赖 → 并行拉，少一趟跨区往返（函数在美东、Supabase 跨区，串行往返会叠加固定开销）。
    const [{ data: prefs }, { data: acts }] = await Promise.all([
      supabase.from("user_preferences").select("*").eq("user_id", user.id).single(),
      supabase.from("job_actions").select("*").eq("user_id", user.id),
    ]);
    preferences = (prefs as UserPreferences | null) ?? null;
    actions = (acts as JobAction[]) || [];
  }

  try {
    // 资本来源筛选需按来源判岗位国籍：jobs（香港库）无 adapter 列、sources 在 Supabase、跨库无法 SQL join，
    // 这里用 service-role 查一次 source_id→adapter_name 映射传给搜索层（绕 RLS，保证匿名浏览也生效）。
    // 仅 capitalOrigin 非空时才查（常规搜索零额外开销）；搜索层据此给候选岗位标注 source_adapter。
    // ⚠️ 必须分页拉全量（sources 1121 行 > PostgREST 单次 1000 行上限）：截断后 map 缺条目
    // → 尾部源的岗位判不出资本来源、被资本来源筛选静默漏掉。
    let adapterBySource: Map<string, string | null> | null = null;
    if (filters.capitalOrigin) {
      const srcRows = await fetchAllSources<{ id: string; adapter_name: string | null }>(
        createServiceClient(),
        "id, adapter_name",
      );
      adapterBySource = new Map(srcRows.map((s) => [s.id, s.adapter_name] as [string, string | null]));
    }
    // jobs 已迁到自建香港 PG（Phase 1）：配了 JOBS_DATABASE_URL 走 jobs-store（直连香港库，同 FTS/同精筛）；
    // 否则回退 Supabase service-role 读（本地无 env / 迁移回滚时仍可用）。prefs/actions 仍来自 Supabase。
    const result = process.env.JOBS_DATABASE_URL
      ? await searchJobsStore(filters, preferences, actions, offset, limit, adapterBySource)
      : await searchJobs(createServiceClient(), filters, preferences, actions, offset, limit, adapterBySource);
    return NextResponse.json({ ok: true, ...result });
  } catch (e: any) {
    return NextResponse.json(
      { ok: false, error: e?.message || "search_failed" },
      { status: 500 },
    );
  }
}

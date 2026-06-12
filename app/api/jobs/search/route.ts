import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { createServiceClient } from "@/lib/supabaseService";
import { searchJobs } from "@/lib/job-search";
import { DEFAULT_FILTERS, type Filters } from "@/lib/job-filter";
import type { JobAction, UserPreferences } from "@/lib/types";

export const dynamic = "force-dynamic";
// 候选窗口最大 15k 行 + 打分/精筛，给足执行时间（避免大城搜索被默认 10s 砍断）。
export const maxDuration = 60;

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
    salaryOnly: bool("salaryOnly"),
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
    const { data: prefs } = await supabase
      .from("user_preferences")
      .select("*")
      .eq("user_id", user.id)
      .single();
    preferences = (prefs as UserPreferences | null) ?? null;

    const { data: acts } = await supabase
      .from("job_actions")
      .select("*")
      .eq("user_id", user.id);
    actions = (acts as JobAction[]) || [];
  }

  try {
    // jobs 是公开可读表；用 service-role 客户端做大候选读，绕开 anon/authenticated 角色的
    // statement_timeout（未建索引时全库 ilike/排序会超该超时而失败）。打分用的 prefs/actions 已在上面按用户取。
    const db = createServiceClient();
    const result = await searchJobs(db, filters, preferences, actions, offset, limit);
    return NextResponse.json({ ok: true, ...result });
  } catch (e: any) {
    return NextResponse.json(
      { ok: false, error: e?.message || "search_failed" },
      { status: 500 },
    );
  }
}

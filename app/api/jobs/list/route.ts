import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { jobsStoreEnabled, listLatestActive } from "@/lib/jobs-store/read";
import { sortAndFilterJobs } from "@/lib/scoring";
import type { Job, UserPreferences, JobAction } from "@/lib/types";

export const dynamic = "force-dynamic";

// 岗位库分页接口：返回某一页（按 first_seen_at desc）的「已打分」岗位。
// 岗位库页 SSR 只出第一页，前端挂载后用本接口后台分块拉完剩余 → 合并进内存库（解除展示硬上限，避免一次性塞满 props）。
// 打分口径与岗位库页 SSR 一致（同 sortAndFilterJobs + 用户偏好/操作），合并后前端再按 match_score/最新统一排序。
export async function GET(request: NextRequest) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const params = request.nextUrl.searchParams;
  const offset = Math.max(0, Number(params.get("offset") || 0));
  const limit = Math.min(Math.max(1, Number(params.get("limit") || 1000)), 1000);

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

  // jobs 已迁自建香港 PG：配了 env 走 jobs-store；否则 Supabase。异常统一 500。
  let data: Job[] = [];
  try {
    data = jobsStoreEnabled()
      ? ((await listLatestActive(limit, offset)) as Job[])
      : (((await supabase
          .from("jobs").select("*").eq("status", "active")
          .order("first_seen_at", { ascending: false })
          .range(offset, offset + limit - 1)).data as Job[] | null) ?? []);
  } catch (e: any) {
    return NextResponse.json({ ok: false, error: e?.message || "list_failed" }, { status: 500 });
  }

  // showIgnored/showApplied=true：本接口不做隐藏过滤，隐藏交给前端筛选器（保持与 SSR 同口径）。
  const scored = sortAndFilterJobs((data as Job[]) || [], preferences, actions, {
    showIgnored: true,
    showApplied: true,
  });

  return NextResponse.json({ ok: true, jobs: scored, offset, limit, count: (data || []).length });
}

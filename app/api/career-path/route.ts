import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { companyMatches, findCompanyProfile } from "@/lib/insight-match";
import { ITEM_COLUMNS, groupGatedInsights } from "@/lib/insight-bundle";
import { buildCareerPath, type CareerCompanyInput } from "@/lib/career-path";
import type { CompanyProfile } from "@/lib/types";

export const runtime = "nodejs";

const FALLBACK_LIMIT = 8;

// ③ 个性化职业路径：确定性引擎。锚定用户目标公司 + 画像 + 洞察层 + jobs 在招计数。
export async function GET() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  // 1) 画像 + 偏好
  const [{ data: profile }, { data: prefs }, { data: profiles, error: profileErr }] =
    await Promise.all([
      supabase.from("candidate_profiles").select("*").eq("user_id", user.id).maybeSingle(),
      supabase.from("user_preferences").select("*").eq("user_id", user.id).maybeSingle(),
      supabase.from("company_profiles").select("*"),
    ]);
  if (profileErr) {
    console.error("[career-path] 读取 company_profiles 失败", profileErr.message);
    return NextResponse.json({ ok: false, error: profileErr.message }, { status: 500 });
  }
  const allProfiles = (profiles || []) as CompanyProfile[];

  // 2) 目标公司 → 匹配画像；为空则 fallback 推荐全部种子（引擎按窗口期排序后截断）
  const targetCompanies: string[] = (prefs?.target_companies || []).filter(Boolean);
  const matchedMap = new Map<string, CompanyProfile>();
  for (const name of targetCompanies) {
    const p = findCompanyProfile(allProfiles, name);
    if (p) matchedMap.set(p.id, p);
  }
  const isFallback = matchedMap.size === 0;
  const chosen = isFallback ? allProfiles : Array.from(matchedMap.values());

  if (chosen.length === 0) {
    const report = buildCareerPath(profile, [], isFallback, new Date());
    return NextResponse.json({ ok: true, report });
  }

  // 3) 批量取洞察 + jobs 在招计数
  const ids = chosen.map((p) => p.id);
  const [{ data: items, error: itemErr }, { data: jobRows, error: jobErr }] = await Promise.all([
    supabase
      .from("insight_items")
      .select(`${ITEM_COLUMNS}, insight_item_sources(insight_sources(*))`)
      .in("company_id", ids)
      .eq("status", "active"),
    supabase.from("jobs").select("company").eq("status", "active"),
  ]);
  if (itemErr) {
    console.error("[career-path] 读取 insight_items 失败", itemErr.message);
    return NextResponse.json({ ok: false, error: itemErr.message }, { status: 500 });
  }
  if (jobErr) {
    console.error("[career-path] 读取 jobs 失败", jobErr.message);
    return NextResponse.json({ ok: false, error: jobErr.message }, { status: 500 });
  }

  const byCompany = new Map<string, any[]>();
  for (const it of (items || []) as any[]) {
    const arr = byCompany.get(it.company_id) || [];
    arr.push(it);
    byCompany.set(it.company_id, arr);
  }

  const now = new Date();
  const companies: CareerCompanyInput[] = chosen.map((p) => {
    const { dimensions } = groupGatedInsights(byCompany.get(p.id) || [], now);
    const job_count = (jobRows || []).filter((j: any) => companyMatches(p, j.company)).length;
    return { company: p.company, display_name: p.display_name, job_count, dimensions };
  });

  const report = buildCareerPath(profile, companies, isFallback, now);
  if (isFallback) {
    report.recommendations = report.recommendations.slice(0, FALLBACK_LIMIT);
  }

  return NextResponse.json({ ok: true, report });
}

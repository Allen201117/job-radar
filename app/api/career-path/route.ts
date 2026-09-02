import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { verifyRequestClaims } from "@/lib/auth-claims";
import { companyMatches, findCompanyProfile } from "@/lib/insight-match";
import { ITEM_COLUMNS, groupGatedInsights } from "@/lib/insight-bundle";
import { buildCareerPath, type CareerCompanyInput } from "@/lib/career-path";
import { getCachedCompanyProfilesLight, getCachedActiveJobCounts } from "@/lib/insight-availability-cache";
import type { CompanyProfile } from "@/lib/types";

export const runtime = "nodejs";

const FALLBACK_LIMIT = 8;

// ③ 个性化职业路径：确定性引擎。锚定用户目标公司 + 画像 + 洞察层 + jobs 在招计数。
export async function GET() {
  const supabase = await createServerSupabase();
  const user = await verifyRequestClaims(supabase);
  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  // 1) 画像 + 偏好 + company_profiles 轻列（走跨实例缓存，避免每请求整表读 1152+ 行）
  const [[{ data: profile }, { data: prefs }], allProfilesLight] = await Promise.all([
    Promise.all([
      supabase.from("candidate_profiles").select("*").eq("user_id", user.id).maybeSingle(),
      supabase.from("user_preferences").select("*").eq("user_id", user.id).maybeSingle(),
    ]),
    getCachedCompanyProfilesLight().catch((err: any) => {
      console.error("[career-path] 读取 company_profiles 失败", err?.message);
      return [] as CompanyProfile[];
    }),
  ]);
  const allProfiles = allProfilesLight as CompanyProfile[];

  // 2) 目标公司 → 匹配画像；为空则 fallback 推荐全部种子（引擎按窗口期排序后截断）
  const targetCompanies: string[] = (prefs?.target_companies || []).filter(Boolean);

  // 新用户：未上传简历画像 + 未设目标公司 → 不跑「全量种子公司窗口期 fallback」
  // （对全部公司做 .in 查询易 400，且对没画像的用户意义不大）。直接返回友好的「去上传简历」态，
  // 前端据 has_profile=false / failure_reason=no_profile 展示上传引导，而不是报错。
  const hasProfileContent = Boolean(
    profile &&
      ((profile.target_roles || []).filter(Boolean).length ||
        profile.seniority ||
        (profile.target_locations || []).filter(Boolean).length),
  );
  if (!hasProfileContent && targetCompanies.length === 0) {
    return NextResponse.json({
      ok: true,
      report: buildCareerPath(profile, [], false, new Date()),
    });
  }

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
  // 在招计数走跨实例缓存（同 availability 接口）；insight_items 按 ids 精确过滤。
  const [{ data: items, error: itemErr }, rawCounts] = await Promise.all([
    supabase
      .from("insight_items")
      .select(`${ITEM_COLUMNS}, insight_item_sources(insight_sources(*))`)
      .in("company_id", ids)
      .eq("status", "active"),
    getCachedActiveJobCounts().catch(() => [] as Array<{ company: string; job_count: number }>),
  ]);
  const companyCounts = rawCounts;
  const countErr = null; // getCachedActiveJobCounts 内部已记录错误并降级为空数组
  if (itemErr) {
    // 洞察条目读取失败（如批量 .in 过大或瞬时错误）→ 降级为「无洞察条目」而非整页报错；
    // 时机/在招计数仍可用，至少给出窗口期推荐。items 为 null 时下方 (items || []) 自然成空。
    console.error("[career-path] 读取 insight_items 失败（降级为无条目）", itemErr.message);
  }
  const counts = (companyCounts || []) as Array<{ company: string; job_count: number }>;

  const byCompany = new Map<string, any[]>();
  for (const it of (items || []) as any[]) {
    const arr = byCompany.get(it.company_id) || [];
    arr.push(it);
    byCompany.set(it.company_id, arr);
  }

  const now = new Date();
  const companies: CareerCompanyInput[] = chosen.map((p) => {
    const { dimensions } = groupGatedInsights(byCompany.get(p.id) || [], now);
    // 按 company 分组求和（命中 companyMatches 的公司计数累加）== 改造前「逐行 filter 计数」。
    const job_count = counts
      .filter((row) => companyMatches(p, row.company))
      .reduce((sum, row) => sum + (row.job_count || 0), 0);
    return { company: p.company, display_name: p.display_name, job_count, dimensions };
  });

  const report = buildCareerPath(profile, companies, isFallback, now);
  if (isFallback) {
    report.recommendations = report.recommendations.slice(0, FALLBACK_LIMIT);
  }

  return NextResponse.json({ ok: true, report });
}

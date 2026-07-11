import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { activeJobCountsByCompany, jobsStoreEnabled } from "@/lib/jobs-store/read";
import { companyMatches, findCompanyProfile } from "@/lib/insight-match";
import { ITEM_COLUMNS, INSIGHT_DIMENSIONS, groupGatedInsights } from "@/lib/insight-bundle";
import type { CompanyProfile } from "@/lib/types";

export const runtime = "nodejs";

// 批量返回每家公司的「洞察可用性」（按钮点击前预告）：
//   real    = 过门后的实录洞察条数（与抽屉同口径 groupGatedInsights）。
//   derived = 是否有「岗位聚合」派生洞察。lib/insight-derive 的 deriveHiring 在 active 岗位数 >= 3 时
//             必产出，故用 active 岗位数 >= 3 作为派生可用性阈值（与派生层同口径）。
// 成本与公司数无关：一次取 公司画像(小表) + 全部 active 洞察行(仅 ~5% 公司有) + 各公司 active 岗位计数(RPC)。
const DERIVED_MIN_ACTIVE = 3;

export async function GET(request: NextRequest) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  const raw = (request.nextUrl.searchParams.get("companies") || "").trim();
  const companies = Array.from(
    new Set(raw.split("|").map((c) => c.trim()).filter(Boolean)),
  ).slice(0, 80);
  if (companies.length === 0) {
    return NextResponse.json({ ok: true, availability: {} });
  }

  const countsPromise = jobsStoreEnabled()
    ? activeJobCountsByCompany()
        .then((data) => ({ data, error: null as any }))
        .catch((error) => ({ data: null, error }))
    : supabase.rpc("active_job_counts_by_company");
  const [{ data: profiles }, { data: items }, { data: companyCounts, error: countErr }] = await Promise.all([
    supabase.from("company_profiles").select("*"),
    supabase
      .from("insight_items")
      .select(`${ITEM_COLUMNS}, insight_item_sources(insight_sources(*))`)
      .eq("status", "active"),
    countsPromise,
  ]);

  if (countErr) {
    console.error("[insights/availability] 读取在招计数失败（降级为无派生洞察）", countErr.message);
  }
  const counts = (countErr ? [] : companyCounts || []) as Array<{ company: string; job_count: number }>;

  const allProfiles = (profiles || []) as CompanyProfile[];
  const itemsByProfile = new Map<string, any[]>();
  for (const it of (items || []) as any[]) {
    const arr = itemsByProfile.get(it.company_id) || [];
    arr.push(it);
    itemsByProfile.set(it.company_id, arr);
  }
  const countByCompany = new Map<string, number>();
  for (const row of counts) {
    countByCompany.set(row.company, row.job_count || 0);
  }

  const now = new Date();
  const availability: Record<string, { real: number; derived: boolean }> = {};
  for (const company of companies) {
    const profile = findCompanyProfile(allProfiles, company);
    let real = 0;
    if (profile) {
      const { dimensions } = groupGatedInsights(itemsByProfile.get(profile.id) || [], now);
      real = INSIGHT_DIMENSIONS.reduce((n, d) => n + dimensions[d].length, 0);
    }
    const activeCount = profile
      ? counts
          .filter((row) => companyMatches(profile, row.company))
          .reduce((sum, row) => sum + (row.job_count || 0), 0)
      : countByCompany.get(company) || 0;
    availability[company] = { real, derived: activeCount >= DERIVED_MIN_ACTIVE };
  }

  return NextResponse.json({ ok: true, availability });
}

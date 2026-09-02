import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { verifyRequestClaims } from "@/lib/auth-claims";
import { companyMatches, findCompanyProfile } from "@/lib/insight-match";
import { ITEM_COLUMNS, INSIGHT_DIMENSIONS, groupGatedInsights } from "@/lib/insight-bundle";
import { fetchAllPages } from "@/lib/supabase-paginate";
import { getCachedCompanyProfilesLight, getCachedActiveJobCounts } from "@/lib/insight-availability-cache";
import type { CompanyProfile } from "@/lib/types";

export const runtime = "nodejs";

// 批量返回每家公司的「洞察可用性」（按钮点击前预告）：
//   real    = 过门后的实录洞察条数（与抽屉同口径 groupGatedInsights）。
//   derived = 是否有「岗位聚合」派生洞察。lib/insight-derive 的 deriveHiring 在 active 岗位数 >= 3 时
//             必产出，故用 active 岗位数 >= 3 作为派生可用性阈值（与派生层同口径）。
// 成本：company_profiles 轻列 + active 岗位计数走跨实例缓存（10min）；
//       insight_items 按请求里的 company ids 精确过滤，不整表拉。
const DERIVED_MIN_ACTIVE = 3;

export async function GET(request: NextRequest) {
  const supabase = await createServerSupabase();
  const user = await verifyRequestClaims(supabase);
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

  // company_profiles 轻列 + 在招计数走跨实例缓存（两者对所有用户相同）
  const EMPTY_PROFILES: CompanyProfile[] = [];
  const EMPTY_COUNTS: Array<{ company: string; job_count: number }> = [];
  const [allProfilesLight, counts] = await Promise.all([
    getCachedCompanyProfilesLight().catch(() => EMPTY_PROFILES),
    getCachedActiveJobCounts().catch(() => EMPTY_COUNTS),
  ]);
  const allProfiles = allProfilesLight as CompanyProfile[];

  // 先从请求的 companies 匹配出有画像的 profile id 列表，再精确过滤 insight_items
  const profileIds: string[] = [];
  for (const company of companies) {
    const p = findCompanyProfile(allProfiles, company);
    if (p) profileIds.push(p.id);
  }

  // 仅当有匹配到画像时才查询 insight_items，按 company_id in(ids) 精确过滤
  const itemsByProfile = new Map<string, any[]>();
  if (profileIds.length > 0) {
    const items = await fetchAllPages<any>(
      (from, to) =>
        supabase
          .from("insight_items")
          .select(`${ITEM_COLUMNS}, insight_item_sources(insight_sources(*))`)
          .in("company_id", profileIds)
          .eq("status", "active")
          .order("id", { ascending: true })
          .range(from, to),
    ).catch(() => []);
    for (const it of items) {
      const arr = itemsByProfile.get(it.company_id) || [];
      arr.push(it);
      itemsByProfile.set(it.company_id, arr);
    }
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

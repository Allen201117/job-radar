import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { verifyRequestClaims } from "@/lib/auth-claims";
import { companyGroupBrandSuffix } from "@/lib/company-normalize";

export const runtime = "nodejs";

// 批量返回每家公司的 logo（data URI）或「无」。前端 lib/logo-client 微批调用。
// data = base64 data URI（后端抓取时已内联），前端直接 <img src>；status='not_found' 时前端首字母兜底。
// 按 company_key（lower(trim(company))）匹配，与抓取脚本 / 前端同口径。
export async function GET(request: NextRequest) {
  const supabase = await createServerSupabase();
  const user = await verifyRequestClaims(supabase);
  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  const raw = (request.nextUrl.searchParams.get("companies") || "").trim();
  const companies = Array.from(
    new Set(raw.split("|").map((c) => c.trim()).filter(Boolean)),
  ).slice(0, 100);
  if (companies.length === 0) {
    return NextResponse.json({ ok: true, logos: {} });
  }

  // 每个调用方公司最多展开出「完整名 + 集团短名」两个 key；100 的上限仍只限制调用方公司数。
  const keys = Array.from(new Set(companies.flatMap((company) => {
    const fullKey = company.trim().toLowerCase();
    const brand = companyGroupBrandSuffix(company);
    return brand ? [fullKey, brand.toLowerCase()] : [fullKey];
  })));
  const { data, error } = await supabase
    .from("company_logos")
    .select("company_key, logo_data, status")
    .in("company_key", keys);

  if (error) {
    console.error("[company-logos] 查询失败", error.message);
    // 降级为「全部无 logo」（前端首字母兜底），不 500 阻断看板
    const logos: Record<string, { data: string | null; status: string }> = {};
    for (const company of companies) logos[company] = { data: null, status: "not_found" };
    return NextResponse.json({ ok: false, logos, error: error.message });
  }

  const byKey = new Map<string, { data: string | null; status: string }>();
  for (const row of (data || []) as Array<{ company_key: string; logo_data: string | null; status: string }>) {
    byKey.set(row.company_key, { data: row.logo_data ?? null, status: row.status });
  }

  const logos: Record<string, { data: string | null; status: string }> = {};
  for (const company of companies) {
    const fullHit = byKey.get(company.trim().toLowerCase());
    const brand = companyGroupBrandSuffix(company);
    const brandHit = brand ? byKey.get(brand.toLowerCase()) : undefined;
    const hit = fullHit?.status === "found" ? fullHit : brandHit;
    logos[company] = hit ? { data: hit.data, status: hit.status } : { data: null, status: "not_found" };
  }

  return NextResponse.json({ ok: true, logos });
}

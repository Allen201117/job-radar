import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";

export const runtime = "nodejs";

// 批量返回每家公司的 logo（data URI）或「无」。前端 lib/logo-client 微批调用。
// data = base64 data URI（后端抓取时已内联），前端直接 <img src>；status='not_found' 时前端首字母兜底。
// 按 company_key（lower(trim(company))）匹配，与抓取脚本 / 前端同口径。
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
  ).slice(0, 100);
  if (companies.length === 0) {
    return NextResponse.json({ ok: true, logos: {} });
  }

  const keys = Array.from(new Set(companies.map((c) => c.trim().toLowerCase())));
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
    const hit = byKey.get(company.trim().toLowerCase());
    logos[company] = hit ? { data: hit.data, status: hit.status } : { data: null, status: "not_found" };
  }

  return NextResponse.json({ ok: true, logos });
}

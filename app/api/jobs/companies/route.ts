import { NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabaseService";
import { jobsStoreEnabled, activeCompanies } from "@/lib/jobs-store/read";

export const dynamic = "force-dynamic";

// 「有活跃岗位的公司」全量去重列表，供岗位库筛选器的公司下拉(datalist)使用。
// 服务端筛选后公司项不能再从浏览器已加载岗位派生（会只剩几家）——这里一次取全 ~500+ 家。
// 进程内缓存：RPC 全量结果缓存 10 分钟；兜底(不全)只缓存 30 秒，让其尽快重试 RPC 拿全量。
let cache: { until: number; companies: string[] } | null = null;
const TTL_FULL_MS = 10 * 60 * 1000;
const TTL_FALLBACK_MS = 30 * 1000;

export async function GET() {
  if (cache && Date.now() < cache.until) {
    return NextResponse.json({ ok: true, companies: cache.companies, cached: true });
  }

  // jobs 已迁自建香港 PG：配了 env 走 jobs-store 的 active_companies()；异常落到下面 Supabase 兜底。
  if (jobsStoreEnabled()) {
    try {
      const companies = await activeCompanies();
      cache = { until: Date.now() + TTL_FULL_MS, companies };
      return NextResponse.json({ ok: true, companies });
    } catch {
      /* 香港库异常 → 走 Supabase 兜底 */
    }
  }

  // jobs 公开可读；用 service-role 绕 anon 角色的 statement_timeout。
  const supabase = createServiceClient();

  // 首选 active_companies() RPC（迁移 138，单次 group by，最全）。
  // 注意：迁移刚应用时 PostgREST schema 缓存可能尚未收录该函数 → rpc 报错，走兜底，几十秒后自愈。
  let companies: string[] | null = null;
  let fromRpc = false;
  const rpc = await supabase.rpc("active_companies");
  if (!rpc.error && Array.isArray(rpc.data)) {
    companies = (rpc.data as Array<{ company: string }>).map((r) => r.company).filter(Boolean);
    fromRpc = true;
  } else {
    // 兜底（RPC 未就绪）：扫全库 company 列（仅一列，轻量）去重，仍给出尽量完整的列表。
    const seen = new Set<string>();
    for (let off = 0; off < 110000; off += 1000) {
      const { data, error } = await supabase
        .from("jobs")
        .select("company")
        .eq("status", "active")
        .order("first_seen_at", { ascending: false })
        .range(off, off + 999);
      if (error || !data || data.length === 0) break;
      for (const r of data as Array<{ company: string }>) {
        if (r.company) seen.add(r.company);
      }
      if (data.length < 1000) break;
    }
    companies = Array.from(seen).sort((a, b) => a.localeCompare(b, "zh"));
  }

  cache = {
    until: Date.now() + (fromRpc ? TTL_FULL_MS : TTL_FALLBACK_MS),
    companies: companies || [],
  };
  return NextResponse.json({ ok: true, companies: cache.companies });
}

import { NextResponse } from "next/server";
import { createServiceClient } from "@/lib/supabaseService";

export const dynamic = "force-dynamic";

// 「有活跃岗位的公司」全量去重列表，供岗位库筛选器的公司下拉(datalist)使用。
// 服务端筛选后公司项不能再从浏览器已加载岗位派生（会只剩几家）——这里一次取全 ~500+ 家。
// 进程内缓存 10 分钟（低频、对所有用户相同），避免每次进页都全表聚合。
let cache: { at: number; companies: string[] } | null = null;
const TTL_MS = 10 * 60 * 1000;

export async function GET() {
  if (cache && Date.now() - cache.at < TTL_MS) {
    return NextResponse.json({ ok: true, companies: cache.companies, cached: true });
  }

  // jobs 公开可读；用 service-role 绕 anon 角色的 statement_timeout（未建索引时全表聚合/排序会超时）。
  const supabase = createServiceClient();

  // 首选 active_companies() RPC（迁移 138，单次 group by，最全最快）。
  let companies: string[] | null = null;
  const rpc = await supabase.rpc("active_companies");
  if (!rpc.error && Array.isArray(rpc.data)) {
    companies = (rpc.data as Array<{ company: string }>)
      .map((r) => r.company)
      .filter(Boolean);
  } else {
    // 兜底（RPC 未就绪时，如本地未应用迁移）：取最近窗口的 company 列去重。
    const seen = new Set<string>();
    for (let off = 0; off < 12000; off += 1000) {
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

  cache = { at: Date.now(), companies: companies || [] };
  return NextResponse.json({ ok: true, companies: cache.companies });
}

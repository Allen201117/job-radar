import { createServiceClient } from "@/lib/supabaseService";
import { buildExactProfileIndex, companyOwnsName } from "@/lib/insight-match";
import { fetchAllPages } from "@/lib/supabase-paginate";
import type { RecruitmentObservation } from "@/lib/recruitment-cycle";
import type { CompanyProfile } from "@/lib/types";

type CycleRow = RecruitmentObservation & { company_id: string };
type ProfileNames = Pick<CompanyProfile, "id" | "company" | "aliases">;

/**
 * 清单公司 → 它名下的观测（key=pattern）。纯函数，归属走「精确优先」。
 *
 * ❌ 改前拿清单名逐个去比「有观测的画像」，不看别的画像：「京东科技」自己有画像（名下只有没核实的草稿），
 *    照样被画像「京东」放行，校招专区的京东科技卡上挂的是京东的 2 条时间线（2026-10-11 全集回放，311 家里唯一一家）。
 * ✅ 所以必须拿**全部**画像建精确索引，不能只看有观测的那几十个——挡住京东的正是那个没有观测的京东科技画像。
 */
export function matchCyclesToCompanies(
  list: Array<{ name: string; pattern: string }>,
  rows: CycleRow[],
  profiles: ProfileNames[],
): Map<string, RecruitmentObservation[]> {
  const out = new Map<string, RecruitmentObservation[]>();
  const exactIndex = buildExactProfileIndex(profiles);
  const withRows = new Set(rows.map((row) => row.company_id));
  const candidates = profiles.filter((p) => withRows.has(p.id));
  for (const c of list) {
    const owners = new Set(
      candidates.filter((p) => companyOwnsName(p, c.name, exactIndex)).map((p) => p.id),
    );
    if (!owners.size) continue;
    out.set(c.pattern, rows.filter((row) => owners.has(row.company_id)));
  }
  return out;
}

// 读全部 verified 且未过期的招聘周期观测，按公司归一匹配到必投清单公司（key=pattern）。
export async function getRecruitmentCyclesForCompanies(
  list: Array<{ name: string; pattern: string }>,
): Promise<Map<string, RecruitmentObservation[]>> {
  const service = createServiceClient();
  const today = new Date().toISOString().slice(0, 10);
  const [cycles, profiles] = await Promise.all([
    service
      .from("recruitment_cycle_observations")
      .select(
        "company_id, grad_class, season, batch, event, time_expr_type, value_text, month_start, month_end, confidence, evidence_url, evidence_excerpt, verify_status, valid_until",
      )
      .eq("verify_status", "verified")
      .or(`valid_until.is.null,valid_until.gte.${today}`),
    // 画像已过 1000 行：不分页会被 PostgREST 静默截断，挡不住的那一段正好没有任何报错。
    fetchAllPages<ProfileNames>((from, to) =>
      service.from("company_profiles").select("id, company, aliases").order("id", { ascending: true }).range(from, to),
    ).catch((error: Error) => {
      console.error("[campus-cycles] 读取画像失败", error.message);
      return null;
    }),
  ]);
  if (cycles.error) {
    console.error("[campus-cycles] 读取失败", cycles.error.message);
    return new Map();
  }
  // 画像读不到就整体不给时间线：没有精确索引时退回逐个比，等于把别家的时间线挂上来。
  if (!profiles) return new Map();
  return matchCyclesToCompanies(list, (cycles.data || []) as unknown as CycleRow[], profiles);
}

import { createServiceClient } from "@/lib/supabaseService";
import { companyMatches } from "@/lib/insight-match";
import type { RecruitmentObservation } from "@/lib/recruitment-cycle";

// 读全部 verified 且未过期的招聘周期观测，按公司归一匹配到必投清单公司（key=pattern）。
export async function getRecruitmentCyclesForCompanies(
  list: Array<{ name: string; pattern: string }>,
): Promise<Map<string, RecruitmentObservation[]>> {
  const out = new Map<string, RecruitmentObservation[]>();
  const service = createServiceClient();
  const today = new Date().toISOString().slice(0, 10);
  const { data, error } = await service
    .from("recruitment_cycle_observations")
    .select(
      "grad_class, season, batch, event, time_expr_type, value_text, month_start, month_end, confidence, evidence_url, evidence_excerpt, verify_status, valid_until, company_profiles!inner(company, aliases)",
    )
    .eq("verify_status", "verified")
    .or(`valid_until.is.null,valid_until.gte.${today}`);
  if (error) {
    console.error("[campus-cycles] 读取失败", error.message);
    return out;
  }
  for (const c of list) {
    const matched = (data || []).filter((row: any) =>
      companyMatches(
        { company: row.company_profiles?.company || "", aliases: row.company_profiles?.aliases || [] },
        c.name,
      ),
    );
    if (matched.length > 0) out.set(c.pattern, matched as RecruitmentObservation[]);
  }
  return out;
}

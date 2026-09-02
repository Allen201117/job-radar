import "server-only";
import type { SupabaseClient } from "@supabase/supabase-js";
import { resolveMustApplyIndustries, MUST_APPLY_BY_INDUSTRY } from "@/lib/must-apply-list";

/**
 * 读用户行业：candidate_profiles（简历解析）优先，回退 user_preferences（手填偏好）。
 * 走传入的 RLS 客户端（只读用户自己的行），不用 service-role——这不是 admin 场景。
 *
 * 抽出来共用是为了让 `/campus` 页面与 `/api/campus-zone/jobs` 解析出**同一批公司**：
 * 展开区取的岗位必须落在卡面计数所依据的那份清单里，两边各写一遍迟早漂。
 */
export async function getUserCampusScope(
  supabase: SupabaseClient,
  userId: string,
): Promise<{ rawIndustries: string[]; industries: string[]; companies: Array<{ name: string; pattern: string }> }> {
  const [profRes, prefRes] = await Promise.all([
    supabase.from("candidate_profiles").select("target_industries").eq("user_id", userId).maybeSingle(),
    supabase.from("user_preferences").select("target_industries").eq("user_id", userId).maybeSingle(),
  ]);
  const rawIndustries =
    (profRes.data?.target_industries as string[] | null) ||
    (prefRes.data?.target_industries as string[] | null) ||
    [];
  const industries = resolveMustApplyIndustries(rawIndustries); // 空/归一不出 → 兜底「互联网/科技」
  return { rawIndustries, industries, companies: companiesForIndustries(industries) };
}

/** 必投清单公司：按行业取并跨行业按 pattern 去重（同一公司可能出现在多个行业清单里）。 */
export function companiesForIndustries(industries: string[]): Array<{ name: string; pattern: string }> {
  return Array.from(
    new Map(
      industries.flatMap((ind) => MUST_APPLY_BY_INDUSTRY[ind] || []).map((c) => [c.pattern, c] as const),
    ).values(),
  );
}

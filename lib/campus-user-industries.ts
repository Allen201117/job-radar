import "server-only";
import type { SupabaseClient } from "@supabase/supabase-js";
import { resolveMustApplyIndustries, MUST_APPLY_BY_INDUSTRY } from "@/lib/must-apply-list";

/**
 * 读用户的必投范围（行业 → 公司清单）与方向（目标岗位 / 城市）。
 * 行业实际只来自 user_preferences（原因见函数体内注释，live 已核实列不存在）。
 * 走传入的 RLS 客户端（只读用户自己的行），不用 service-role——这不是 admin 场景。
 *
 * 抽出来共用是为了让 `/campus` 页面与 `/api/campus-zone/jobs` 解析出**同一批公司**：
 * 展开区取的岗位必须落在卡面计数所依据的那份清单里，两边各写一遍迟早漂。
 */
export async function getUserCampusScope(
  supabase: SupabaseClient,
  userId: string,
): Promise<{
  rawIndustries: string[];
  industries: string[];
  companies: Array<{ name: string; pattern: string }>;
  /** 目标岗位（原始短语，未归一）：供「对你有货」判用户方向，见 app/campus/page.tsx。 */
  targetRoles: string[];
  /** 目标城市（原始写法）：同上。 */
  targetLocations: string[];
}> {
  const [profRes, prefRes] = await Promise.all([
    supabase.from("candidate_profiles").select("target_roles, target_locations").eq("user_id", userId).maybeSingle(),
    supabase
      .from("user_preferences")
      .select("target_industries, target_roles, target_locations")
      .eq("user_id", userId)
      .maybeSingle(),
  ]);
  // ⚠️ 行业**只读 user_preferences.target_industries**。原代码还从 candidate_profiles 选
  // `target_industries` 并置于更高优先级，但该表根本没有这一列（迁移 006 里叫 `industries`）——
  // PostgREST 整条 select 报错、data 恒为 null，所以「简历优先」这一档**从来没生效过**，
  // 实际一直是偏好单读。这里如实写成偏好单读（行为逐字不变），要不要真的接上简历那一档
  // 属于「必投清单口径」决策，不在本次改动范围内。
  const rawIndustries = (prefRes.data?.target_industries as string[] | null) || [];
  const industries = resolveMustApplyIndustries(rawIndustries); // 空/归一不出 → 兜底「互联网/科技」
  // ⚠️ 行业是「简历优先」（上面几行），而**岗位/城市是偏好优先**——这不是笔误，是跟
  // lib/opportunities/profile.buildRadarProfile 对齐：用户在偏好里手填的方向表达的是「我现在想投什么」，
  // 优先级高于简历解析出来的历史方向。两处口径若分家，/campus 的「对口」与 /today 的推荐会各说各话。
  const pick = (a: unknown, b: unknown): string[] => {
    const first = Array.isArray(a) ? a.filter((x): x is string => typeof x === "string" && !!x.trim()) : [];
    if (first.length) return first;
    return Array.isArray(b) ? b.filter((x): x is string => typeof x === "string" && !!x.trim()) : [];
  };
  return {
    rawIndustries,
    industries,
    companies: companiesForIndustries(industries),
    targetRoles: pick(prefRes.data?.target_roles, profRes.data?.target_roles),
    targetLocations: pick(prefRes.data?.target_locations, profRes.data?.target_locations),
  };
}

/** 必投清单公司：按行业取并跨行业按 pattern 去重（同一公司可能出现在多个行业清单里）。 */
export function companiesForIndustries(industries: string[]): Array<{ name: string; pattern: string }> {
  return Array.from(
    new Map(
      industries.flatMap((ind) => MUST_APPLY_BY_INDUSTRY[ind] || []).map((c) => [c.pattern, c] as const),
    ).values(),
  );
}

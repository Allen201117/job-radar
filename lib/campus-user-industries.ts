import "server-only";
import type { SupabaseClient } from "@supabase/supabase-js";
import { resolveMustApplyIndustries, MUST_APPLY_BY_INDUSTRY } from "@/lib/must-apply-list";

export type CampusIndustrySource = "preference" | "resume" | "default";

/**
 * 读用户的必投范围（行业 → 公司清单）与方向（目标岗位 / 城市）。
 * 行业 / 岗位 / 城市三者同一口径：**偏好（手填）优先，简历解析兜底**（见函数体内注释）。
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
  /** 行业从哪来：偏好手填 / 简历兜底 / 两边都空走默认。页面据此写清来源与「去哪改」。 */
  industrySource: CampusIndustrySource;
  companies: Array<{ name: string; pattern: string }>;
  /** 目标岗位（原始短语，未归一）：供「对你有货」判用户方向，见 app/campus/page.tsx。 */
  targetRoles: string[];
  /** 目标城市（原始写法）：同上。 */
  targetLocations: string[];
}> {
  const [profRes, prefRes] = await Promise.all([
    supabase
      .from("candidate_profiles")
      .select("industries, target_roles, target_locations")
      .eq("user_id", userId)
      .maybeSingle(),
    supabase
      .from("user_preferences")
      .select("target_industries, target_roles, target_locations")
      .eq("user_id", userId)
      .maybeSingle(),
  ]);
  // 三个维度都是「偏好优先、简历兜底」，与 lib/opportunities/profile.buildRadarProfile 对齐：用户在偏好里
  // 手填的表达的是「我现在想投什么」，优先级高于简历解析出来的历史方向；两处口径若分家，/campus 的「对口」
  // 与 /today 的推荐会各说各话。
  // ⚠️ 简历那一档的列名是 `candidate_profiles.industries`（迁移 006），**不是** `target_industries`。
  // 3a0fa0f~b7ff590 期间选的是不存在的列 → PostgREST 整条 select 报错、data 恒为 null，简历档从未生效。
  // 2026-09-17 创始人拍板接上；live 量过影响面：7 个「偏好为空、简历有行业」的用户从兜底「互联网/科技」
  // 换成简历行业，偏好已填的用户一个都不变（偏好优先，简历只兜底）。
  const pick = (a: unknown, b: unknown): string[] => {
    const first = Array.isArray(a) ? a.filter((x): x is string => typeof x === "string" && !!x.trim()) : [];
    if (first.length) return first;
    return Array.isArray(b) ? b.filter((x): x is string => typeof x === "string" && !!x.trim()) : [];
  };
  const prefIndustries = pick(prefRes.data?.target_industries, null);
  const rawIndustries = prefIndustries.length ? prefIndustries : pick(profRes.data?.industries, null);
  const industries = resolveMustApplyIndustries(rawIndustries); // 空/归一不出 → 兜底「互联网/科技」
  const industrySource: CampusIndustrySource = prefIndustries.length
    ? "preference"
    : rawIndustries.length
      ? "resume"
      : "default";
  return {
    rawIndustries,
    industries,
    industrySource,
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

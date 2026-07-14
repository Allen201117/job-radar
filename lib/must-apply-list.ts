// 北极星指标清单：管理员看板与爬虫探活共用的「必投清单健康覆盖」口径来源。
// 每个行业保留 30 家目标公司；用户自由文本行业先归一，再按行业取对应清单。
// ⚠️ 改这份清单 = 改北极星口径，指标会跳变；调整请在 commit message 里写明原因。
import mustApplyByIndustry from "./must-apply-list.json";
import { canonicalizeUserIndustry } from "./company-industry";

export interface MustApplyCompany {
  name: string;
  pattern: string;
}

export type MustApplyListByIndustry = Record<string, MustApplyCompany[]>;

export const MUST_APPLY_BY_INDUSTRY = mustApplyByIndustry as MustApplyListByIndustry;
export const MUST_APPLY_INDUSTRIES = Object.keys(MUST_APPLY_BY_INDUSTRY);
export const DEFAULT_MUST_APPLY_INDUSTRY = "互联网/科技";
export const MUST_APPLY_LIST = MUST_APPLY_BY_INDUSTRY[DEFAULT_MUST_APPLY_INDUSTRY];

export function mustApplyUnion(): MustApplyCompany[] {
  const seen = new Set<string>();
  return MUST_APPLY_INDUSTRIES.flatMap((industry) => MUST_APPLY_BY_INDUSTRY[industry]).filter((company) => {
    if (seen.has(company.pattern)) return false;
    seen.add(company.pattern);
    return true;
  });
}

export function industriesForPattern(pattern: string): string[] {
  return MUST_APPLY_INDUSTRIES.filter((industry) =>
    MUST_APPLY_BY_INDUSTRY[industry].some((company) => company.pattern === pattern),
  );
}

export function resolveMustApplyIndustries(targetIndustries?: string[] | null): string[] {
  const resolved = Array.from(
    new Set(
      (targetIndustries || [])
        .map((industry) => canonicalizeUserIndustry(industry))
        .filter((industry): industry is string => Boolean(industry && MUST_APPLY_BY_INDUSTRY[industry])),
    ),
  );
  return resolved.length ? resolved : [DEFAULT_MUST_APPLY_INDUSTRY];
}

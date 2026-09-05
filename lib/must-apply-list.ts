// 北极星指标清单：管理员看板与爬虫探活共用的「必投清单健康覆盖」口径来源。
// 每个行业保留 30 家目标公司；用户自由文本行业先归一，再按行业取对应清单。
// ⚠️ 改这份清单 = 改北极星口径，指标会跳变；调整请在 commit message 里写明原因。
import mustApplyDomesticByIndustry from "./must-apply-list.json";
import mustApplyOverseasByIndustry from "./must-apply-list-overseas.json";
import { canonicalizeUserIndustry } from "./company-industry";

export interface MustApplyCompany {
  name: string;
  pattern: string;
  /** 同一家公司在库里的其它写法（ILIKE 模式，与 pattern 同语义）。见 mustApplyPatterns。 */
  aliases?: string[];
  parentPattern?: string;
  brandTokens?: string[];
}

export type MustApplyListByIndustry = Record<string, MustApplyCompany[]>;
export type MustApplyScope = "domestic" | "overseas";

type MustApplyJson = Record<string, unknown>;

function withoutMetadata(raw: MustApplyJson): MustApplyListByIndustry {
  return Object.fromEntries(
    Object.entries(raw).filter(
      ([key, value]) => !key.startsWith("_") && Array.isArray(value),
    ),
  ) as MustApplyListByIndustry;
}

const domesticJson = mustApplyDomesticByIndustry as unknown as MustApplyJson;
const overseasJson = mustApplyOverseasByIndustry as unknown as MustApplyJson;

export const MUST_APPLY_VERSION =
  typeof domesticJson._version === "string" ? domesticJson._version : "unversioned";
export const MUST_APPLY_BY_INDUSTRY = withoutMetadata(domesticJson);
export const MUST_APPLY_OVERSEAS_BY_INDUSTRY = withoutMetadata(overseasJson);
export const MUST_APPLY_INDUSTRIES = Object.keys(MUST_APPLY_BY_INDUSTRY);
export const DEFAULT_MUST_APPLY_INDUSTRY = "互联网/科技";
export const MUST_APPLY_LIST = MUST_APPLY_BY_INDUSTRY[DEFAULT_MUST_APPLY_INDUSTRY];

/**
 * 一家公司**在库里可能用的全部名字模式** = `pattern` + `aliases`（别名）。
 *
 * 为什么要别名：`sources.company` / `jobs.company` 存的是抓取时对方门户自报的名字，
 * 可能是英文（壳牌记成 `Shell`、大陆集团记成 `Continental`），清单存的是中文品牌名。
 * 只按清单名匹配 ⇒「有源有岗却显示 0」⇒ 驱动人去重复补源（2026-09-04 因此插了第二条
 * 壳牌源，与已有源同一个 Workday 站点仅大小写不同，同一个岗在库里存了两行）。
 *
 * ⚠️ 与 `crawler/must_apply.company_patterns()` 是**同一口径**，两端共读 must-apply-list.json；
 * 改这里的语义必须同改 Python 侧，否则台账与北极星会给出两个互相打架的数字。
 */
export function mustApplyPatterns(
  company: Pick<MustApplyCompany, "pattern" | "aliases">,
): string[] {
  const out: string[] = [];
  for (const raw of [company.pattern, ...(company.aliases || [])]) {
    const pattern = typeof raw === "string" ? raw.trim() : "";
    if (pattern && !out.includes(pattern)) out.push(pattern);
  }
  return out;
}

export function mustApplyByIndustry(scope: MustApplyScope): MustApplyListByIndustry {
  return scope === "overseas" ? MUST_APPLY_OVERSEAS_BY_INDUSTRY : MUST_APPLY_BY_INDUSTRY;
}

export function mustApplyUnion(scope: MustApplyScope = "domestic"): MustApplyCompany[] {
  const byIndustry = mustApplyByIndustry(scope);
  const seen = new Set<string>();
  return MUST_APPLY_INDUSTRIES.flatMap((industry) => byIndustry[industry] || []).filter((company) => {
    if (seen.has(company.pattern)) return false;
    seen.add(company.pattern);
    return true;
  });
}

export function industriesForPattern(pattern: string, scope: MustApplyScope = "domestic"): string[] {
  const byIndustry = mustApplyByIndustry(scope);
  return MUST_APPLY_INDUSTRIES.filter((industry) =>
    (byIndustry[industry] || []).some((company) => company.pattern === pattern),
  );
}

export function resolveMustApplyScopes(jobScope?: string | null): MustApplyScope[] {
  if (jobScope === "overseas") return ["overseas"];
  if (jobScope === "all") return ["domestic", "overseas"];
  return ["domestic"];
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

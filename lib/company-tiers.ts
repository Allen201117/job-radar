// 公司类型标签:唯一数据源 lib/company-tiers.json。名字子串匹配 + 中小厂兜底。
// SQL 下推与本文件的 classify 必须语义一致(同 patterns、同大小写不敏感子串)。

import * as fs from "node:fs";
import * as path from "node:path";

type TierEntry = { name: string; pattern: string };

// 使用 fs.readFileSync 确保 transpiler 能处理
const tiersDataStr = fs.readFileSync(path.join(__dirname, "company-tiers.json"), "utf8");
const RAW = JSON.parse(tiersDataStr) as Record<string, unknown>;

// JSON key 顺序即优先级;排除 _meta。
const NAMED_TIERS: string[] = Object.keys(RAW).filter((k) => k !== "_meta");
export const COMPANY_TIER_LABELS: readonly string[] = [...NAMED_TIERS, "中小厂"];

const patternsOf = (tier: string): string[] =>
  ((RAW[tier] as TierEntry[]) || []).map((e) => e.pattern);

// pattern("%字节%") → 核心子串 "字节"(小写)
const core = (pat: string): string => pat.replace(/%/g, "").trim().toLowerCase();

export const NAMED_TIER_PATTERNS: string[] = NAMED_TIERS.flatMap(patternsOf);

export function classifyCompanyTier(company: string): string {
  const name = (company || "").toLowerCase();
  if (name) {
    for (const tier of NAMED_TIERS) {
      for (const pat of patternsOf(tier)) {
        if (name.includes(core(pat))) return tier;
      }
    }
  }
  return "中小厂";
}

export function companyTierPatterns(tiers: string[]): { named: string[]; includeSmb: boolean } {
  const set = new Set(tiers);
  const named: string[] = [];
  for (const tier of NAMED_TIERS) {
    if (set.has(tier)) named.push(...patternsOf(tier));
  }
  return { named, includeSmb: set.has("中小厂") };
}

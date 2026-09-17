// sources.industry 自由写法 → sources.industry_group 归一表。
//
// 唯一数据源是 industry-taxonomy.json（爬虫侧 crawler/industry_taxonomy.py 读同一份文件），
// 两端一致性由 tests/industry-taxonomy-cross-lang.test.js 全量对拍守住（433 条全跑，不抽样）。
// ⚠️ 改映射只改那个 JSON，不要在这里另写一份规则/表——两端各写一份迟早会漂
// （company-industry.js / company_industry.py 就是前车之鉴）。
//
// 设计取舍详见 industry-taxonomy.json 的 `_boundaryNotes`：groups 与
// lib/company-industry.js 的 INDUSTRY_CATEGORIES / lib/must-apply-list.json 的行业键
// 同一空间（11 个），不新造分类体系；mapping 是逐条人工审定的显式表，不是关键词猜测。
import taxonomyJson from "./industry-taxonomy.json";

export interface IndustryTaxonomyJson {
  _version: string;
  groups: string[];
  otherGroup: string;
  mapping: Record<string, string>;
}

const data = taxonomyJson as unknown as IndustryTaxonomyJson;

export const INDUSTRY_TAXONOMY_VERSION = data._version;
/** 11 个行业组，顺序与 lib/company-industry.js 的 INDUSTRY_CATEGORIES 一致。 */
export const INDUSTRY_GROUPS = data.groups;
export const OTHER_INDUSTRY_GROUP = data.otherGroup;
const MAPPING = data.mapping;

/**
 * sources.industry 原始写法 → industry_group；查不到 / 空值一律返回 null。
 *
 * null 的两种成因调用方要分清：
 * 1. raw 本身为空 —— 这个 source 压根没打行业标签；
 * 2. raw 有值但不在 mapping 里 —— 出现了没见过的新写法，需要人工补录 mapping，
 *    不许在这里猜一个关键词规则自动兜底。
 */
export function classifyIndustry(raw: string | null | undefined): string | null {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return MAPPING[trimmed] ?? null;
}

// 服务端岗位搜索。两条路径，匹配/排序最终都复用 lib/job-filter（与前端同一份，口径零变化）：
//
//  ① FTS 路径（有关键词/城市/公司时）：用 search_bigrams（迁移140：中文双字 bigram 的 tsvector + GIN 索引）
//     把候选秒级收窄到「子串命中超集」，再 JS 精筛分层。这是中文 2 字词搜索唯一能「快且全」的办法
//     （pg_trgm 对 2 字中文无效已验证并撤除，见迁移139）。
//  ② 扫描路径（纯浏览，无任何筛选）/ 兜底：按 (status,first_seen_at) 复合索引分批翻最新岗位 + JS 精筛。
//     也用于「迁移窗口/回填未完成」时 FTS 查询异常的降级，保证搜索永不挂。
//
// 历史踩坑：全库塞前端=卡死；全库塞服务端=45s 超时；count(exact)/ilike 全表扫撞 statement_timeout。
import { sortAndFilterJobs } from "@/lib/scoring";
import {
  filterAndRankJobs,
  jobFilterTier,
  type Filters,
  countMatchBreakdown,
  type MatchReason,
} from "@/lib/job-filter";
import type { JobAction, ScoredJob, UserPreferences } from "@/lib/types";
import { effectiveJobScope, jobMatchesScope } from "@/lib/job-scope";
// china-keyword-expansion 为 CommonJS，沿用 hooks 的 import 习惯。
import { cityMatchTokens, ftsCandidateTerms } from "@/lib/china-keyword-expansion";

const DB_PAGE = 1000;
// 扫描路径：逐批增大的并行扫描页数（累计 4/12/28 页）。
const BATCH_SIZES = [4, 8, 16];
const SCAN_BUDGET = 28000;
// FTS 路径：单次最多纳入的命中候选（远超绝大多数关键词的命中量；JS 精筛后分页）。
const FTS_CAP = 8000;

type SupabaseLike = { from: (table: string) => any };

export type SearchResult = {
  jobs: Array<ScoredJob & { __tier: "exact" | "related"; __match: MatchReason }>;
  total: number;
  exactCount: number;
  relatedSameFunction: number;
  relatedMissingInfo: number;
  capped: boolean;
  offset: number;
  limit: number;
};

// 与 SQL search_tokens 同口径：纯拉丁/数字词→整词（英文标题选择性好、不爆）；含 CJK 的词→相邻双字（中文子串）。
function queryTokens(term: string): string[] {
  const out: string[] = [];
  for (const tok of String(term || "").toLowerCase().split(/\s+/)) {
    if (!tok) continue;
    if (/^[a-z0-9]+$/.test(tok)) {
      out.push(tok); // 纯拉丁/数字：整词
      continue;
    }
    if (tok.length === 1) {
      if (/^[㐀-䶿一-鿿]$/.test(tok)) out.push(tok);
      continue;
    }
    for (let i = 0; i < tok.length - 1; i++) {
      const bg = tok.slice(i, i + 2);
      if (/^[a-z0-9㐀-䶿一-鿿]{2}$/.test(bg)) out.push(bg);
    }
  }
  return out;
}

// 一个词 → 「其全部 token 的 AND」子句（命中该词≈其 token 全在文档中）。无有效 token 返回 null。
function termClause(term: string): string | null {
  const toks = queryTokens(term);
  if (!toks.length) return null;
  return `(${toks.join(" & ")})`;
}

// 构造 tsquery：关键词候选词「组内 OR」，再与 城市/公司 等「过滤词 AND」。全空返回 null（→走浏览/扫描）。
// 中文出 bigram、英文出整词，两者选择性都好 → 中英文标题同时命中且快（v2，title 锚定，不再丢英文）。
export function buildTsquery(keywordTerms: string[], andTerms: string[]): string | null {
  const clauses: string[] = [];

  const kwClauses = keywordTerms.map(termClause).filter((c): c is string => !!c);
  if (kwClauses.length) clauses.push(`(${kwClauses.join(" | ")})`);

  for (const t of andTerms) {
    const c = termClause(t);
    if (c) clauses.push(c);
  }

  return clauses.length ? clauses.join(" & ") : null;
}

// 给候选 jobs 行标注 source_adapter（资本来源筛选按来源判国籍用）。jobs 在香港库、sources 在 Supabase，
// 跨库无法 SQL join：调用方（route）查好 source_id→adapter_name 映射传入，这里 in-place 标注。
// 映射缺省（未选资本来源 / 查不到）时原样返回，scoring 的 {...job} 会把该字段透传给 job-filter 消费。
export function annotateSourceAdapter(
  rows: any[],
  adapterBySource?: Map<string, string | null> | null,
): any[] {
  if (!adapterBySource || !rows || !rows.length) return rows || [];
  for (const r of rows) {
    if (r && r.source_id != null) {
      r.source_adapter = adapterBySource.get(r.source_id) ?? null;
    }
  }
  return rows;
}

export function annotateAndRank(
  rows: any[],
  filters: Filters,
  prefs: UserPreferences | null,
  actions: JobAction[],
): Array<ScoredJob & { __tier: "exact" | "related"; __match: MatchReason }> {
  const scored = sortAndFilterJobs(rows, prefs, actions, {
    showIgnored: true,
    showApplied: true,
  }) as ScoredJob[];
  return filterAndRankJobs(scored, filters);
}

function softCityOrFilter(city: string): string | null {
  const tokens = cityMatchTokens(city);
  if (!tokens.length) return null;

  // 与 JS matcher 保持超集：空 location 放行降级；别名/拼音通过 ilike 进候选。
  return [
    "location.is.null",
    "location.eq.",
    ...tokens.map((tok) => `location.ilike.%${tok}%`),
  ].join(",");
}

// FTS 路径：search_bigrams @@ tsquery 收窄候选 → JS 精筛分层 → 分页。
async function searchViaFTS(
  supabase: SupabaseLike,
  filters: Filters,
  prefs: UserPreferences | null,
  actions: JobAction[],
  offset: number,
  limit: number,
  tsquery: string,
  adapterBySource?: Map<string, string | null> | null,
): Promise<SearchResult> {
  const company = filters.company.trim();
  // 关键：**不要 order by**。加 order(id/first_seen) 会让 planner 改走那个索引扫描 + 逐行 @@ 过滤(扫全表，6-8s)；
  // 不排序时 planner 用 GIN bitmap 只取命中行(~1s)。排序交给下面 JS 的 filterAndRankJobs(本就要重排)。
  // 无 SQL 排序 → 分页顺序非严格保证，故用 Map 按 id 去重兜底重叠。
  const byId = new Map<string, any>();
  for (let off = 0; off < FTS_CAP; off += DB_PAGE) {
    let q = supabase
      .from("jobs")
      .select("*")
      .eq("status", "active")
      .textSearch("search_doc", tsquery, { config: "simple" });
    // 精确收紧（在 GIN 命中集上 recheck，便宜）：公司是硬条件；城市是软条件，必须保留空 location。
    const city = filters.city.trim();
    const cityOr = city ? softCityOrFilter(city) : null;
    if (cityOr) q = q.or(cityOr);
    if (company) q = q.ilike("company", `%${company}%`);
    const { data, error } = await q.range(off, off + DB_PAGE - 1);
    if (error) throw new Error(error.message); // 列未就绪/异常 → 调用方降级到扫描路径
    if (!data || data.length === 0) break;
    for (const j of data) {
      if (jobMatchesScope(j, prefs, filters.region)) byId.set(j.id, j);
    }
    if (data.length < DB_PAGE) break;
  }

  const rows = annotateSourceAdapter(Array.from(byId.values()), adapterBySource);
  const ranked = annotateAndRank(rows, filters, prefs, actions);
  const breakdown = countMatchBreakdown(ranked);
  return {
    jobs: ranked.slice(offset, offset + limit),
    total: ranked.length,
    exactCount: breakdown.exact,
    relatedSameFunction: breakdown.relatedSameFunction,
    relatedMissingInfo: breakdown.relatedMissingInfo,
    capped: byId.size >= FTS_CAP,
    offset,
    limit,
  };
}

// 扫描路径：按 (status,first_seen_at) 复合索引分批并行翻最新岗位 + JS 精筛；newest 可早停，match 要看满预算再排序。
async function searchViaScan(
  supabase: SupabaseLike,
  filters: Filters,
  prefs: UserPreferences | null,
  actions: JobAction[],
  offset: number,
  limit: number,
  adapterBySource?: Map<string, string | null> | null,
): Promise<SearchResult> {
  const need = offset + limit;
  const page = (off: number) =>
    supabase
      .from("jobs")
      .select("*")
      .eq("status", "active")
      .order("first_seen_at", { ascending: false })
      .range(off, off + DB_PAGE - 1);

  const matched: ScoredJob[] = [];
  let nextOff = 0;
  let exhausted = false;

  for (const bsize of BATCH_SIZES) {
    if ((filters.sortBy !== "match" && matched.length > need) || exhausted || nextOff >= SCAN_BUDGET) break;
    const offsets: number[] = [];
    for (let k = 0; k < bsize && nextOff < SCAN_BUDGET; k++, nextOff += DB_PAGE) {
      offsets.push(nextOff);
    }
    const res = await Promise.all(offsets.map((o) => page(o)));
    for (const r of res) {
      if (r.error) throw new Error(r.error.message);
      const rawRows: any[] = r.data || [];
      if (rawRows.length === 0) {
        exhausted = true;
        continue;
      }
      const rows: any[] = annotateSourceAdapter(
        rawRows.filter((j: any) => jobMatchesScope(j, prefs, filters.region)),
        adapterBySource,
      );
      const scored = sortAndFilterJobs(rows, prefs, actions, {
        showIgnored: true,
        showApplied: true,
      }) as ScoredJob[];
      for (const j of scored) {
        if (jobFilterTier(j, filters) !== null) matched.push(j);
      }
      if (rawRows.length < DB_PAGE) exhausted = true;
    }
  }

  const ranked = filterAndRankJobs(matched, filters);
  const breakdown = countMatchBreakdown(ranked);
  return {
    jobs: ranked.slice(offset, offset + limit),
    total: ranked.length,
    exactCount: breakdown.exact,
    relatedSameFunction: breakdown.relatedSameFunction,
    relatedMissingInfo: breakdown.relatedMissingInfo,
    capped: !exhausted,
    offset,
    limit,
  };
}

export async function searchJobs(
  supabase: SupabaseLike,
  filters: Filters,
  prefs: UserPreferences | null,
  actions: JobAction[],
  offset: number,
  limit: number,
  adapterBySource?: Map<string, string | null> | null,
): Promise<SearchResult> {
  const keyword = filters.keyword.trim();
  const city = filters.city.trim();
  const company = filters.company.trim();

  // 有关键词/城市/公司 → FTS 路径（快且全召回）；其中关键词用 ftsCandidateTerms 取「精确+同职能」候选词。
  const includeOverseasLexicon = effectiveJobScope(prefs) !== "domestic";
  const keywordTerms = keyword ? ftsCandidateTerms(keyword, { includeOverseasLexicon }) : [];
  // 城市必须留在 tsquery（全表 GIN 命中，保住城市浏览完整覆盖——location 无 trigram 索引，移出会让
  // 无关键词的城市搜索退化到 scan 仅覆盖最新 28k）；空 location / 别名的软放行由 softCityOrFilter 精修。
  const andTerms = [city, company].filter(Boolean);
  const tsquery = buildTsquery(keywordTerms, andTerms);

  if (tsquery) {
    try {
      return await searchViaFTS(supabase, filters, prefs, actions, offset, limit, tsquery, adapterBySource);
    } catch {
      // search_bigrams 列未就绪（迁移/回填窗口）或 FTS 异常 → 降级扫描路径，保证搜索可用。
    }
  }
  return await searchViaScan(supabase, filters, prefs, actions, offset, limit, adapterBySource);
}

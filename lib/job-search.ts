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
  countExact,
  type Filters,
} from "@/lib/job-filter";
import type { JobAction, ScoredJob, UserPreferences } from "@/lib/types";
// china-keyword-expansion 为 CommonJS，沿用 hooks 的 import 习惯。
import { ftsCandidateTerms } from "@/lib/china-keyword-expansion";

const DB_PAGE = 1000;
// 扫描路径：逐批增大的并行扫描页数（累计 4/12/28 页）。
const BATCH_SIZES = [4, 8, 16];
const SCAN_BUDGET = 28000;
// FTS 路径：单次最多纳入的命中候选（远超绝大多数关键词的命中量；JS 精筛后分页）。
const FTS_CAP = 8000;

type SupabaseLike = { from: (table: string) => any };

export type SearchResult = {
  jobs: Array<ScoredJob & { __tier: "exact" | "related" }>;
  total: number;
  exactCount: number;
  capped: boolean;
  offset: number;
  limit: number;
};

// 与 SQL chinese_bigrams 同口径：小写→按空白切词→每词相邻双字（单字词原样）。
// 仅保留「纯字母/数字/CJK」的 2 字元（或单字），避免标点把 tsquery 语法搞坏。
function bigramsOf(term: string): string[] {
  const out: string[] = [];
  for (const tok of String(term || "").toLowerCase().split(/\s+/)) {
    if (!tok) continue;
    // 纯字母/数字/中日韩(BMP) 才保留；不用 \p{}/u 标志（项目 TS target < es6）。
    if (tok.length === 1) {
      if (/^[a-z0-9㐀-䶿一-鿿]$/.test(tok)) out.push(tok);
      continue;
    }
    for (let i = 0; i < tok.length - 1; i++) {
      const bg = tok.slice(i, i + 2);
      if (/^[a-z0-9㐀-䶿一-鿿]{2}$/.test(bg)) out.push(bg);
    }
  }
  return out;
}

// 一个词 → 「其全部 bigram 的 AND」子句（命中该词≈其 bigram 全在文档中）。无有效 bigram 返回 null。
function termClause(term: string): string | null {
  const bg = bigramsOf(term);
  if (!bg.length) return null;
  return `(${bg.join(" & ")})`;
}

// 构造 bigram tsquery：关键词候选词「组内 OR」，再与 城市/公司 等「过滤词 AND」。全空返回 null（→走浏览/扫描）。
function buildBigramTsquery(keywordTerms: string[], andTerms: string[]): string | null {
  const clauses: string[] = [];

  const kwClauses = keywordTerms.map(termClause).filter((c): c is string => !!c);
  if (kwClauses.length) clauses.push(`(${kwClauses.join(" | ")})`);

  for (const t of andTerms) {
    const c = termClause(t);
    if (c) clauses.push(c);
  }

  return clauses.length ? clauses.join(" & ") : null;
}

function annotateAndRank(
  rows: any[],
  filters: Filters,
  prefs: UserPreferences | null,
  actions: JobAction[],
): Array<ScoredJob & { __tier: "exact" | "related" }> {
  const scored = sortAndFilterJobs(rows, prefs, actions, {
    showIgnored: true,
    showApplied: true,
  }) as ScoredJob[];
  return filterAndRankJobs(scored, filters);
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
): Promise<SearchResult> {
  const company = filters.company.trim();
  const rows: any[] = [];
  for (let off = 0; off < FTS_CAP; off += DB_PAGE) {
    let q = supabase
      .from("jobs")
      .select("*")
      .eq("status", "active")
      .textSearch("search_bigrams", tsquery, { config: "simple" });
    if (company) q = q.ilike("company", `%${company}%`);
    // 按主键 id 取（稳定分页；@@ 选择性高，planner 走 GIN bitmap 后排序，避免扫全表）。
    const { data, error } = await q.order("id", { ascending: true }).range(off, off + DB_PAGE - 1);
    if (error) throw new Error(error.message); // 列未就绪/异常 → 调用方降级到扫描路径
    if (!data || data.length === 0) break;
    rows.push(...data);
    if (data.length < DB_PAGE) break;
  }

  const ranked = annotateAndRank(rows, filters, prefs, actions);
  return {
    jobs: ranked.slice(offset, offset + limit),
    total: ranked.length,
    exactCount: countExact(ranked),
    capped: rows.length >= FTS_CAP,
    offset,
    limit,
  };
}

// 扫描路径：按 (status,first_seen_at) 复合索引分批并行翻最新岗位 + JS 精筛，攒够当前页即停。
async function searchViaScan(
  supabase: SupabaseLike,
  filters: Filters,
  prefs: UserPreferences | null,
  actions: JobAction[],
  offset: number,
  limit: number,
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
    if (matched.length > need || exhausted || nextOff >= SCAN_BUDGET) break;
    const offsets: number[] = [];
    for (let k = 0; k < bsize && nextOff < SCAN_BUDGET; k++, nextOff += DB_PAGE) {
      offsets.push(nextOff);
    }
    const res = await Promise.all(offsets.map((o) => page(o)));
    for (const r of res) {
      if (r.error) throw new Error(r.error.message);
      const rows: any[] = r.data || [];
      if (rows.length === 0) {
        exhausted = true;
        continue;
      }
      const scored = sortAndFilterJobs(rows, prefs, actions, {
        showIgnored: true,
        showApplied: true,
      }) as ScoredJob[];
      for (const j of scored) {
        if (jobFilterTier(j, filters) !== null) matched.push(j);
      }
      if (rows.length < DB_PAGE) exhausted = true;
    }
  }

  const ranked = filterAndRankJobs(matched, filters);
  return {
    jobs: ranked.slice(offset, offset + limit),
    total: ranked.length,
    exactCount: countExact(ranked),
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
): Promise<SearchResult> {
  const keyword = filters.keyword.trim();
  const city = filters.city.trim();
  const company = filters.company.trim();

  // 有关键词/城市/公司 → FTS 路径（快且全召回）；其中关键词用 ftsCandidateTerms 取「精确+同职能」候选词。
  const keywordTerms = keyword ? ftsCandidateTerms(keyword) : [];
  const andTerms = [city, company].filter(Boolean);
  const tsquery = buildBigramTsquery(keywordTerms, andTerms);

  if (tsquery) {
    try {
      return await searchViaFTS(supabase, filters, prefs, actions, offset, limit, tsquery);
    } catch {
      // search_bigrams 列未就绪（迁移/回填窗口）或 FTS 异常 → 降级扫描路径，保证搜索可用。
    }
  }
  return await searchViaScan(supabase, filters, prefs, actions, offset, limit);
}

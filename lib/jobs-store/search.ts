// 服务端岗位搜索 —— 自建香港 jobs 库（pg）版，忠实复刻 lib/job-search.ts 的 searchJobs：
//   同一份 search_doc bigram FTS（to_tsquery）收窄候选 + 同一份 JS 精筛/排序（scoring + job-filter）。
//   差别仅「候选取数」从 supabase-js 换成直连 pg SQL → 搜索口径/精度/排序与线上零差异。
import "server-only";
import { jobsQuery } from "./client";
import { JOB_COLUMNS } from "./types";
import { sortAndFilterJobs } from "@/lib/scoring";
import { filterAndRankJobs, jobFilterTier, countExact, type Filters } from "@/lib/job-filter";
import { buildTsquery, annotateAndRank } from "@/lib/job-search";
import { ftsCandidateTerms, normalizeChinaCity } from "@/lib/china-keyword-expansion";
import type { JobAction, ScoredJob, UserPreferences } from "@/lib/types";

const FTS_CAP = 8000;
const DB_PAGE = 1000;
const SCAN_BUDGET = 28000;

export type SearchResult = {
  jobs: Array<ScoredJob & { __tier: "exact" | "related" }>;
  total: number;
  exactCount: number;
  capped: boolean;
  offset: number;
  limit: number;
};

// FTS 路径：search_doc @@ to_tsquery 收窄候选（pg 无 1000 行上限，一次取到 FTS_CAP）→ JS 精筛分层。
async function searchViaFTS(
  filters: Filters,
  prefs: UserPreferences | null,
  actions: JobAction[],
  offset: number,
  limit: number,
  tsquery: string,
): Promise<SearchResult> {
  // 不加 order by：让 planner 用 GIN bitmap 只取命中行；排序交给 JS filterAndRankJobs。
  const conds = ["status = 'active'", "search_doc @@ to_tsquery('simple', $1)"];
  const params: unknown[] = [tsquery];
  const city = filters.city.trim();
  if (city) {
    params.push(`%${normalizeChinaCity(city) || city}%`);
    conds.push(`location ilike $${params.length}`);
  }
  const company = filters.company.trim();
  if (company) {
    params.push(`%${company}%`);
    conds.push(`company ilike $${params.length}`);
  }
  const rows = await jobsQuery(
    `select ${JOB_COLUMNS} from jobs where ${conds.join(" and ")} limit ${FTS_CAP}`,
    params,
  );
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

// 扫描路径：按 (status,first_seen_at) 索引翻最新岗位 + JS 精筛，攒够当前页即停（纯浏览/FTS 降级用）。
async function searchViaScan(
  filters: Filters,
  prefs: UserPreferences | null,
  actions: JobAction[],
  offset: number,
  limit: number,
): Promise<SearchResult> {
  const need = offset + limit;
  const matched: ScoredJob[] = [];
  let off = 0;
  let exhausted = false;
  while (matched.length <= need && !exhausted && off < SCAN_BUDGET) {
    const rows: any[] = await jobsQuery(
      `select ${JOB_COLUMNS} from jobs where status='active' order by first_seen_at desc limit ${DB_PAGE} offset ${off}`,
    );
    if (!rows.length) {
      exhausted = true;
      break;
    }
    const scored = sortAndFilterJobs(rows, prefs, actions, {
      showIgnored: true,
      showApplied: true,
    }) as ScoredJob[];
    for (const j of scored) {
      if (jobFilterTier(j, filters) !== null) matched.push(j);
    }
    if (rows.length < DB_PAGE) exhausted = true;
    off += DB_PAGE;
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

// 入口：与 lib/job-search.ts searchJobs 同逻辑，去掉 supabase 参数（jobs-store 直连 pg）。
export async function searchJobsStore(
  filters: Filters,
  prefs: UserPreferences | null,
  actions: JobAction[],
  offset: number,
  limit: number,
): Promise<SearchResult> {
  const keyword = filters.keyword.trim();
  const keywordTerms = keyword ? ftsCandidateTerms(keyword) : [];
  const andTerms = [filters.city.trim(), filters.company.trim()].filter(Boolean);
  const tsquery = buildTsquery(keywordTerms, andTerms);

  if (tsquery) {
    try {
      return await searchViaFTS(filters, prefs, actions, offset, limit, tsquery);
    } catch {
      // FTS 异常 → 降级扫描，保证搜索永不挂
    }
  }
  return await searchViaScan(filters, prefs, actions, offset, limit);
}

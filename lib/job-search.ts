// 服务端岗位搜索：按 (status, first_seen_at) 复合索引「分批并行扫最新岗位」+ JS 精筛(复用 lib/job-filter) + 提前停。
//
// 为什么是这个形态（踩过的坑都在这）：
//  · 全库 ~10万行，一次性拉进来做筛选会 45s+ 且撞 Postgres statement_timeout —— 不可行。
//  · 关键词/城市是 2~3 字中文，`ilike '%产品%'` 上 pg_trgm 索引几乎不选择性(2字无足够 trigram)，单页仍要 ~6s、多页超时 —— 不可行。
//  · 真正快的是「复合索引按最新排序的纯翻页」(无 ilike)：实测每页 ~1s、深 offset 也稳定。
// 故：用复合索引按 first_seen desc 分批并行翻页，把每页行在 JS 里用与前端**完全相同**的 jobFilterTier 精筛，
// 攒够当前页(offset+limit)即停。匹配逻辑零改动(含 summary 正文匹配/两层相关召回)，结果与原前端逐字段一致。
// 代价：稀疏关键词只在「最近 SCAN_BUDGET 行」窗口内召回(回传 capped，前端显示「N+」并可加载更多)。
// 全库精确召回 + 秒级响应需物化检索列(category/function/分词)，作为后续优化(库继续暴涨时再做)。
import { sortAndFilterJobs } from "@/lib/scoring";
import {
  filterAndRankJobs,
  jobFilterTier,
  countExact,
  type Filters,
} from "@/lib/job-filter";
import type { JobAction, ScoredJob, UserPreferences } from "@/lib/types";

const DB_PAGE = 1000;
// 逐批增大的并行扫描页数（累计 4 / 12 / 28 页）：稠密查询(浏览/常见城市)第一批就够→快；稀疏关键词才扩到 28 页。
const BATCH_SIZES = [4, 8, 16];
// 单次搜索最多扫描的「最新岗位」行数窗口（控制稀疏查询成本 + DB 负载）。
const SCAN_BUDGET = 28000;

type SupabaseLike = { from: (table: string) => any };

export type SearchResult = {
  jobs: Array<ScoredJob & { __tier: "exact" | "related" }>;
  total: number;
  exactCount: number;
  capped: boolean;
  offset: number;
  limit: number;
};

export async function searchJobs(
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
      .order("first_seen_at", { ascending: false }) // 走迁移 138 的 (status, first_seen_at desc) 复合索引
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
      // 复用前端同口径打分（含 exclude_keywords 硬过滤）→ 再用同一份 jobFilterTier 精筛（含关键词两层匹配）。
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
    // 未扫到库尾就提前停 → 窗口外可能还有更多命中（前端显示「N+」并支持加载更多继续扫）。
    capped: !exhausted,
    offset,
    limit,
  };
}

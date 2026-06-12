// 服务端岗位搜索：有界 SQL 候选拉取 → 复用打分(sortAndFilterJobs) → 复用两层匹配排序(filterAndRankJobs) → 分页。
//
// 为什么不一次性把全库塞内存：实测全库 ~10万行 order-by-first_seen 深 offset 分页会触发 Postgres
// statement timeout（45s 且抓不全）。所以这里用「廉价 SQL 谓词把候选收窄到有界窗口」+「JS 精筛保持
// 与前端逐字段一致」：
//   · 关键词存在 → 用 expandChinaKeywordTerms 的同义词在 title/summary 上做 ilike 超集收窄（北京+产品 只拉 ~752 行而非全城 1.4万）。
//   · 城市/公司 → 按 location/company 的 ilike 收窄。
//   · 都没有（浏览） → 取最新 CAP 窗口。
// 关键词命中靠同义词超集（精确 + 含同义词的相关）；纯职能相关（标题/摘要无同义词但同职能）由 JS 两层匹配在候选内判定。
// JS 精筛复用 lib/job-filter（与浏览器端同一份），保证服务端结果 == 你在页面设同样筛选看到的。
import { sortAndFilterJobs } from "@/lib/scoring";
import {
  filterAndRankJobs,
  countExact,
  type Filters,
} from "@/lib/job-filter";
import type { JobAction, ScoredJob, UserPreferences } from "@/lib/types";
// china-keyword-expansion 为 CommonJS，沿用 hooks 的 import 习惯。
import {
  normalizeChinaCity,
  expandChinaKeywordTerms,
} from "@/lib/china-keyword-expansion";

// 单次搜索最多纳入的候选窗口（浅分页 ≤ CAP/1000 页）。
// 关键词搜索经同义词预筛后通常远小于此（如 北京+产品 仅 ~1094）；纯城市/全库浏览按最新 CAP 截断并回传 capped。
// 取 6000 平衡「覆盖真实关键词搜索」与「控制单次数据量/页数」。
const CAP = 6000;
const DB_PAGE = 1000;

type SupabaseLike = { from: (table: string) => any };

export type SearchResult = {
  jobs: Array<ScoredJob & { __tier: "exact" | "related" }>;
  total: number;
  exactCount: number;
  capped: boolean;
  offset: number;
  limit: number;
};

// PostgREST or() 过滤值含逗号/括号/点等保留字需双引号包裹；这里统一加引号并转义。
function quoteOrValue(v: string): string {
  return `"${String(v).replace(/["\\]/g, "\\$&")}"`;
}

// 把廉价谓词（公司/城市/薪资/关键词同义词）加到任意 builder 上（数据查询与 count 查询共用一处）。
function applyFilters(q: any, filters: Filters, keywordTerms: string[] | null) {
  const company = filters.company.trim();
  if (company) q = q.ilike("company", `%${company}%`);

  const city = filters.city.trim();
  if (city) {
    const norm = normalizeChinaCity(city);
    const ors = [`location.ilike.${quoteOrValue(`%${city}%`)}`];
    if (norm && norm !== city) ors.push(`location.ilike.${quoteOrValue(`%${norm}%`)}`);
    q = q.or(ors.join(","));
  }

  if (filters.salaryOnly) q = q.not("salary_text", "is", null);

  if (keywordTerms && keywordTerms.length) {
    const ors: string[] = [];
    for (const t of keywordTerms) {
      const pat = quoteOrValue(`%${t}%`);
      ors.push(`title.ilike.${pat}`);
      ors.push(`summary.ilike.${pat}`);
    }
    q = q.or(ors.join(","));
  }
  return q;
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
  const keywordTerms = keyword ? expandChinaKeywordTerms(keyword).slice(0, 40) : null;

  // 候选拉取：按主键 id 顺序浅分页拉到「无更多」或撞 CAP。
  // 刻意不做独立 count(exact)——那是又一次全表顺扫，未建索引时正是它先撞 statement_timeout。
  // 改用「拉满 CAP 即视为截断」，省一次全表扫；total 用 JS 精筛后的实际条数（未截断即精确）。
  const makePage = (off: number) =>
    applyFilters(
      supabase.from("jobs").select("*").eq("status", "active"),
      filters,
      keywordTerms,
    )
      // 按最新排序（截断窗口即「最近 CAP 条」），走迁移 138 的 (status, first_seen_at desc) 复合索引。
      .order("first_seen_at", { ascending: false })
      .range(off, off + DB_PAGE - 1);

  const rows: any[] = [];
  let capped = false;
  for (let off = 0; off < CAP; off += DB_PAGE) {
    const { data, error } = await makePage(off);
    if (error) throw new Error(error.message);
    if (!data || data.length === 0) break;
    rows.push(...data);
    if (data.length < DB_PAGE) break; // 最后一页
    if (rows.length >= CAP) {
      capped = true;
      break;
    }
  }

  // 复用前端同口径打分（含 exclude_keywords 硬过滤）+ 两层匹配排序。
  const scored = sortAndFilterJobs(rows, prefs, actions, {
    showIgnored: true,
    showApplied: true,
  }) as ScoredJob[];
  const ranked = filterAndRankJobs(scored, filters);

  return {
    jobs: ranked.slice(offset, offset + limit),
    total: ranked.length,
    exactCount: countExact(ranked),
    capped,
    offset,
    limit,
  };
}

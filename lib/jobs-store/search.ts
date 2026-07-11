// 服务端岗位搜索 —— 自建香港 jobs 库（pg）版，忠实复刻 lib/job-search.ts 的 searchJobs：
//   同一份 search_doc bigram FTS（to_tsquery）收窄候选 + 同一份 JS 精筛/排序（scoring + job-filter）。
//   差别仅「候选取数」从 supabase-js 换成直连 pg SQL → 搜索口径/精度/排序与线上零差异。
import "server-only";
import { jobsQuery } from "./client";
import { JOB_COLUMNS } from "./types";
import { sortAndFilterJobs } from "@/lib/scoring";
import {
  filterAndRankJobs,
  jobFilterTier,
  splitMultiValue,
  countMatchBreakdown,
  type Filters,
  type MatchReason,
} from "@/lib/job-filter";
import { buildTsquery, annotateAndRank, annotateSourceAdapter } from "@/lib/job-search";
import { cityMatchTokens, ftsCandidateTerms } from "@/lib/china-keyword-expansion";
import { appendJobScopeWhere, effectiveJobScope } from "@/lib/job-scope";
import type { JobAction, ScoredJob, UserPreferences } from "@/lib/types";

const FTS_CAP = 8000;
const DB_PAGE = 1000;
const SCAN_BUDGET = 28000;

// 候选取数只拉「打分/精筛」真正要用的列，把纯展示/写库列（正文之外最肥的 canonical_jd_url 等）留到
// 分页命中后再补——函数固定在美东、库在香港，跨太平洋每少传一列 × 数千行都直接缩短耗时。JS 打分/精筛
// （scoring + jobFilterMatch + recruitmentCategory + keywordMatchTier）只读这些列，删下面几列零精度影响。
const CANDIDATE_COLUMNS =
  "id, source_id, company, title, location, country_code, job_scope, job_type, summary, sponsorship_signal, " +
  "jd_url, apply_url, salary_text, posted_at, first_seen_at, last_seen_at, status, experience, education";
// 仅命中页(≤limit 行)回补的展示/写库列（打分精筛都不读）。
const HYDRATE_COLUMNS =
  "content_hash, created_at, deadline, enrich_fail_count, enrich_checked_at, canonical_jd_url";

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

function appendSoftCityWhere(conds: string[], params: unknown[], cities: string[]) {
  const tokens = cities.flatMap((c) => cityMatchTokens(c));
  if (!tokens.length) return;

  // 城市筛选必须是 JS matcher 的超集：空 location 要放行降级，多城市所有别名/拼音也要进候选（OR）。
  const parts = ["location is null", "location = ''"];
  for (const tok of tokens) {
    params.push(`%${tok}%`);
    parts.push(`location ilike $${params.length}`);
  }
  conds.push(`(${parts.join(" or ")})`);
}

// 校招/实习「预筛超集」下推 SQL：这两类是「会自报家门的少数派」（校招/实习各占极小比例），JS 把无信号岗
// 兜底成社招后再一刀切，导致 8000 候选里绝大多数被传过来又被丢。这里在 SQL 侧先只保留「可能是校招/实习」
// 的行——严格是 recruitmentCategory 判定的**超集**（只加正向信号、不做任何排除），最终判定仍由 JS 权威执行，
// 因此零精度损失，只是别再把 97% 的社招岗跨洋传过来。社招是默认态（大头），不下推。
// ⚠️ 正则须与 china-keyword-expansion 的 sourceDeclaredCategory / hasStrongCampusSignal / hasInternSignal 对齐，
// 改一处两处同改，否则可能漏掉真校招/实习（精度红线）。
function appendRecruitmentPrefilter(conds: string[], jobType: string) {
  if (jobType === "校招") {
    // (a) 正向校招信号超集  AND  (b) 排除「job_type 自报社招」——sourceDeclaredCategory 里 社招 的判定
    // 在校招之前短路(且实习更先)，故 job_type 命中社招模式的岗在 JS 里必是 社招/实习、绝不会是校招，
    // 可安全剔除（实测把候选从 4423 收到 2661，最终校招结果数不变）。null job_type 必须保留。
    conds.push(
      "((job_type ~* '(校招|校园招聘|应届|管培生|管理培训生|留学生专项|campus|new\\s+grad|university\\s+graduate|entry[-\\s]?level)'" +
        " or jd_url ~* '(xiaozhao|campus)'" +
        " or (coalesce(title,'')||' '||coalesce(summary,'')) ~* '(应届|[0-9]{2,4}届|校园招聘|校招|管培生|管理培训生|留学生专项|new\\s?grads?|university\\s+graduate|entry[-\\s]?level|campus\\s?(recruit|hiring)|graduate\\s+program)'" +
        " or company ~* '(校招|校园招聘)')" +
        " and (job_type is null or job_type !~* '(社招|社会招聘|全职|experienced|professional|full.?time)'))",
    );
  } else if (jobType === "实习") {
    conds.push(
      "(job_type ~* '(实习|intern)' or title ~* '(实习|shixi|intern)' or jd_url ~* '(shixi|intern)')",
    );
  }
}

// 命中页回补 HYDRATE_COLUMNS：候选阶段没拉这些展示列，排序分页定下 ≤limit 行后按 id 批量补齐再合并。
async function hydratePageColumns(
  page: Array<ScoredJob & { __tier: "exact" | "related"; __match: MatchReason }>,
): Promise<void> {
  if (!page.length) return;
  const ids = page.map((j) => j.id);
  const placeholders = ids.map((_, i) => `$${i + 1}`).join(",");
  const extra = (await jobsQuery(
    `select id, ${HYDRATE_COLUMNS} from jobs where id in (${placeholders})`,
    ids,
  )) as Array<Record<string, unknown>>;
  const byId = new Map(extra.map((r) => [r.id as string, r]));
  for (const j of page) {
    const e = byId.get(j.id);
    if (e) Object.assign(j, e);
  }
}

// FTS 路径：search_doc @@ to_tsquery 收窄候选（pg 无 1000 行上限，一次取到 FTS_CAP）→ JS 精筛分层。
async function searchViaFTS(
  filters: Filters,
  prefs: UserPreferences | null,
  actions: JobAction[],
  offset: number,
  limit: number,
  tsquery: string,
  adapterBySource?: Map<string, string | null> | null,
): Promise<SearchResult> {
  // 不加 order by：让 planner 用 GIN bitmap 只取命中行；排序交给 JS filterAndRankJobs。
  const conds = ["status = 'active'", "search_doc @@ to_tsquery('simple', $1)"];
  const params: unknown[] = [tsquery];
  appendJobScopeWhere(conds, params, prefs, filters);
  const cities = splitMultiValue(filters.city);
  if (cities.length) {
    appendSoftCityWhere(conds, params, cities);
  }
  const company = filters.company.trim();
  if (company) {
    params.push(`%${company}%`);
    conds.push(`company ilike $${params.length}`);
  }
  // 校招/实习超集下推：只保留可能命中的行，别把大量社招岗跨洋传过来（JS 仍权威判定）。
  appendRecruitmentPrefilter(conds, filters.jobType);
  const rows = annotateSourceAdapter(
    await jobsQuery(
      `select ${CANDIDATE_COLUMNS} from jobs where ${conds.join(" and ")} limit ${FTS_CAP}`,
      params,
    ),
    adapterBySource,
  );
  const ranked = annotateAndRank(rows, filters, prefs, actions);
  const breakdown = countMatchBreakdown(ranked);
  const page = ranked.slice(offset, offset + limit);
  await hydratePageColumns(page); // 命中页回补展示列（候选阶段省传）
  return {
    jobs: page,
    total: ranked.length,
    exactCount: breakdown.exact,
    relatedSameFunction: breakdown.relatedSameFunction,
    relatedMissingInfo: breakdown.relatedMissingInfo,
    capped: rows.length >= FTS_CAP,
    offset,
    limit,
  };
}

// 扫描路径：按 (status,first_seen_at) 索引翻最新岗位 + JS 精筛；newest 可攒够即停，match 必须看满预算后再按分排序。
async function searchViaScan(
  filters: Filters,
  prefs: UserPreferences | null,
  actions: JobAction[],
  offset: number,
  limit: number,
  adapterBySource?: Map<string, string | null> | null,
): Promise<SearchResult> {
  const need = offset + limit;
  const matched: ScoredJob[] = [];
  let off = 0;
  let exhausted = false;
  const conds = ["status = 'active'"];
  const params: unknown[] = [];
  appendJobScopeWhere(conds, params, prefs, filters);
  appendRecruitmentPrefilter(conds, filters.jobType); // 校招/实习超集下推，扫描也少翻无关行
  while ((filters.sortBy === "match" || matched.length <= need) && !exhausted && off < SCAN_BUDGET) {
    const rows: any[] = annotateSourceAdapter(
      await jobsQuery(
        `select ${JOB_COLUMNS} from jobs where ${conds.join(" and ")} order by first_seen_at desc limit $${params.length + 1} offset $${params.length + 2}`,
        [...params, DB_PAGE, off],
      ),
      adapterBySource,
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

// 入口：与 lib/job-search.ts searchJobs 同逻辑，去掉 supabase 参数（jobs-store 直连 pg）。
export async function searchJobsStore(
  filters: Filters,
  prefs: UserPreferences | null,
  actions: JobAction[],
  offset: number,
  limit: number,
  adapterBySource?: Map<string, string | null> | null,
): Promise<SearchResult> {
  const keywords = splitMultiValue(filters.keyword);
  const cities = splitMultiValue(filters.city);
  const includeOverseasLexicon = effectiveJobScope(prefs) !== "domestic";
  // 多关键词各自展开候选词后并集（tsquery 内 OR）。
  const keywordTerms = keywords.flatMap((kw) =>
    ftsCandidateTerms(kw, { includeOverseasLexicon }),
  );
  // 城市必须留在 tsquery：走全表 GIN 命中，保住城市浏览的【完整覆盖】——location 无 trigram 索引，
  // 把城市移出 tsquery 会让「城市 / 城市+类型」等无关键词搜索退化到 scan（仅最新 28k），实测只覆盖
  // ~6% 目标城市岗（北京 1818/28201）。多城市为一个 OR 组（(北京 | 上海)），与关键词/公司 AND。
  // 空 location 与别名/拼音的「软放行」由 appendSoftCityWhere 的 OR 组精修（location null / 别名 ilike）
  // ——它是 JS matcher 的超集，且排除「只在正文提到该城、实际在别处」的岗。
  const andTerms = filters.company.trim() ? [filters.company.trim()] : [];
  const orGroups = cities.length ? [cities] : [];
  const tsquery = buildTsquery(keywordTerms, andTerms, orGroups);

  if (tsquery) {
    try {
      return await searchViaFTS(filters, prefs, actions, offset, limit, tsquery, adapterBySource);
    } catch {
      // FTS 异常 → 降级扫描，保证搜索永不挂
    }
  }
  return await searchViaScan(filters, prefs, actions, offset, limit, adapterBySource);
}

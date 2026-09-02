// 服务端岗位搜索 —— 自建香港 jobs 库（pg）版，忠实复刻 lib/job-search.ts 的 searchJobs：
//   同一份 search_doc bigram FTS（to_tsquery）收窄候选 + 同一份 JS 精筛/排序（scoring + job-filter）。
//   差别仅「候选取数」从 supabase-js 换成直连 pg SQL → 搜索口径/精度/排序与线上零差异。
import "server-only";
import { jobsQuery } from "./client";
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

/**
 * 候选缓存 TTL（同一 lambda 实例内跨请求共享，FTS 与扫描两条路径共用）。
 * 能共享的理由与不变量见下面 `fetchCandidates` 的注释。
 *
 * 线上实测收益（香港库）：无筛选的 /jobs 落地态要拉满 SCAN_BUDGET=2.8 万行，
 * 首次 TTFB 19.0s、命中缓存 2.1s；FTS 路径（城市/关键词搜索）4354 行候选，
 * 未接缓存时**每翻一页都重拉一遍**。in-flight 去重让并发请求只拉一次。
 */
const SCAN_CACHE_TTL_MS = 60_000;
/**
 * 缓存按**行数**记账，不按条数。
 *
 * 两条路径的候选集大小差一个数量级（扫描 28000 行 ≈ 20MB，FTS 常见几千行 ≈ 5MB），
 * 按条数封顶会让「一个扫描候选集」和「一个 FTS 候选集」占同样的名额：/jobs 落地页与
 * 城市搜索交替访问时互相驱逐，两边都永远打不中。按行数记账则大集合自然占更多预算。
 * 6 万行 ≈ 两份满额扫描候选，是这个函数内存上限的保守取值。
 */
const CANDIDATE_CACHE_ROW_BUDGET = 60_000;
const scanCache = new Map<string, { expiresAt: number; rows: any[] }>();
const scanInFlight = new Map<string, Promise<any[]>>();

/** 供测试重置模块级缓存（本文件每个用例都是新模块实例，这里只为显式清理留个口子）。 */
export function __resetScanCache(): void {
  scanCache.clear();
  scanInFlight.clear();
}

/** 超预算时按插入顺序淘汰最旧的（Map 保序），而不是整体 clear —— 别为了收一份新的把全部热数据丢光。 */
function evictToRowBudget(incomingRows: number): void {
  let total = incomingRows;
  for (const entry of scanCache.values()) total += entry.rows.length;
  for (const key of scanCache.keys()) {
    if (total <= CANDIDATE_CACHE_ROW_BUDGET) break;
    total -= scanCache.get(key)!.rows.length;
    scanCache.delete(key);
  }
}

/**
 * 取候选行（带进程内缓存 + 并发去重）。**FTS 与扫描两条路径共用**。
 *
 * key = 完整 SQL + 全部绑定参数，而 where 子句里已经含了会改变结果集的每一项
 * （tsquery / 求职范围 / 城市 / 公司 / 发布时间 / 招聘类型预筛）→ 同 key 必同结果集，
 * 不同用户的偏好差异会体现成不同的 params、拿到各自的 key，不会串味。
 * 用户偏好只参与之后的打分/精筛，而那一步在 `sortAndFilterJobs` 里是
 * `{...job, match_score, …}` **复制**后再写（lib/scoring.ts），不碰原行。
 *
 * ⚠️ **不变量：任何人不得就地改写这些行。** 唯一例外是 `annotateSourceAdapter` 写
 * `source_adapter`，它的值来自全局 sources 映射、与用户无关，因此幂等安全。
 * 若将来新增「按用户往行对象写回」的逻辑，**必须先深拷贝**，否则会把一个用户的数据泄给另一个。
 *
 * TTL 60s：岗位库由爬虫按天级写入，60 秒的陈旧对用户不可见。
 */
async function fetchCandidates(sql: string, params: unknown[]): Promise<any[]> {
  const key = `${sql}|${JSON.stringify(params)}`;
  const hit = scanCache.get(key);
  if (hit && hit.expiresAt > Date.now()) return hit.rows;
  const pending = scanInFlight.get(key);
  if (pending) return pending;

  const p = (async () => {
    try {
      const rows = await queryCandidateRows(sql, params);
      scanCache.delete(key); // 重新插入 = 移到队尾，让淘汰顺序反映最近写入
      evictToRowBudget(rows.length);
      scanCache.set(key, { expiresAt: Date.now() + SCAN_CACHE_TTL_MS, rows });
      return rows;
    } finally {
      scanInFlight.delete(key);
    }
  })();
  scanInFlight.set(key, p);
  return p;
}
// ⚠️⚠️ 别再尝试「并行取候选页」来加速这条扫描路径 —— 2026-07-30 线上实测两次都更差：
//   1) 照搬 lib/job-search.ts 的 BATCH_SIZES=[4,8,16] → 直接 500
//      ({"error":"timeout exceeded when trying to connect"})。两条路径机制不同不能照搬：
//      那份走 supabase-js（HTTP，无池上限），这里直连 pg，受 client.ts 的
//      max:5 + connectionTimeoutMillis:8000 约束，池满后多出的获取请求不排队、8s 就抛。
//   2) 降到并发 3（< 池 max）后 500 消失，但 TTFB 从基线 25s **恶化到 32s**。
// 原因：香港库是 2 vCPU 轻量机，而 `order by first_seen_at desc limit 1000 offset 27000`
// 这类大偏移扫描是 DB 端 CPU 密集活（要走完并跳过 2.7 万行），并发只是互抢 CPU；
// node-pg 解析 2.8 万肥行也是单线程，并行取回只让解析交错。
// → 结论：这条路径的瓶颈不是「等网络往返」，并行救不了它。真正的解法是别扫 2.8 万行
//   （把打分/排序下推到 SQL，或缩小候选窗口），属于检索层重构，见设计文档。

// 候选取数只拉「打分/精筛」真正要用的列，把纯展示/写库列（正文之外最肥的 canonical_jd_url 等）留到
// 分页命中后再补。JS 打分/精筛（scoring + jobFilterMatch + recruitmentCategory + keywordMatchTier）
// 只读这些列，删下面几列零精度影响。
const CANDIDATE_TEXT_COLUMNS = [
  "id", "source_id", "company", "title", "location", "country_code", "job_scope", "job_type",
  "summary", "sponsorship_signal", "jd_url", "apply_url", "salary_text", "status",
  "experience", "education",
] as const;
// timestamptz 列。JSON 传输层必须显式 ::text —— 见 queryCandidateRows 的说明。
const CANDIDATE_TS_COLUMNS = ["posted_at", "first_seen_at", "last_seen_at"] as const;
const CANDIDATE_COLUMNS = [...CANDIDATE_TEXT_COLUMNS, ...CANDIDATE_TS_COLUMNS].join(", ");
// JSON 层的投影：时间列转成与线协议**逐字节相同**的文本（都走 timestamptz_out，
// 已在生产库拿 2 万行核对过 0 处差异），其余列原样。两份列表由同一组常量派生，杜绝漂移。
const CANDIDATE_JSON_PROJECTION = [
  ...CANDIDATE_TEXT_COLUMNS,
  ...CANDIDATE_TS_COLUMNS.map((c) => `${c}::text as ${c}`),
].join(", ");
// 仅命中页(≤limit 行)回补的展示/写库列（打分精筛都不读）。
const HYDRATE_COLUMNS =
  "content_hash, created_at, deadline, enrich_fail_count, enrich_checked_at, canonical_jd_url";

/**
 * 取候选行：让**库**把整个结果集打成一个 json 数组一次性传回，而不是走 pg 的逐字段线协议。
 *
 * 为什么：香港库实测这条接口的服务端耗时几乎全在「把候选行搬进函数」这一步，而且它既不是
 * 数据库执行也不是网络——
 *   FTS(4354 行)：堆扫描+过滤 355~383ms，渲染成线协议文本 489~678ms，而端到端服务端耗时约 2.3s；
 *   扫描(28000 行)：库侧 3.2~3.4s，端到端却要 19s。
 * 差额是 node-pg 在函数里逐字段解析的开销：4354 行 × 19 列 = 8.3 万次、28000 行 = 53 万次
 * 字段解析，全在 JS 单线程上。改成一个 json 字段后，node-pg 只解析 1 个字段，剩下的交给
 * V8 原生 JSON.parse（pg 对 json 类型的默认 parser 就是它）。
 * 库侧成本反而更低（json_agg 425~436ms < 线协议渲染 489~678ms），字节数也少约 11%。
 *
 * ⚠️ 三条不变量，改这里必须全部保住：
 *  1) **内层 SQL 原样不动**。时间列的 ::text 只能放在外面这层投影里。曾试过把 ::text 直接写进
 *     内层列表，结果 `order by first_seen_at` 被解析成**输出列**（已是 text）→ 计划变成
 *     `Sort Key: ((jobs.first_seen_at)::text) DESC`，排序从时间序悄悄变成字典序。
 *  2) **时间列必须显式 ::text**。让 json_agg 自己渲染 timestamptz 会得到 ISO-8601
 *     （`2026-07-07T14:15:17.841751+08:00`），与全库假定的线协议文本
 *     （`2026-07-07 14:15:17.841751+08`）不一样 —— 2026-06-26 的 503 就是时间列类型不一致
 *     引发的（见 client.ts 的 type parser 注释）。::text 与线协议同走 timestamptz_out，
 *     已在生产库拿 2 万行核对过 0 处差异。
 *  3) **中间那层只做投影**（无 order by / 无聚合），所以它按输入顺序流式产出，json_agg 也就
 *     按同样顺序聚合 —— 行顺序与改造前逐行对拍一致（同一 REPEATABLE READ 快照下 4354 行
 *     与 28000 行各自 0 处差异）。顺序不是可有可无的：命中同分时 V8 的稳定排序会让输入顺序
 *     决定展示顺序。
 */
async function queryCandidateRows(innerSql: string, params: unknown[]): Promise<any[]> {
  const rows = (await jobsQuery(
    `select coalesce(json_agg(t), '[]'::json) as rows ` +
      `from (select ${CANDIDATE_JSON_PROJECTION} from (${innerSql}) src) t`,
    params,
  )) as Array<{ rows: any[] | null }>;
  return rows[0]?.rows ?? [];
}

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

function appendPostedWithinWhere(conds: string[], params: unknown[], postedWithin: string) {
  if (!postedWithin) return;
  const days = Number(postedWithin);
  if (!Number.isInteger(days) || ![1, 3, 7, 30].includes(days)) return;
  params.push(days);
  // 发布时间是唯一能安全缩小候选窗口的新条件；NULL 没有可核验的发布时间，不能混进「最近发布」。
  conds.push(`posted_at >= now() - ($${params.length}::int * interval '1 day')`);
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
  appendPostedWithinWhere(conds, params, filters.postedWithin);
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
  // 走同一份候选缓存：候选集只由 where 决定（已全部进 key），而**翻页是在 JS 里 slice 的**——
  // 第 2 页的 SQL 与第 1 页逐字节相同。不缓存的话每翻一页都要把几千行重新跨库拉一遍再解析一遍，
  // 香港库实测这段占该接口服务端耗时的绝大部分（4354 行 ≈ 4.8MB）。
  const rows = annotateSourceAdapter(
    await fetchCandidates(
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
  let nextOff = 0;
  let exhausted = false;
  const conds = ["status = 'active'"];
  const params: unknown[] = [];
  appendJobScopeWhere(conds, params, prefs, filters);
  appendPostedWithinWhere(conds, params, filters.postedWithin);
  appendRecruitmentPrefilter(conds, filters.jobType); // 校招/实习超集下推，扫描也少翻无关行
  // 候选只取 CANDIDATE_COLUMNS（与 FTS 路径同一套）：JS 打分/精筛只读这些列，纯展示列留到
  // 命中页再回补。此前这里拉的是全量 JOB_COLUMNS —— sortBy=match 默认要看满 SCAN_BUDGET=28000 行，
  // 多传的 6 个展示列 × 2.8 万行是白扔的带宽。
  const sql =
    `select ${CANDIDATE_COLUMNS} from jobs where ${conds.join(" and ")} ` +
    `order by first_seen_at desc limit $${params.length + 1} offset $${params.length + 2}`;
  const fetchRows = (want: number, off: number) => queryCandidateRows(sql, [...params, want, off]);
  // 吸收一批：打分/精筛后并入 matched，返回「是否已到底」（拿到的比想要的少 = 没更多了）。
  const absorb = (raw: unknown, want: number): boolean => {
    const rows: any[] = annotateSourceAdapter(raw as any[], adapterBySource);
    if (!rows.length) return true;
    const scored = sortAndFilterJobs(rows, prefs, actions, {
      showIgnored: true,
      showApplied: true,
    }) as ScoredJob[];
    for (const j of scored) {
      if (jobFilterTier(j, filters) !== null) matched.push(j);
    }
    return rows.length < want;
  };

  if (filters.sortBy === "match") {
    // match 必须看满 SCAN_BUDGET 才能按分排序 → **一次查完，不要 OFFSET 翻页**。
    // 翻页是移植 lib/job-search.ts 时留下的阑尾：那侧走 PostgREST（单次最多返 1000 行）
    // 才不得不翻页，直连 pg 没有该上限 —— 同文件的 FTS 路径本来就是一条 `limit FTS_CAP`。
    // OFFSET 还是二次方浪费：第 k 页要重走 k×1000 条索引项，28 页累计走 40.6 万次才取回 2.8 万行。
    // 结果集与顺序同翻页版完全一致（同一 where + 同一 order by，只是不再分片取）。
    //
    // 香港库实测（EXPLAIN ANALYZE，热缓存，不含结果传输）：
    //   28 次 OFFSET 翻页累计  679 ms
    //   单查询 limit 28000      45~73 ms
    // ⚠️ 收益就 ~0.6s，别高估：这条接口端到端约 21s，DB 执行只占极小一块。
    // 真正的大头是**把候选传回来**——2.8 万行里 summary 就占 15 MB（其余关键列仅 4.3 MB）。
    // 而 summary 砍不掉：classifyJobFunction / keywordMatchTier 的兄弟组排除 / 校招信号判定
    // 都要读它（见 lib/china-keyword-expansion.js:709/753/623），砍了就是静默改坏匹配精度。
    // → 更进一步的解法是**物化派生字段**（job_function / 招聘类型等落成列，写入时算好），
    //   让候选取数根本不需要 summary。属 schema 改动，见设计文档。
    // 在物化之前，先用「候选与用户无关」这一点把重复传输吃掉：走进程内缓存 + 并发去重
    // （见上面 fetchCandidates 的注释与不变量）。
    exhausted = absorb(
      await fetchCandidates(sql, [...params, SCAN_BUDGET, 0]),
      SCAN_BUDGET,
    );
  } else {
    // newest 攒够 need 即停 → 保持逐页，不为了少几次往返把 2.8 万行全拉回来。
    // （并行取页已实测更慢/会 500，见上面常量位置的记录，别再改回去。）
    while (matched.length <= need && !exhausted && nextOff < SCAN_BUDGET) {
      exhausted = absorb(await fetchRows(DB_PAGE, nextOff), DB_PAGE);
      nextOff += DB_PAGE;
    }
  }
  const ranked = filterAndRankJobs(matched, filters);
  const breakdown = countMatchBreakdown(ranked);
  const page = ranked.slice(offset, offset + limit);
  await hydratePageColumns(page); // 命中页回补展示列（候选阶段省传）
  return {
    jobs: page,
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

// 服务端岗位搜索 —— 自建香港 jobs 库（pg）版，忠实复刻 lib/job-search.ts 的 searchJobs：
//   同一份 search_doc bigram FTS（to_tsquery）收窄候选 + 同一份 JS 精筛/排序（scoring + job-filter）。
//   差别仅「候选取数」从 supabase-js 换成直连 pg SQL → 搜索口径/精度/排序与线上零差异。
import "server-only";
import { unstable_cache } from "next/cache";
import { jobsQuery } from "./client";
import { actionHiddenJobIds, scoringSignalGroups, scoringTargetFunctions, scoringTargetRoles, sortAndFilterJobs } from "@/lib/scoring";
import {
  filterAndRankJobs,
  filtersFullyPushedToSql,
  jobFilterTier,
  splitMultiValue,
  countMatchBreakdown,
  type Filters,
  type MatchReason,
} from "@/lib/job-filter";
import { buildTsquery, annotateAndRank, annotateSourceAdapter, queryTokens } from "@/lib/job-search";
import ftsTokenDf from "@/lib/fts-token-df.json";
import { cityMatchTokens, ftsCandidateTerms } from "@/lib/china-keyword-expansion";
import { companyTierPatterns, NAMED_TIER_PATTERNS } from "@/lib/company-tiers";
import { appendJobScopeWhere, effectiveJobScope } from "@/lib/job-scope";
import { collapseBulkStoreJobs } from "@/lib/bulk-store-dedup";
import { appendCurrentSeasonWhere } from "@/lib/campus-season";
import { currentGradClass } from "@/lib/grad-class";
import { spreadByCompany } from "../job-diversify";
import type { JobAction, ScoredJob, UserPreferences } from "@/lib/types";

const FTS_CAP = 8000;
const DB_PAGE = 1000;
const SCAN_BUDGET = 28000;
// 登录 + 按匹配度排（扫描路径）的候选窗口（2026-09-17）：SQL 先按打分公式的四个可下推项粗排
// （方向 30 / 城市 20 / 公司 15 / 7 天内 10，见 prescoreOrderBy），JS 只精排这一窗。
// 窗口 1000 + 候选不传正文：真实用户偏好对拍，第一页 60 条与「全量 28,000 行带正文 JS 精排」重合 94%（W2000 96%），
// 差异全是同分并列；载荷与匿名默认态同量级（<1MB），见 docs/reviews/2026-09-17 §10。
// env JOBS_MATCH_WINDOW 可整体调档（出事改 Vercel 变量即可，不用重新部署）。
function matchPrescoreWindow(): number {
  const raw = Number(process.env.JOBS_MATCH_WINDOW || 0);
  return Number.isFinite(raw) && raw > 0 ? Math.min(raw, SCAN_BUDGET) : 1000;
}

/**
 * 候选缓存 TTL（同一 lambda 实例内跨请求共享，FTS 与扫描两条路径共用）。
 * 能共享的理由与不变量见下面 `fetchCandidates` 的注释。
 *
 * 线上实测收益（香港库）：无筛选的 /jobs 落地态要拉满 SCAN_BUDGET=2.8 万行，
 * 首次 TTFB 19.0s、命中缓存 2.1s；FTS 路径（城市/关键词搜索）4354 行候选，
 * 未接缓存时**每翻一页都重拉一遍**。in-flight 去重让并发请求只拉一次。
 *
 * 2026-09-03 由 60s 提到 5min：登录态生产实测这条接口有两个清晰档位——命中 1.0~1.7s、
 * 未命中 3.6~5.8s（城市越大越慢：上海 total 3567 首发 5.8s）。60s 覆盖不住一次正常的
 * 筛选/翻页浏览，用户每隔一会儿就掉回未命中档。
 * 陈旧代价可忽略：岗位库由爬虫**按天**写入，且缓存只存原始岗位行——用户自己的
 * 收藏/忽略/投递(actions)与偏好都在缓存之后的打分层参与，改了立刻生效，不受 TTL 影响。
 * 死岗也不靠它兜底：看板加载后有异步探活会把死岗当场隐藏（见 CLAUDE.md「展示时校验」）。
 * ⚠️ 上限由下面的**行数预算**兜着，不由 TTL 兜——调 TTL 不会让内存无限涨。
 */
const SCAN_CACHE_TTL_MS = 300_000;
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
 * TTL 见 SCAN_CACHE_TTL_MS：岗位库由爬虫按天级写入，分钟级陈旧对用户不可见。
 */
async function fetchCandidates(sql: string, params: unknown[], meta?: { cacheHit?: boolean }): Promise<any[]> {
  const key = `${sql}|${JSON.stringify(params)}`;
  const hit = scanCache.get(key);
  if (hit && hit.expiresAt > Date.now()) {
    if (meta) meta.cacheHit = true;
    return hit.rows;
  }
  const pending = scanInFlight.get(key);
  if (pending) {
    if (meta) meta.cacheHit = true;
    return pending;
  }
  if (meta) meta.cacheHit = false;

  const p = (async () => {
    try {
      const rows = (await jobsQuery(sql, params)) as any[];
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
// 分页命中后再补——函数固定在美东、库在香港，跨太平洋每少传一列 × 数千行都直接缩短耗时。JS 打分/精筛
// （scoring + jobFilterMatch + recruitmentCategory + keywordMatchTier）只读这些列，删下面几列零精度影响。
// job_function / recruitment_category / recruitment_explicit（2026-09-17 加）：入库时算好的物化分类，
// classifyJobFunction / recruitmentCategory 有列就认列，与 /campus、/today 同一口径，也是下面「正文按需传」的前提。
const CANDIDATE_BASE_COLUMNS =
  "id, source_id, company, title, location, country_code, job_scope, job_type, sponsorship_signal, " +
  "jd_url, apply_url, salary_text, posted_at, first_seen_at, last_seen_at, status, experience, education, " +
  "job_function, recruitment_category, recruitment_explicit";
/** 候选列 = 轻列 + 「按需传」的正文（见 candidateSummaryExpr）。 */
function candidateColumns(summaryExpr: string): string {
  return `${CANDIDATE_BASE_COLUMNS}, ${summaryExpr} as summary`;
}

/**
 * 正文只传给「打分/精筛真会读它」的行（2026-09-17，/jobs 默认态冷路径 14~35s 的主因是把 2.8 万行正文传回函数：
 * 16 MB 里正文占 13~15 MB）。
 *
 * 可以不传的行：scoreJob 的职能门 `functionAllowed = userFns.size===0 || jobFn==='其他' || userFns.has(jobFn)`
 * 一旦为 false，方向/关键词命中一律不算 —— 这些行的正文读了也白读。用户目标职能是「产品」时，
 * 研发/销售/生产制造… 的行（active 里占 ~77%）正文直接不传。等价性成立的前提：
 *   ① classifyJobFunction 认物化列（有列就不现算，所以 summary=null 不改变职能判定）；
 *   ② 排除词已下推到 SQL（appendExcludeWhere），JS 不再靠正文判排除；
 *   ③ 只有 keyword / jobRole / experience 这三个 JS 精筛条件会读正文，任一生效就退回全传。
 * 匿名（无偏好）或目标职能判不出 → 全传（scoreJob 没有职能门可省）。
 */
export function candidateSummaryExpr(candidateParams: unknown[], filters: Filters, prefs: UserPreferences | null): string {
  const readsBody = [filters.keyword, filters.jobRole, filters.experience].some((v) => String(v ?? "").trim());
  if (readsBody) return "summary";
  // 匿名：scoreJob 直接返回 0 分、不读任何正文；上面三个读正文的精筛也没开 → 一行正文都不用传
  // （命中页展示用的摘要由 hydratePageColumns 按 id 回补）。
  if (!prefs) return "null::text";
  // 登录 + 按匹配度排（2026-09-17）：候选也不传正文，正文只给命中页回补。香港机出口个位数 Mbps，
  // 正文是候选载荷的大头；不传后打分只看标题/地点/公司/类型（正文里的关键词命中随之失效），
  // 但真库对拍第一页与「全量 28,000 行带正文精排」重合 94~96%、差异全是同分并列（docs/reviews/2026-09-17 §10）。
  // 筛选里显式读正文的项（keyword / jobRole / experience）仍走上面的 `summary` 分支。
  if (filters.sortBy === "match") return "null::text";
  const fns = scoringTargetFunctions(prefs);
  if (!fns.length) return "summary";
  candidateParams.push(fns);
  return `(case when job_function is null or job_function = '其他' or job_function = any($${candidateParams.length}::text[]) then summary else null end)`;
}

function escapeLike(value: string): string {
  return value.replace(/[\\%_]/g, (m) => `\\${m}`);
}

/**
 * 排除词下推 SQL（与 lib/scoring.ts scoreJob 的 `text.includes(ek)` 同字段集：title + summary，同为子串、大小写不敏感）。
 * 此前只在 JS 里判 → 撞候选上限时算不出真实总数（exactTotalWhenCapped 的偏好门），现在 SQL 与 JS 同口径，
 * 计数也能给确定数字。正文按需传（candidateSummaryExpr）后更是必须：JS 看不到的正文由这里兜。
 */
export function appendExcludeWhere(conds: string[], params: unknown[], prefs: UserPreferences | null) {
  const words = (prefs?.exclude_keywords || [])
    .map((w) => String(w || "").trim().toLowerCase())
    .filter(Boolean);
  if (!words.length) return;
  params.push(words.map((w) => `%${escapeLike(w)}%`));
  conds.push(`not (lower(coalesce(title, '') || ' ' || coalesce(summary, '')) like any($${params.length}::text[]))`);
}
// 仅命中页(≤limit 行)回补的展示/写库列（打分精筛都不读）。
// summary 也在这里回补：候选阶段对职能门必拒的行不传正文（candidateSummaryExpr），但卡片要展示摘要——
// 命中页 ≤limit 行按 id 补齐即可，Object.assign 落在打分后的副本上，不碰候选缓存里的原行。
const HYDRATE_COLUMNS =
  "content_hash, created_at, deadline, enrich_fail_count, enrich_checked_at, canonical_jd_url, summary";

export type SearchResult = {
  jobs: Array<ScoredJob & { __tier: "exact" | "related"; __match: MatchReason }>;
  /** 可翻页的条数 = 候选里通过精筛的条数。候选被截断时它**不是**真实总数，别拿它当计数展示。 */
  total: number;
  exactCount: number;
  relatedSameFunction: number;
  relatedMissingInfo: number;
  /** 候选撞上限：`total` 只是「取到这么多」，真实匹配数更大。 */
  capped: boolean;
  /** capped 时的真实匹配总数；只有能证明数字正确时才有值，否则 null（前端退回「N+」）。 */
  exactTotal: number | null;
  offset: number;
  limit: number;
  /** 服务端分段耗时（ms），只为观测：写进 `x-jobs-search-timing` 响应头 + 一行 `[jobs-search]` 日志。 */
  timing?: SearchTiming;
};

export type SearchTiming = {
  path: "fts" | "scan";
  sortBy: string;
  anon: boolean;
  rows: number;
  /** 候选是否来自进程内缓存（true = 这次没跨库拉行）。 */
  cacheHit: boolean;
  /** 候选取数（含跨库传输 + node-pg 解析）。 */
  fetchMs: number;
  /** JS 打分 + 精筛 + 排序 + 散列。 */
  scoreMs: number;
  /** 命中页回补 + 真实总数计数（并行，取两者之长）。 */
  tailMs: number;
  totalMs: number;
};

const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
// 2026-09-17 立：线上匿名 sortBy=match 冷路径正文按需传之后仍 10.8~13s，从外面量不出钱花在哪。
// 这一行是分段账本；先看它的数字再动代码（先量后改）。
function logSearchTiming(t: SearchTiming): void {
  console.log(
    `[jobs-search] path=${t.path} sortBy=${t.sortBy} anon=${t.anon} rows=${t.rows} cache=${t.cacheHit ? "hit" : "miss"} ` +
      `fetch_ms=${Math.round(t.fetchMs)} score_ms=${Math.round(t.scoreMs)} tail_ms=${Math.round(t.tailMs)} total_ms=${Math.round(t.totalMs)}`,
  );
}

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

// 公司类型下推（FTS / 扫描两条候选路径共用同一份实现，保证 SQL 字节级一致，杜绝两处各写一套漂移）：
// named tiers 走 ilike any，中小厂走「不命中任一 named 前缀」的负向匹配；与 classifyCompanyTier
// 同一份 patterns、同大小写不敏感子串，保持 SQL_PUSHED 的等价性。
function appendCompanyTierWhere(conds: string[], params: unknown[], companyTier: string) {
  const tierSel = splitMultiValue(companyTier);
  if (!tierSel.length) return;
  const { named, includeSmb } = companyTierPatterns(tierSel);
  const ors: string[] = [];
  if (named.length) {
    const ph = named.map((p) => {
      params.push(p);
      return `company ilike $${params.length}`;
    });
    ors.push(`(${ph.join(" or ")})`);
  }
  if (includeSmb) {
    const ph = NAMED_TIER_PATTERNS.map((p) => {
      params.push(p);
      return `company not ilike $${params.length}`;
    });
    ors.push(ph.length ? `(${ph.join(" and ")})` : "true");
  }
  if (ors.length) conds.push(`(${ors.join(" or ")})`);
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
  const arms = recruitmentPrefilterArms(jobType);
  if (arms) conds.push(`((${arms[0]}) or (${arms[1]}))`);
}

/**
 * 预筛的两支（按 recruitment_category 是否为 NULL 切开，**互斥**）：[已分类支, 待回填支]。
 * appendRecruitmentPrefilter 把它们 OR 起来；扫描路径的 recruitmentUnionSql 把它们拆成两条各自按索引取数的子查询。
 * 两处共用这一份字符串，不存在两套口径。
 */
function recruitmentPrefilterArms(jobType: string): [string, string] | null {
  if (jobType !== "校招" && jobType !== "实习" && jobType !== "社招") return null;

  // ── 主路：查物化列，与 JS 的 jobFilterMatch 逐字同义 ──────────────────────────────
  // 这两列由入库时的 JS 权威规则算好（crawler/recruitment_classify.py → scripts/classify-recruitment.js），
  // 所以这里不是「近似超集」而是**精确等价**：
  //   · 选 校招/实习：有明确依据 且 类型相符才留（无依据的岗 JS 会淘汰，这里也淘汰）
  //   · 选 社招    ：只淘汰「有明确依据且不是社招」的（无依据的岗 JS 放行降级，这里也放行）
  const exact =
    jobType === "社招"
      ? "not (recruitment_explicit and recruitment_category <> '社招')"
      : `recruitment_explicit and recruitment_category = '${jobType}'`;

  // ── 兜底路：recruitment_category is null = 「还没算」，**不等于「不是」** ──────────────
  // 什么时候会是 null：一次性回填尚未覆盖到、或入库时分类降级（没装 node / 超时）。
  // 这时必须退回原来的信号超集，绝不能当它不存在——否则新抓来的岗会从筛选结果里凭空消失，
  // 而新岗恰恰是用户最想看的。社招本来就不下推（默认态、大头），兜底路直接放行。
  return [
    `recruitment_category is not null and ${exact}`,
    `recruitment_category is null and ${legacyRecruitmentSuperset(jobType)}`,
  ];
}

/**
 * 校招 / 实习按新鲜度取数：把预筛拆成两支各自 `order by first_seen_at desc limit N`，再 Merge Append（2026-09-23）。
 *
 * 为什么：预筛是「已分类 OR 待回填」一个 OR，规划器只能沿 (status, first_seen_at) 按时间翻、逐行回表判类型。
 * 实习只占 active 6% → 凑满 1000 行要回表 2.9 万行；库机 2GB 内存装不下 2.26GB 数据，冷缓存时每行 0.1~0.3ms，
 * 同一条「只选实习」热 76ms / 冷 2.1~4.6s。拆开后已分类支走 idx_jobs_active_recruitment_first_seen
 * （Index Cond: 类型 = X and 明确），待回填支走同一索引的 IS NULL 段：香港库 26,573 → 2,743 buffer。
 * 等价性：两支按 recruitment_category 是否为 NULL 互斥，并集 = 原 OR；全集按 first_seen_at 倒序的前 (offset+limit) 行
 * 必然落在「每支各自的前 (offset+limit) 行」里。真库对拍 1000 行（按 first_seen_at, id 定序取 md5）逐条相同。
 * 社招不拆：它是大头，按时间翻很快就凑满，而且「已分类支」是否定条件，走不了索引。
 * 参数：比普通形态多一个「内层 limit = 外层 limit + offset」，由调用方追加在最后。
 */
function recruitmentUnionSql(
  columns: string,
  conds: string[],
  prefilterAt: number,
  jobType: string,
  lastParam: number,
): string | null {
  if (jobType !== "校招" && jobType !== "实习") return null;
  const arms = recruitmentPrefilterArms(jobType);
  if (!arms || prefilterAt < 0 || prefilterAt >= conds.length) return null;
  const branch = (arm: string) => {
    const cs = [...conds];
    cs[prefilterAt] = `(${arm})`;
    return `(select ${columns} from jobs where ${cs.join(" and ")} order by first_seen_at desc limit $${lastParam + 3})`;
  };
  return (
    `select * from (${branch(arms[0])} union all ${branch(arms[1])}) u ` +
    `order by first_seen_at desc limit $${lastParam + 1} offset $${lastParam + 2}`
  );
}


/**
 * 旧的「正向信号并集」超集，现在只服务于 recruitment_category 尚未算出的行。
 *
 * ⚠️ 它与 JS 的分层裁决**结构不同**（这里是「有任一信号就捞」，JS 是「高可信信号可否决低可信」），
 * 所以它只能当超集用、不能当等价判据 —— 这正是物化那两列的原因：live 实测「深圳+校招」4354 条
 * 候选里 43% 是被它捞进来又被 JS 扔掉的（其中 37% 挂在社招门户下，而这里压根没看门户信号）。
 * ⚠️ 正则须与 china-keyword-expansion 的 sourceDeclaredCategory / hasStrongCampusSignal /
 * hasInternSignal 对齐；作为超集，宁可放宽不可收紧（收紧=漏掉真岗，精度红线）。
 */
function legacyRecruitmentSuperset(jobType: string): string {
  if (jobType === "校招") {
    return (
      "((job_type ~* '(校招|校园招聘|应届|管培生|管理培训生|留学生专项|campus|new\\s+grad|university\\s+graduate|entry[-\\s]?level)'" +
      " or jd_url ~* '(xiaozhao|campus)'" +
      // 老版 wt 的平台渠道常量（recruitmentCategory 层4 认 recruitType=1 → 校招；12 是实习，下面排除）。
      // 超集只许放宽：job_type 不带标签的 wt 校招行（2026-09-18 实测 83 行）在列为 NULL 期间也要捞到。
      " or jd_url ~* '[?&]recruitType=1(?![0-9])'" +
      " or (coalesce(title,'')||' '||coalesce(summary,'')) ~* '(应届|[0-9]{2,4}届|校园招聘|校招|管培生|管理培训生|留学生专项|new\\s?grads?|university\\s+graduate|entry[-\\s]?level|campus\\s?(recruit|hiring)|graduate\\s+program)'" +
      " or company ~* '(校招|校园招聘)')" +
      " and (job_type is null or job_type !~* '(社招|社会招聘|全职|experienced|professional|full.?time)')" +
      // 排除实习：带实习信号的行在 recruitmentCategory 里只会落到 实习（层1 标题 / 层2b 渠道）或 社招（层2 经验门），
      // 绝不可能再被判成校招，所以从校招超集里剔掉是安全的。
      // ⚠️ intern 必须**两侧**词边界（PG 用 \y）：否则 international / internal / internet 会被当实习剔掉
      //    ——同款裸子串坑在 crawler 上实锤误标过 27,824 个岗。
      // ⚠️ url 只认**路径段** /shixi /intern，不认 `?postType=intern`：实测 wecruit 有 10 个「27届」
      //    真校招岗带该参数，按查询参数算会被误杀。
      " and not (coalesce(job_type,'') ~* '(实习|\\yintern(ship)?s?\\y)'" +
      " or coalesce(title,'') ~ '(实习|shixi)' or coalesce(title,'') ~* '\\yintern(ship)?s?\\y'" +
      " or coalesce(nullif(jd_url,''), apply_url, '') ~* '/(shixi|intern)(/|\\?|$)'))"
    );
  }
  if (jobType === "实习") {
    return "(job_type ~* '(实习|intern)' or title ~* '(实习|shixi|intern)' or jd_url ~* '(shixi|intern)' or jd_url ~* '[?&]recruitType=12(?![0-9])')";
  }
  return "true"; // 社招=默认态·大头，无信号可下推 → 兜底路全放行，交给 JS 精筛
}

/** 校招专区头部的「库存量级」计数（校招 / 实习各一个）。 */
export type CampusLibraryCounts = { campus: number; intern: number };

/**
 * 「校招岗位库现在有多少个在招岗」—— 精确计数，**不是**某次搜索的匹配数。
 *
 * 为什么不能拿搜索结果的 `total` 当这个数：`total` 是「可翻页条数」，候选撞窗口上限时它只是
 * 「取到这么多」（实测 `jobType=校招` 回 `total=1000, capped=true, exactTotal=null` → 只能显示
 * 「1000+」）。`exactTotalWhenCapped` 在这里主动弃权是对的——库里还有约 2,954 行
 * `recruitment_category is null`，它们走「信号超集」兜底分支，那条不是充分条件。
 * 所以头部另给一个库存量级的确定数字，和 `/jobs` 的 `JobLibraryStat` 是同一个先例：
 * 两个数字措辞刻意不同（头部 = 库里有多少 / 列表行 = 你这组筛选匹配到多少）。
 *
 * ⚠️ **口径必须与 `appendRecruitmentPrefilter` + `appendCurrentSeasonWhere` 逐条对齐**，
 * 尤其 `recruitment_explicit` 这一条不能少：少了它是 75,744（2026-09-18 实测），而列表只给得出
 * 69,138 —— 头部与列表两个数字当场打架，用户会读成「有 6,606 个岗被藏了」。
 * ⚠️ 实测 `Parallel Seq Scan` 515ms / 13.3 万 buffers，调用方**必须缓存**（见 app/campus/page.tsx）。
 */
export async function countCampusLibrary(
  prefs: UserPreferences | null,
): Promise<CampusLibraryCounts> {
  const conds = ["status = 'active'", "recruitment_explicit", "recruitment_category in ('校招','实习')"];
  const params: unknown[] = [];
  appendJobScopeWhere(conds, params, prefs, {});
  // 与 appendCurrentSeasonWhere 同一条往届门；这里 where 已经限定在校招/实习两桶内，
  // 故不必再带 `recruitment_category in (...)` 那半截（那半截在通用路径上是为了别误伤社招）。
  params.push(currentGradClass());
  conds.push(`(grad_class is null or grad_class >= $${params.length})`);
  const rows = await jobsQuery<{ campus: number; intern: number }>(
    `select count(*) filter (where recruitment_category = '校招')::int as campus,` +
      ` count(*) filter (where recruitment_category = '实习')::int as intern` +
      ` from jobs where ${conds.join(" and ")}`,
    params,
  );
  const row = rows[0];
  return { campus: Number(row?.campus ?? 0), intern: Number(row?.intern ?? 0) };
}

/**
 * 拿来做「偏好优先」的 tsquery：把用户偏好词按搜索框同一套词表展开后 OR 起来。
 *
 * ⚠️ **只放在本次候选集里还有区分度的维度**。用户已经按「深圳」筛过了 → 候选全在深圳 →
 * 再把 target_locations 放进来，每一行都算「偏好命中」，排序等于没排。这不是理论顾虑：
 * live 实测「深圳 + 社招」15,350 个候选，带上城市词命中 15,350（0 区分度），
 * 剔除后降到 4,642 —— 正好装得进 8000 的窗口，于是**能拿方向/公司加分的岗一个都不会被砍**。
 * 被剔掉的那一维在候选集内是常量，窗口内外同样拿得到那份分，不影响相对排序。
 *
 * 词数封顶是为了别让 tsquery 无限膨胀（简历技能可能有几十条）；排在前面的是目标岗位，
 * 也正是加分最高（+30/+15）的一类，截掉尾巴不影响「高分岗一定在窗口内」这个性质。
 */
const PREF_SIGNAL_TERM_CAP = 40;

function preferenceTsquery(filters: Filters, prefs: UserPreferences | null): string | null {
  if (!prefs) return null;
  const includeOverseasLexicon = effectiveJobScope(prefs) !== "domestic";
  const groups = scoringSignalGroups(prefs, { overseasProfile: includeOverseasLexicon });
  const signals = [
    ...groups.direction,
    // 用户自己填了公司/城市 → 候选已按它收窄，这一维在集合内是常量，放进来只会稀释区分度。
    ...(filters.company.trim() ? [] : groups.companies),
    ...(splitMultiValue(filters.city).length ? [] : groups.locations),
  ];
  const terms = signals
    .slice(0, PREF_SIGNAL_TERM_CAP)
    .flatMap((t: string) => ftsCandidateTerms(t, { includeOverseasLexicon }));
  return buildTsquery(terms, [], []);
}

/**
 * 候选窗口的排序 —— 它真正决定的是「装不下时砍掉谁」。
 *
 * 此前 FTS 那条查询**根本没有 order by**（为了让 planner 用 GIN bitmap 直接取命中行）：
 * 线上「深圳 + 社招」有 15,350 个候选、窗口只有 8000，砍掉哪 7,350 个纯看执行计划 →
 * 「按匹配度」排出来的第一页其实只是「任意一批里最匹配的」。这是撞上限最伤的一处，
 * 比数字不准更伤——数字看得见，排序偏了看不见。
 *
 * 实测这笔排序很便宜（香港库「深圳+社招」15,350 行：无序 147ms / 按新鲜度 59ms /
 * 真实画像的偏好优先 187ms），而且走 5 分钟候选缓存只付一次，所以直接让截断变得有意义：
 *   · 按发布时间排 → `first_seen_at desc`：被砍掉的确实更旧，**窗口内的分页与全集一致**。
 *   · 按匹配度排 → 「命中用户偏好的」优先，再按新鲜度补满。可论证：scoreJob 里 10 分以上的
 *     加分项（岗位 +30/+15、城市 +20、公司 +15、补充词 +5/+2.5）**全部来自偏好词**，所以
 *     偏好命中的行必定进窗口；窗口外的行最多只剩「近 7 天 +10」，而补位恰恰按新鲜度排
 *     → 被砍掉的确实是分数最低的一批。
 *
 * ⚠️ 已知边界：`search_doc` 只含 title/company/location/job_type，**不含 JD 正文**
 *   （见 jobs-db/schema.sql 的 jobs_set_search_doc）→「只在正文里命中偏好词」的岗不算偏好命中。
 *   这不是这里新引入的不一致：关键词搜索一直是标题锚定的（同一个 search_doc）。要消掉它得给
 *   正文单独建 FTS，是另一件事。
 * ⚠️ 排序参数进了候选缓存的 key → 不同偏好的用户不再共用同一份候选。内测规模下可接受；
 *   要恢复共享只能牺牲上面那条正确性，别为省缓存把它换回去。
 * ⚠️ 不要加 `nulls last`：索引是 (status, first_seen_at desc) 即 NULLS FIRST，加了就用不上索引；
 *   而 first_seen_at 线上 0 个 NULL（有 default now()），两者结果本来就一样。
 */
function candidateOrderBy(
  params: unknown[],
  filters: Filters,
  prefs: UserPreferences | null,
): string {
  const fresh = "first_seen_at desc";
  if (filters.sortBy === "newest") return ` order by ${fresh}`;
  const prefQuery = preferenceTsquery(filters, prefs);
  if (!prefQuery) return ` order by ${fresh}`; // 无偏好时打分只剩「近 7 天 +10」→ 按新鲜度排就是对的
  params.push(prefQuery);
  return ` order by (search_doc @@ to_tsquery('simple', $${params.length})) desc, ${fresh}`;
}

// 扫描路径 + 登录 + 按匹配度排：把 lib/scoring.scoreJob 里能下推的四项搬进 SQL 当粗排键，
// 让「JS 精排要看的那批」尽量落在窗口前部——窗口从 28,000 缩到几千行，带宽是香港机的硬上限（见 CLAUDE.md）。
// 方向项用 FTS 近似 keywordMatchTier（同一份 ftsCandidateTerms 展开），城市/公司项与 scoreJob 同为子串命中。
// ⚠️ 排序 tsquery 仍压在**最后一个**参数上（tests/jobs-store-candidate-window 按它定位），城市/公司数组在它前面。
const FTS_GENERIC_TOKENS: Record<string, number> = (ftsTokenDf as { tokens: Record<string, number> }).tokens;
/** 一个检索词是否「泛词」：它的全部 token 在 active 岗里都是高频 token（文档频率 ≥ 阈值）。无 token 视为泛词（不进收窄）。 */
export function isGenericFtsTerm(term: string): boolean {
  const toks = queryTokens(term);
  if (!toks.length) return true;
  return toks.every((t) => FTS_GENERIC_TOKENS[t] !== undefined);
}
/** 收窄候选用的方向词：岗位名本身 ∪ 岗位名的非泛化扩展（不含关键词/技能）。理由见 Prescore.candidateWhere 注释。 */
export function narrowDirectionTerms(prefs: UserPreferences, includeOverseasLexicon: boolean): string[] {
  const roles = scoringTargetRoles(prefs, includeOverseasLexicon).slice(0, PREF_SIGNAL_TERM_CAP);
  const out = new Set<string>();
  for (const r of roles) {
    out.add(r);
    for (const t of ftsCandidateTerms(r, { includeOverseasLexicon })) if (!isGenericFtsTerm(t)) out.add(t);
  }
  return [...out];
}

type Prescore = {
  orderBy: string;
  /**
   * 只给**候选查询**用的收窄条件（计数查询不带它，总数口径不变）。
   * 2026-09-18 线上分段账本：登录 match 无筛选冷路径 fetch 5.5s，只拉 1000 行且不传正文——慢的不是带宽，
   * 是 `order by 粗排键` 对全部 33.8 万 active 行逐行算 tsquery / ilike 再 top-N（EXPLAIN：Parallel Seq Scan，
   * 13.5 万 buffer，库上 2.3~2.6s；函数里叠 2 核争用 + 传输 → 5.5s）。
   * 把「方向词 GIN 命中 OR 7 天内新岗」下推到 where：两条都能走索引（jobs_search_doc_gin +
   * jobs_status_first_seen_idx 的 BitmapOr），同一画像 EXPLAIN 493ms、窗口照样填满 1000 行。
   * 被排除的只有「不命中方向、又超过 7 天、只靠城市/公司加分」的行（粗排分 ≤35，且 7 天内新岗单独就有 1.7 万行，
   * 窗口不会因此变空）。等价性对拍见 docs/reviews/2026-09-17 §11。
   * ⚠️ 收窄用的方向 tsquery（narrowQuery）不能复用排序键那个宽查询，也不能只用原始词——两头都试过、都错：
   * · 宽查询 = 全部方向词（岗位名 + 关键词/技能）经 ftsCandidateTerms 扩展，创始人账号 236 个 OR 子句、全库 36% 的岗命中
   *   → 规划器放弃 GIN 走 Parallel Seq Scan，线上 fetch 6.5s，与没收窄一样慢；
   * · 只用原始岗位名 → 「财务会计」这位用户第一页重合率 95% → 17%：真值里大量只写「会计」的老岗被挡在候选外。
   * 现行口径（见 narrowDirectionTerms）：**岗位名本身 ∪ 岗位名的非泛化扩展**。「泛化」按 lib/fts-token-df.json
   * （active 岗 search_doc 的 token 文档频率，脚本 scripts/fts-token-df/gen.mjs）判：一个词的全部 token 都 ≥ 阈值才算泛
   * （「产品经理」三个 bigram 都高频但整短语只命中 1.6%，所以岗位名本身永远保留）。关键词/技能不进收窄条件。
   * 实测：财务会计 8,970 行（扩展一个不丢）、后端工程师 5,901（丢「工程师」「java」）、创始人 27,896 行 897ms（原 5.8s）。
   * 没有岗位名时不收窄——那时只剩城市/公司/7 天三项，全表扫是老路径，量级同旧。
   */
  candidateWhere: string | null;
};

// 运维开关：出事改 Vercel 变量退回「全窗 JS 精排」，不用重新部署（对拍脚本也拿它取真值）。
function prescoreDisabled(): boolean {
  return (process.env.JOBS_MATCH_PRESCORE || "").toLowerCase() === "off";
}

function prescoreOrderBy(
  params: unknown[],
  filters: Filters,
  prefs: UserPreferences | null,
  options: { candidateWhere: boolean },
): Prescore | null {
  if (filters.sortBy !== "match" || !prefs) return null;
  if (prescoreDisabled()) return null;
  const includeOverseasLexicon = effectiveJobScope(prefs) !== "domestic";
  const groups = scoringSignalGroups(prefs, { overseasProfile: includeOverseasLexicon });
  const dirTerms = groups.direction
    .slice(0, PREF_SIGNAL_TERM_CAP)
    .flatMap((t: string) => ftsCandidateTerms(t, { includeOverseasLexicon }));
  const dirQuery = buildTsquery(dirTerms, [], []);
  const narrowQuery = buildTsquery(narrowDirectionTerms(prefs, includeOverseasLexicon), [], []);
  const pieces: string[] = [];
  const cities = splitMultiValue(filters.city).length ? [] : groups.locations;
  if (cities.length) {
    params.push(cities.map((c: string) => `%${escapeLike(c)}%`));
    // ⚠️ 每一项都要 `is true`：location/company 为 NULL 时 ilike 返回 NULL，整个和会变成 NULL，
    // 而 `order by … desc` 默认 NULLS FIRST → 没写城市的岗全排到最前面（2026-09-17 对拍当场抓到：重合率 0%）。
    pieces.push(`((location ilike any($${params.length}::text[])) is true)::int * 20`);
  }
  const companies = filters.company.trim() ? [] : groups.companies;
  if (companies.length) {
    params.push(companies.map((c: string) => `%${escapeLike(c)}%`));
    pieces.push(`((company ilike any($${params.length}::text[])) is true)::int * 15`);
  }
  pieces.push("((first_seen_at > now() - interval '7 days') is true)::int * 10");
  let candidateWhere: string | null = null;
  if (dirQuery) {
    // ⚠️ 只有调用方真会把 candidateWhere 拼进 SQL 时才压这个参数：绑定了 SQL 里没引用的参数 PG 直接报错
    //（2026-09-18 线上实锤：FTS 路径没用收窄条件却压了参数 → 抛错 → 被 searchJobsStore 的 catch 吞掉、静默退化到扫描路径）。
    if (narrowQuery && options.candidateWhere) {
      // 先压窄查询、再压宽查询：保住「候选查询最后一个参数 = 排序 tsquery」的既有契约（tests/jobs-store-candidate-window）。
      params.push(narrowQuery);
      const dir = `search_doc @@ to_tsquery('simple', $${params.length})`;
      const recent = "first_seen_at > now() - interval '7 days'";
      // 选了校招 / 实习时按招聘类型拆开（2026-09-23）：外层预筛本来就只留「该类型 / 待回填（NULL）」两种行，
      // 所以 (方向 or 7天) ≡ (方向 and 该类型) or (7天 and 该类型) or (待回填 and (方向 or 7天))，候选集逐行不变。
      // 拆开后三支各走索引再 BitmapOr：方向支与 idx_jobs_active_recruitment_first_seen 做 BitmapAnd，7 天支直接按
      // (类型, 首见时间) 取，待回填支只有一千多行——不再把 7 天内全部 4.5 万行、方向词命中的全部行（含社招、海外）回表再丢。
      // 香港库三个真实画像：回表块 3.7 万 → 1.4 万；磁盘读 2.1 万 → 百级。方向词宽的画像（33 个 OR 子句）1,029 → 591ms（热）。
      // ⚠️ 别写成 `(方向 or 7天) and (该类型 or 待回填)`：规划器会把它当普通过滤，照旧回表（实测计划不变）；
      //    也别让「待回填」分别并进前两支：方向词 GIN 会被扫两遍（宽画像每遍 ~250ms）。
      const stage = filters.jobType === "校招" || filters.jobType === "实习" ? filters.jobType : null;
      const rc = `recruitment_category = '${stage}'`;
      candidateWhere = stage
        ? `((${dir} and ${rc}) or (${recent} and ${rc}) or (recruitment_category is null and (${dir} or ${recent})))`
        : `(${dir} or ${recent})`;
    }
    params.push(dirQuery);
    pieces.unshift(`((search_doc @@ to_tsquery('simple', $${params.length})) is true)::int * 30`);
  }
  if (!dirQuery && !cities.length && !companies.length) return null; // 没有可粗排的信号 → 退回原排序
  return { orderBy: ` order by (${pieces.join(" + ")}) desc, first_seen_at desc`, candidateWhere };
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

/** 候选里落在「SQL 也会一并排除」的隐藏岗（ignored / applied）条数。 */
function countHidden(rows: Array<{ id?: string }>, hiddenIds: Set<string>): number {
  if (!hiddenIds.size) return 0;
  return rows.reduce((n, r) => n + (r.id && hiddenIds.has(r.id) ? 1 : 0), 0);
}

/**
 * 候选撞上限（capped）时，用一条 count(*) 拿**真实匹配总数**。
 *
 * 不这么做的话，前端只能把「取数上限」当真实值展示：线上「深圳 + 社招」候选撞 FTS_CAP=8000，
 * 页面就写「8000 个匹配岗位」，而库里符合条件的其实是 15,290 个（2026-09-03 实测）。
 *
 * 计数用的**就是取候选那条 where**（同一份 conds/params，不另写一套），所以不存在「两套条件漂移」；
 * 需要成立的只有一个方向：**where 成立 ⇒ jobFilterMatch 放行**。四道门保证它，任一不满足就返回
 * null，前端退回诚实的「N+」—— 宁可不给数字，也不给另一个错的确定数字：
 *   ① 结构门：还有只能在 JS 里判的条件在生效（关键词/职能/学历/经验…）→ 不给。
 *   ② 偏好门：exclude_keywords 命中即硬删，而 SQL 看不到 JD 正文 → 不给。
 *   ③ 运行时自检：where 若真是充分条件，这批候选里除了 SQL 一并排除的 ignored/applied 之外，
 *      **一个都不该被 JS 淘汰**。不成立 = 等价性已经漂了（有人给 jobFilterMatch 加了条件却没同步
 *      上面的归类表）→ 不给。这道门不依赖任何人记得改代码，是最后一道保险。
 *   ④ recruitment_category 尚未算出的行走的是「信号超集」兜底分支，那条不是充分条件 → 结果集里
 *      只要还有这种行，数就不可信。
 */
const CAPPED_COUNT_TTL_SECONDS = 300;
type CappedCountRow = { total: number; unclassified: number };
const queryCappedCount = async (sql: string, params: unknown[]) =>
  (await jobsQuery(sql, params)) as CappedCountRow[];
const cachedCappedCountInner = unstable_cache(queryCappedCount, ["jobs-search-capped-count-v1"], {
  revalidate: CAPPED_COUNT_TTL_SECONDS,
});
// unstable_cache 只在 Next 请求上下文里可用；单测 / 独立脚本里抛「incrementalCache missing」→ 退回直查
// （与 lib/jobs-store/read.ts 的 getCompanyActiveAggregates 同一做法，只吞这一种错）。
async function cachedCappedCount(sql: string, params: unknown[]): Promise<CappedCountRow[]> {
  try {
    return await cachedCappedCountInner(sql, params);
  } catch (error) {
    if (!(error instanceof Error && /incrementalCache missing/i.test(error.message))) throw error;
    return queryCappedCount(sql, params);
  }
}

async function exactTotalWhenCapped(args: {
  conds: string[];
  params: unknown[];
  filters: Filters;
  prefs: UserPreferences | null;
  hiddenIds: Set<string>;
  scanned: number;
  hiddenScanned: number;
  rankedLength: number;
}): Promise<number | null> {
  const { conds, params, filters, hiddenIds, scanned, hiddenScanned, rankedLength } = args;
  if (!filtersFullyPushedToSql(filters)) return null; // ①
  // ② 排除词自 2026-09-17 起已下推 SQL（appendExcludeWhere，与 scoreJob 同字段集），不再弃权；
  //    若两边口径漂了，③ 会兜住（JS 淘汰的行数对不上即弃权）。
  if (rankedLength !== scanned - hiddenScanned) return null; // ③

  const countParams = [...params];
  const where = [...conds];
  if (hiddenIds.size) {
    countParams.push([...hiddenIds]);
    where.push(`not (id = any($${countParams.length}::uuid[]))`);
  }
  try {
    // ④ 先判，别先数（2026-09-23）：选了招聘类型时，结果集里只要有一行「还没分类」，下面的计数算完也会被 ④ 丢掉。
    // 而 active 里几乎总有这种行（当天实测 1,453 行，全是近 3 天新抓的），于是 /campus 默认态、「只选实习」
    // 每次都白跑一遍 33 万行全表计数（库上 0.6~2.4s，与回补并行 → 整段 tail 就是它）。
    // 这条存在性查询走 jobs_recruitment_unclassified_idx（只含未分类行），毫秒级；判定与 ④ 完全同一条件。
    if (filters.jobType) {
      const pending = await jobsQuery<{ pending: boolean }>(
        `select exists(select 1 from jobs where ${where.join(" and ")} and recruitment_category is null) as pending`,
        countParams,
      );
      if (pending[0]?.pending !== false) return null; // ④（查询异常走下面的 catch，同样退回「N+」）
    }
    // 跨实例数据缓存（2026-09-18）：这条 count(*) 只由 where 决定、与用户无关，结果就两个整数；
    // 线上冷路径它是 33 万行并行全表扫 0.55~0.94s，与回补展示列并行后 tail ≈ 它。此前走 fetchCandidates 的
    // 进程内缓存——每次请求常落到不同实例，首屏基本不命中（同一 tab 三连打三个实例）。
    // ⚠️ 缓存函数体内不读 cookies()/headers()；key 由 sql + params 序列化而来，翻页/换用户同 where 共用一份。
    const rows = await cachedCappedCount(
      `select count(*)::int as total, count(*) filter (where recruitment_category is null)::int as unclassified ` +
        `from jobs where ${where.join(" and ")}`,
      countParams,
    );
    const row = rows[0];
    if (!row) return null;
    if (filters.jobType && row.unclassified > 0) return null; // ④
    // 真实总数不可能比「已经排出来的条数」还少；小于就说明这个数不可信。
    return row.total >= rankedLength ? row.total : null;
  } catch {
    // 计数只是展示优化，挂了就退回「N+」，绝不拖垮搜索本身。
    return null;
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
  const t0 = now();
  const fetchMeta: { cacheHit?: boolean } = {};
  // 「默认会被隐藏」的岗位（忽略/已投递）。⚠️ 无偏好时 scoreJob 直接返回 hidden_reason=null，
  // 用户操作根本不生效（lib/scoring.ts），这里必须同口径，否则算真实总数时会多排除。
  const hiddenIds = prefs ? actionHiddenJobIds(actions, filters) : new Set<string>();
  // 最终排序仍由 JS filterAndRankJobs 权威执行；这里的 order by 只管「窗口装不下时砍掉谁」
  // （见 candidateOrderBy，实测不额外收费）。
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
  appendCompanyTierWhere(conds, params, filters.companyTier);
  // 校招/实习超集下推：只保留可能命中的行，别把大量社招岗跨洋传过来（JS 仍权威判定）。
  appendRecruitmentPrefilter(conds, filters.jobType);
  appendCurrentSeasonWhere(conds, params);
  appendExcludeWhere(conds, params, prefs);
  // 走同一份候选缓存：候选集只由 where 决定（已全部进 key），而**翻页是在 JS 里 slice 的**——
  // 第 2 页的 SQL 与第 1 页逐字节相同。不缓存的话每翻一页都要把几千行重新跨库拉一遍再解析一遍，
  // 香港库实测这段占该接口服务端耗时的绝大部分（4354 行 ≈ 4.8MB）。
  // ⚠️ 排序/正文门参数走 candidateParams，`params` 保持「只含 where」——exactTotalWhenCapped 要拿它拼
  // count 查询，多带一个用不到的绑定参数 PG 会直接报错。
  const candidateParams = [...params];
  // 先压正文门参数、再压排序参数：让「候选查询最后一个参数 = 排序 tsquery」这个既有契约继续成立
  // （tests/jobs-store-candidate-window 按它定位排序参数）。
  const columns = candidateColumns(candidateSummaryExpr(candidateParams, filters, prefs));
  // 登录 + match：与扫描路径同一套 SQL 粗排 + 1000 窗口（2026-09-18）。此前带城市/关键词的登录默认态
  // 一次拉满 FTS_CAP=8000 行再 JS 全打分：线上账本 fetch 1.4s + score 1.6s；候选集本身已被 FTS 收窄，
  // 不再另加 candidateWhere。窗口装不下时（capped）照旧走 exactTotalWhenCapped 给真实总数。
  const prescore = prescoreOrderBy(candidateParams, filters, prefs, { candidateWhere: false });
  const orderBy = prescore?.orderBy ?? candidateOrderBy(candidateParams, filters, prefs);
  // 匿名（无偏好）也用同一个 1000 窗，别拉满 FTS_CAP（2026-09-18）：
  // prescoreOrderBy 第一行就是 `if (!prefs) return null`，于是**登录用户走 1000 窗、匿名反而走 8000 窗**——
  // 正好反了。ux-walkthrough 上线第一天就报 `search_city TTFB 20.1s`，线上复测冷实例 8~12s。
  // 库上量因（香港库，`city=北京`，同一条候选 SQL 只改 limit）：
  //     limit 8000 → 10,468ms  ·  limit 2000 → 507ms  ·  limit 1000 → 17ms
  // 根因不是索引选错（强制 CTE 走 GIN 也要 8.6s，因为「北京」命中 5.6 万行都得取堆），而是**取太多行**：
  // 计划器沿 jobs_status_first_seen_idx 按时间倒序边扫边过滤，凑够 1000 个北京岗只要扫最近几千行，
  // 凑够 8000 个就得一路扫到很久以前。
  // 等价性：匿名无偏好时 scoreJob 打分恒为 0（见 lib/scoring.ts），排序退化成纯新鲜度，而候选查询本身就是
  // `order by first_seen_at desc` —— 取到的 1000 行就是 8000 行的前 1000 行，且 JS 精筛对无偏好用户几乎不拒
  // （没有偏好就没有 role/location/industry mismatch），第一页 60 条不受影响。
  // 撞窗口时的计数照旧走 exactTotalWhenCapped / formatMatchTotal（给不出确定数字就显示「N+」，不会给错数字）。
  // 匿名 + 筛选全下推时也用 1000 窗，别拉满 FTS_CAP（2026-09-18）：
  // prescoreOrderBy 第一行是 `if (!prefs) return null`，于是**登录用户走 1000 窗、匿名反而走 8000 窗**，
  // 正好反了。ux-walkthrough 上线第一天就报 `search_city TTFB 20.1s`，线上复测冷实例 8~12s。
  // 库上量因（香港库 `city=北京`，同一条候选 SQL 只改 limit）：
  //     limit 8000 → 10,468ms  ·  limit 2000 → 507ms  ·  limit 1000 → 17ms
  // 根因不是索引选错（强制 CTE 走 GIN 仍要 8.6s——「北京」命中 5.6 万行都得取堆），而是**取太多行**：
  // 计划器沿 jobs_status_first_seen_idx 按时间倒序边扫边过滤，凑够 1000 个北京岗只需扫最近几千行，
  // 凑够 8000 个就得一路扫到很久以前。
  // ⚠️ 必须同时要求 filtersFullyPushedToSql：JS 侧不再过滤时「候选 = 结果」，而匿名无偏好的 scoreJob
  // 打分恒为 0（lib/scoring.ts）、排序退化成纯新鲜度，候选查询本身又是 order by first_seen_at desc
  // —— 取到的 1000 行**就是** 8000 行的前 1000 行，逐条相同，第一页 60 条可证等价。
  // 反过来，带 keyword/education/experience 这类 JS-only 筛选时 JS 会拒掉大量候选，1000 行可能不够填满一页，
  // 那种情况保持 FTS_CAP 不动。
  // 撞窗口时的计数照旧走 exactTotalWhenCapped / formatMatchTotal（给不出确定数字就显示「N+」，不会给错数字）。
  // 「有偏好记录、但一个可粗排的信号都没有」（没填岗位名/城市/公司，prescore 为 null）的登录用户按匹配度排时，
  // 打分同样只剩「7 天内 +10」、与 first_seen_at 同向，和匿名是同一回事（扫描路径早已这样归并，见 searchViaScan）。
  // 此前这里只认 `!prefs` → 这类用户反而拉满 8000 行（2026-09-23 实测「北京 + 实习」5.6 MB，慢请求里 4 次都是它）。
  // newest 不归并：JS 按 posted_at 排、SQL 按 first_seen_at 排，前 1000 行不保证是前 8000 行里 posted_at 最新的。
  // 开关 off 时 prescore 恒为 null，那是「取真值」不是「没信号」，保持 8000 窗。
  const noRankingSignals = !prefs || (filters.sortBy === "match" && !prescore && !prescoreDisabled());
  const anonymousFullyPushed = noRankingSignals && filtersFullyPushedToSql(filters);
  const cap = prescore || anonymousFullyPushed ? matchPrescoreWindow() : FTS_CAP;
  const rows = annotateSourceAdapter(
    await fetchCandidates(
      `select ${columns} from jobs where ${conds.join(" and ")}${orderBy} limit ${cap}`,
      candidateParams,
      fetchMeta,
    ),
    adapterBySource,
  );
  const tFetched = now();
  // 批量门店副本折叠放在排序**之后**：留下的是打分最高的那条。折叠后 ranked.length 变小 →
  // exactTotalWhenCapped 的自检门③ 自动失败 → 计数退回「N+」，这是对的（见 bulk-store-dedup 注释）。
  const rankedRaw = collapseBulkStoreJobs(annotateAndRank(rows, filters, prefs, actions));
  const ranked = filters.sortBy === "newest" ? rankedRaw : spreadByCompany(rankedRaw);
  const breakdown = countMatchBreakdown(ranked);
  const page = ranked.slice(offset, offset + limit);
  const capped = rows.length >= cap;
  const tScored = now();
  // 回补展示列与「真实总数」计数彼此无关，并行跑，别把 85ms 串到 TTFB 上。
  const [, exactTotal] = await Promise.all([
    hydratePageColumns(page), // 命中页回补展示列（候选阶段省传）
    capped
      ? exactTotalWhenCapped({
          conds,
          params,
          filters,
          prefs,
          hiddenIds,
          scanned: rows.length,
          hiddenScanned: countHidden(rows, hiddenIds),
          rankedLength: ranked.length,
        })
      : Promise.resolve(null),
  ]);
  const tEnd = now();
  const timing: SearchTiming = {
    path: "fts", sortBy: filters.sortBy, anon: !prefs, rows: rows.length, cacheHit: fetchMeta.cacheHit === true,
    fetchMs: tFetched - t0, scoreMs: tScored - tFetched, tailMs: tEnd - tScored, totalMs: tEnd - t0,
  };
  logSearchTiming(timing);
  return {
    jobs: page,
    total: ranked.length,
    exactCount: breakdown.exact,
    relatedSameFunction: breakdown.relatedSameFunction,
    relatedMissingInfo: breakdown.relatedMissingInfo,
    capped,
    exactTotal,
    offset,
    limit,
    timing,
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
  const t0 = now();
  const fetchMeta: { cacheHit?: boolean } = {};
  let fetchMs = 0;
  let scoreMs = 0;
  const need = offset + limit;
  const matched: ScoredJob[] = [];
  let nextOff = 0;
  let exhausted = false;
  // 实际翻过的候选行数 / 其中被 SQL 也会一并排除的隐藏岗数（算真实总数时的自检基线，见 exactTotalWhenCapped）。
  let scanned = 0;
  let hiddenScanned = 0;
  const hiddenIds = prefs ? actionHiddenJobIds(actions, filters) : new Set<string>();
  const conds = ["status = 'active'"];
  const params: unknown[] = [];
  appendJobScopeWhere(conds, params, prefs, filters);
  appendPostedWithinWhere(conds, params, filters.postedWithin);
  appendCompanyTierWhere(conds, params, filters.companyTier); // 与 FTS 路径同一份实现，稀疏标签独立浏览不漏岗
  const prefilterAt = conds.length; // 预筛在 conds 里的位置：recruitmentUnionSql 要把它拆成两支
  appendRecruitmentPrefilter(conds, filters.jobType); // 校招/实习超集下推，扫描也少翻无关行
  appendCurrentSeasonWhere(conds, params); // 往届校招/实习岗不进默认结果（与 FTS 路径同口径）
  appendExcludeWhere(conds, params, prefs);
  // 候选只取轻列 + 按需正文（与 FTS 路径同一套，见 candidateColumns / candidateSummaryExpr）：JS 打分/精筛只读这些列，
  // 纯展示列留到命中页再回补。此前这里拉的是全量 JOB_COLUMNS —— sortBy=match 默认要看满 SCAN_BUDGET=28000 行，
  // 多传的 6 个展示列 × 2.8 万行是白扔的带宽。
  // ⚠️ 别再试「用 json_agg 把整批行打成一个字段传回来」绕开 node-pg 逐字段解析：2026-09-02
  // 上线实测**更慢**（无筛选冷路径 19.0s → 20.5s），因为 json 要给每行每列写一遍 key 名，
  // 2.8 万行多出约 8MB 纯键名、字节 +33%，把省下的解析成本吃光了（已撤回，commit f011592）。
  // 同 FTS 路径：`params` 只留 where（计数要用），排序/正文门参数进 candidateParams。
  const candidateParams = [...params];
  const columns = candidateColumns(candidateSummaryExpr(candidateParams, filters, prefs)); // 先正文门、后排序（同 FTS 路径）
  const prescore = prescoreOrderBy(candidateParams, filters, prefs, { candidateWhere: true });
  const orderBy = prescore?.orderBy ?? candidateOrderBy(candidateParams, filters, prefs);
  const matchWindow = prescore ? matchPrescoreWindow() : SCAN_BUDGET;
  // 粗排的收窄条件只进候选 SQL，不进 conds（计数 / 真实总数仍按完整 where 算）。
  const candidateConds = prescore?.candidateWhere ? [...conds, prescore.candidateWhere] : conds;
  // 校招 / 实习 + 按新鲜度取（无粗排）：拆成两支各走索引（见 recruitmentUnionSql），多带一个「内层 limit」参数。
  const unionSql = !prescore && orderBy === " order by first_seen_at desc"
    ? recruitmentUnionSql(columns, candidateConds, prefilterAt, filters.jobType, candidateParams.length)
    : null;
  const sql =
    unionSql ??
    `select ${columns} from jobs where ${candidateConds.join(" and ")}${orderBy} ` +
      `limit $${candidateParams.length + 1} offset $${candidateParams.length + 2}`;
  const pageParams = (want: number, off: number) =>
    unionSql ? [...candidateParams, want, off, want + off] : [...candidateParams, want, off];
  const fetchRows = async (want: number, off: number) => {
    const s = now();
    try {
      return await jobsQuery(sql, pageParams(want, off));
    } finally {
      fetchMs += now() - s;
    }
  };
  // 吸收一批：打分/精筛后并入 matched，返回「是否已到底」（拿到的比想要的少 = 没更多了）。
  const absorb = (raw: unknown, want: number): boolean => {
    const s = now();
    try {
      return absorbInner(raw, want);
    } finally {
      scoreMs += now() - s;
    }
  };
  const absorbInner = (raw: unknown, want: number): boolean => {
    const rows: any[] = annotateSourceAdapter(raw as any[], adapterBySource);
    if (!rows.length) return true;
    scanned += rows.length;
    hiddenScanned += countHidden(rows, hiddenIds);
    const scored = sortAndFilterJobs(rows, prefs, actions, {
      showIgnored: true,
      showApplied: true,
    }) as ScoredJob[];
    for (const j of scored) {
      if (jobFilterTier(j, filters) !== null) matched.push(j);
    }
    return rows.length < want;
  };

  // 匿名 + 按匹配度排：没有偏好 → scoreJob 对每一行都返回 0 分，「按分排序」退化成纯新鲜度，
  // 与 newest 路径逐行同序。此时把 2.8 万行整窗拉回来只为了给一页 60 条排序，是白扔带宽
  // （2026-09-17 线上分段账本：匿名默认态 fetch 7.9~8.3s，打分 0.3s；香港机出口只有个位数 Mbps）。
  // → 匿名走下面攒够即停的逐页路径。有偏好时才需要看满窗口。
  // 2026-09-18：有偏好但**一个可粗排的信号都没有**（没填岗位名 / 城市 / 公司，prescore 为 null）的登录用户，
  // 此前会落回「拉满 SCAN_BUDGET=28000 行再 JS 排序」的老路径（线上 19s 那档）——而此时 scoreJob 能算的只剩
  // 「7 天内 +10」，按分排序退化成纯新鲜度，与匿名路径逐行同序。所以和匿名一样走下面攒够即停的逐页路径。
  // 这正是刚注册、还没填偏好就点开 /campus（默认全部校招岗、sortBy=match）的新用户会踩的那条路。
  if (filters.sortBy === "match" && prefs && prescore) {
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
    const s = now();
    const raw = await fetchCandidates(sql, pageParams(matchWindow, 0), fetchMeta);
    fetchMs += now() - s;
    // 候选被 candidateWhere 收窄过时，「拿到的比窗口少」不等于「全库看完了」→ 仍按 capped 走真实总数计数。
    exhausted = absorb(raw, matchWindow) && !prescore?.candidateWhere;
  } else {
    // newest 攒够 need 即停 → 保持逐页，不为了少几次往返把 2.8 万行全拉回来。
    // （并行取页已实测更慢/会 500，见上面常量位置的记录，别再改回去。）
    while (matched.length <= need && !exhausted && nextOff < SCAN_BUDGET) {
      exhausted = absorb(await fetchRows(DB_PAGE, nextOff), DB_PAGE);
      nextOff += DB_PAGE;
    }
  }
  // 与 FTS 路径同口径：门店副本折叠在排序之后（见 bulk-store-dedup 注释）。
  const sRank = now();
  const rankedRaw = collapseBulkStoreJobs(filterAndRankJobs(matched, filters));
  const ranked = filters.sortBy === "newest" ? rankedRaw : spreadByCompany(rankedRaw);
  const breakdown = countMatchBreakdown(ranked);
  const page = ranked.slice(offset, offset + limit);
  scoreMs += now() - sRank;
  const capped = !exhausted;
  const tScored = now();
  const [, exactTotal] = await Promise.all([
    hydratePageColumns(page), // 命中页回补展示列（候选阶段省传）
    capped
      ? exactTotalWhenCapped({
          conds,
          params,
          filters,
          prefs,
          hiddenIds,
          scanned,
          hiddenScanned,
          rankedLength: ranked.length,
        })
      : Promise.resolve(null),
  ]);
  const tEnd = now();
  const timing: SearchTiming = {
    path: "scan", sortBy: filters.sortBy, anon: !prefs, rows: scanned, cacheHit: fetchMeta.cacheHit === true,
    fetchMs, scoreMs, tailMs: tEnd - tScored, totalMs: tEnd - t0,
  };
  logSearchTiming(timing);
  return {
    jobs: page,
    total: ranked.length,
    exactCount: breakdown.exact,
    relatedSameFunction: breakdown.relatedSameFunction,
    relatedMissingInfo: breakdown.relatedMissingInfo,
    capped,
    exactTotal,
    offset,
    limit,
    timing,
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
    } catch (error) {
      // FTS 异常 → 降级扫描，保证搜索永不挂。⚠️ 必须记日志：这里曾静默吞掉「绑定了未引用参数」的 PG 错误，
      // 线上带城市的登录搜索整体退化到扫描路径（总数变 N+、候选口径变样）一段时间无人知晓（2026-09-18）。
      console.error("[jobs-search] fts path failed, falling back to scan", error instanceof Error ? error.message : error);
    }
  }
  return await searchViaScan(filters, prefs, actions, offset, limit, adapterBySource);
}

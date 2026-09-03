// 服务端岗位搜索 —— 自建香港 jobs 库（pg）版，忠实复刻 lib/job-search.ts 的 searchJobs：
//   同一份 search_doc bigram FTS（to_tsquery）收窄候选 + 同一份 JS 精筛/排序（scoring + job-filter）。
//   差别仅「候选取数」从 supabase-js 换成直连 pg SQL → 搜索口径/精度/排序与线上零差异。
import "server-only";
import { jobsQuery } from "./client";
import { actionHiddenJobIds, scoringSignalGroups, sortAndFilterJobs } from "@/lib/scoring";
import {
  filterAndRankJobs,
  filtersFullyPushedToSql,
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
async function fetchCandidates(sql: string, params: unknown[]): Promise<any[]> {
  const key = `${sql}|${JSON.stringify(params)}`;
  const hit = scanCache.get(key);
  if (hit && hit.expiresAt > Date.now()) return hit.rows;
  const pending = scanInFlight.get(key);
  if (pending) return pending;

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
const CANDIDATE_COLUMNS =
  "id, source_id, company, title, location, country_code, job_scope, job_type, summary, sponsorship_signal, " +
  "jd_url, apply_url, salary_text, posted_at, first_seen_at, last_seen_at, status, experience, education";
// 仅命中页(≤limit 行)回补的展示/写库列（打分精筛都不读）。
const HYDRATE_COLUMNS =
  "content_hash, created_at, deadline, enrich_fail_count, enrich_checked_at, canonical_jd_url";

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
  if (jobType !== "校招" && jobType !== "实习" && jobType !== "社招") return;

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
  conds.push(`((recruitment_category is not null and ${exact}) or (recruitment_category is null and ${legacyRecruitmentSuperset(jobType)}))`);
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
      " or (coalesce(title,'')||' '||coalesce(summary,'')) ~* '(应届|[0-9]{2,4}届|校园招聘|校招|管培生|管理培训生|留学生专项|new\\s?grads?|university\\s+graduate|entry[-\\s]?level|campus\\s?(recruit|hiring)|graduate\\s+program)'" +
      " or company ~* '(校招|校园招聘)')" +
      " and (job_type is null or job_type !~* '(社招|社会招聘|全职|experienced|professional|full.?time)')" +
      // 排除实习：recruitmentCategory 层1（实习）最先短路，命中它绝不可能再被判成校招。
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
    return "(job_type ~* '(实习|intern)' or title ~* '(实习|shixi|intern)' or jd_url ~* '(shixi|intern)')";
  }
  return "true"; // 社招=默认态·大头，无信号可下推 → 兜底路全放行，交给 JS 精筛
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
  const { conds, params, filters, prefs, hiddenIds, scanned, hiddenScanned, rankedLength } = args;
  if (!filtersFullyPushedToSql(filters)) return null; // ①
  if ((prefs?.exclude_keywords || []).length) return null; // ②
  if (rankedLength !== scanned - hiddenScanned) return null; // ③

  const countParams = [...params];
  const where = [...conds];
  if (hiddenIds.size) {
    countParams.push([...hiddenIds]);
    where.push(`not (id = any($${countParams.length}::uuid[]))`);
  }
  try {
    // 走同一份候选缓存：翻页时 where 逐字节相同 → 一次查询覆盖整轮浏览（实测热查询 ~85ms）。
    const rows = (await fetchCandidates(
      `select count(*)::int as total, count(*) filter (where recruitment_category is null)::int as unclassified ` +
        `from jobs where ${where.join(" and ")}`,
      countParams,
    )) as Array<{ total: number; unclassified: number }>;
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
  // 校招/实习超集下推：只保留可能命中的行，别把大量社招岗跨洋传过来（JS 仍权威判定）。
  appendRecruitmentPrefilter(conds, filters.jobType);
  // 走同一份候选缓存：候选集只由 where 决定（已全部进 key），而**翻页是在 JS 里 slice 的**——
  // 第 2 页的 SQL 与第 1 页逐字节相同。不缓存的话每翻一页都要把几千行重新跨库拉一遍再解析一遍，
  // 香港库实测这段占该接口服务端耗时的绝大部分（4354 行 ≈ 4.8MB）。
  // ⚠️ 排序参数走 candidateParams，`params` 保持「只含 where」——exactTotalWhenCapped 要拿它拼
  // count 查询，多带一个用不到的绑定参数 PG 会直接报错。
  const candidateParams = [...params];
  const orderBy = candidateOrderBy(candidateParams, filters, prefs);
  const rows = annotateSourceAdapter(
    await fetchCandidates(
      `select ${CANDIDATE_COLUMNS} from jobs where ${conds.join(" and ")}${orderBy} limit ${FTS_CAP}`,
      candidateParams,
    ),
    adapterBySource,
  );
  const ranked = annotateAndRank(rows, filters, prefs, actions);
  const breakdown = countMatchBreakdown(ranked);
  const page = ranked.slice(offset, offset + limit);
  const capped = rows.length >= FTS_CAP;
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
  // 实际翻过的候选行数 / 其中被 SQL 也会一并排除的隐藏岗数（算真实总数时的自检基线，见 exactTotalWhenCapped）。
  let scanned = 0;
  let hiddenScanned = 0;
  const hiddenIds = prefs ? actionHiddenJobIds(actions, filters) : new Set<string>();
  const conds = ["status = 'active'"];
  const params: unknown[] = [];
  appendJobScopeWhere(conds, params, prefs, filters);
  appendPostedWithinWhere(conds, params, filters.postedWithin);
  appendRecruitmentPrefilter(conds, filters.jobType); // 校招/实习超集下推，扫描也少翻无关行
  // 候选只取 CANDIDATE_COLUMNS（与 FTS 路径同一套）：JS 打分/精筛只读这些列，纯展示列留到
  // 命中页再回补。此前这里拉的是全量 JOB_COLUMNS —— sortBy=match 默认要看满 SCAN_BUDGET=28000 行，
  // 多传的 6 个展示列 × 2.8 万行是白扔的带宽。
  // ⚠️ 别再试「用 json_agg 把整批行打成一个字段传回来」绕开 node-pg 逐字段解析：2026-09-02
  // 上线实测**更慢**（无筛选冷路径 19.0s → 20.5s），因为 json 要给每行每列写一遍 key 名，
  // 2.8 万行多出约 8MB 纯键名、字节 +33%，把省下的解析成本吃光了（已撤回，commit f011592）。
  // 同 FTS 路径：`params` 只留 where（计数要用），排序参数进 candidateParams。
  const candidateParams = [...params];
  const orderBy = candidateOrderBy(candidateParams, filters, prefs);
  const sql =
    `select ${CANDIDATE_COLUMNS} from jobs where ${conds.join(" and ")}${orderBy} ` +
    `limit $${candidateParams.length + 1} offset $${candidateParams.length + 2}`;
  const fetchRows = (want: number, off: number) => jobsQuery(sql, [...candidateParams, want, off]);
  // 吸收一批：打分/精筛后并入 matched，返回「是否已到底」（拿到的比想要的少 = 没更多了）。
  const absorb = (raw: unknown, want: number): boolean => {
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
      await fetchCandidates(sql, [...candidateParams, SCAN_BUDGET, 0]),
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
  const capped = !exhausted;
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

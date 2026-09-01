// 个人机会雷达候选召回（§6.3）= 两阶段检索的 stage-1。返回「可能匹配的超集」，由引擎（stage-2）精筛。
//
// 两条既有约束（别回退）：
//   ① recall 只回**截断 summary**（left 300）+ 排除词在 SQL 应用 → 单行载荷砍数倍；展示卡由 service 回填完整行。
//      排除词必须留在 SQL：SQL 比对**完整** summary，召回行只有 300 字，挪到 JS 会漏掉只写在正文深处的排除词。
//   ② 城市/公司也走 **search_doc GIN**（location/company 已在 search_doc 内），不再 ILIKE 全表扫；
//      多层合成一条 SQL、一次跨区往返（serverless 冷池下每多一条连接就多一次 SSL 握手）。
// stage-1 的分层召回见下方 RECALL_TIERS 注释。
// companyHit 的权威判定用 normalizeCompany() exact（见 eligibility.ts），此处公司层只做超集召回。
import "server-only";
import { jobsQuery } from "./client";
import { jobsStoreEnabled } from "./read";
import { buildTsquery } from "@/lib/job-search";
import { keywordMatchUnits, classifyJobFunction } from "@/lib/china-keyword-expansion";
import { userTargetFunctions } from "@/lib/opportunities/eligibility";
import { appendJobScopeWhere, effectiveTargetRegions, jobMatchesScope } from "@/lib/job-scope";
import type { RadarProfile } from "@/lib/opportunities/types";

type SupabaseLike = { from: (table: string) => any };

export interface RecallResult {
  jobs: any[];
  capped: boolean;
}

const SEVEN_DAYS_MS = 7 * 86_400_000;
// 召回载荷调优（2026-06-26）：summary 截 300。**注**：这只是性能优化，不是 503 事故的根因——
// 真因是 node-pg 时间列返回 Date 对象打挂 Feed 排序（见 jobs-store/client.ts type parser），跟载荷无关。
// 但小载荷让 today SSR 更快、跨区更稳，故保留：匹配仍看 title + 前 300 字
// （search_doc 已 FTS 预筛，关键词必在标题/公司/城市/类型里）。
const SUMMARY_TRUNC = 300;

// ── 两阶段检索 stage-1（2026-07-31）────────────────────────────────────────────
// 旧实现：三类命中 OR 成一条，`order by first_seen_at desc limit 1500`。
// 线上实测证明它**同时又慢又漏**：某真实画像的命中集有 98,009 行，取最新 1500 = 1.5%，
// 等于候选池 ≈「最近约 8 小时被爬到的岗」——一个完美匹配但排在第 1501 新的岗今天根本进不了池子。
//
// 改法 = 检索工程标准的两阶段（retrieve → rerank）：stage-1 在库里按**相关度**取 top-K，
// stage-2（service.ts 的逐岗打分/硬门）一行不改。
//
// 三条被 live 实测否掉的写法（别再走）：
//   ❌ `order by ts_rank(...)`：要对全部命中行算分再排，实测 3.9s（对照当时同查询 57ms）。
//   ❌ 「方向×城市」单独成一层：那条**词库扩展后的方向 tsquery** 是最贵的东西（GIN 扫一次 0.1~3.6s），
//      单独成层等于把它扫两遍——某重画像因此从 3.3s 恶化到 6.0s。改为在方向层**内部**用便宜的
//      城市查询排序，全 SQL 只扫它一次。
//   ❌ 层与层用 `not (...)` 做互斥去重：估算行数被打成 rows=1，计划翻车，且实测零收益。
//
// 层内排序把「城市命中」顶到最前，是因为 checkEligibility 里 **location mismatch 是硬拒**——
// 用户填了目标城市时，不在目标城市的岗无论方向多准都进不了看板，先取它们就是纯浪费名额。
// 城市未知（location 为空）是 degraded 放行，排在城市命中之后、明确不符之前。
const RECALL_TIERS = ["role", "company", "cityNew"] as const;
type RecallTier = (typeof RECALL_TIERS)[number];
// 权重只在「该层这次有效」时参与分配（如用户没填城市 → cityNew 不存在，预算全给 role/company）。
const TIER_WEIGHTS: Record<RecallTier, number> = { role: 5, company: 2, cityNew: 3 };
// 总预算 1800：层内排序与 JS 硬门对齐后仍保留同一候选集合，再把预算从 900 提到 1800，
// 降低候选名额竞争造成的漏报；额外 900 行约增加 1.2MB 传输和少量 JS 计算。
export const RECALL_BUDGET = 1800;
// 已 saved/ignored/applied 的岗在 stage-2 必被 already_actioned 挡掉，却白占候选名额 → 下推到 SQL。
// 封顶 500：超出的仍由 stage-2 兜底拒绝，语义不变（这是纯粹的名额优化，不是过滤条件）。
const ACTIONED_EXCLUDE_CAP = 500;

// recall 列：summary 截断为 ≤500 字，砍跨区传输；展示卡由 service 回填完整 summary。
// 只取硬门 + 打分必需列 + 截断 summary：把 4000 行候选的跨区载荷压到最小（P0-1）。
// apply_url/posted_at/experience/deadline/content_hash/... 等展示字段不在此，由 service 对最终少量入选卡片回填完整行。
// enrich_checked_at（分层核验 today 硬门）+ posted_at/deadline（信号派生：STILL_OPEN/DEADLINE_SOON，在回填前算）
// 必须随召回带回——均为短字段/时间戳，载荷可忽略（P0-1 的重载荷是长 summary，已截断）。
const RECALL_COLUMNS =
  "id, source_id, company, title, location, country_code, job_scope, job_type, " +
  `left(btrim(summary), ${SUMMARY_TRUNC}) as summary, ` +
  "jd_url, salary_text, posted_at, deadline, first_seen_at, last_seen_at, enrich_checked_at, status, education";

// 方向 tsquery 的词库扩展上限。stage-1 最贵的东西就是这条查询的 GIN 扫描（实测 0.1~3.5s，
// 与子句数正相关）。真实画像实测：多数人扩展后 17~132 个子句，但有画像填了 29 个关键词 → **240 个**，
// 单这一条就把召回从 3.3s 拖到 4.1s。超预算后剩下的词**只保留原词、不再展开词库**——
// 一个词都不丢（原词仍能精确召回），砍掉的只是长尾的「近义扩展」，且 stage-2 的 keywordMatchTier
// 本来就会重新判匹配层级。
const ROLE_TSQUERY_CLAUSE_BUDGET = 120;

function roleTsquery(profile: RadarProfile): string | null {
  const terms = [...profile.targetRoles, ...profile.targetKeywords];
  if (!terms.length) return null;
  const includeOverseasLexicon = profile.jobScope !== "domestic";
  // 跨职能剪枝：stage-2 的方向门还有一道**职能门**（岗位职能判得出且不在用户目标职能集内 → 直接拒）。
  // 召回却是把每个词的词库组全 OR 起来，于是「产品经理 + Prompt Engineering」会把整个研发词库
  // （工程师/engineer/研发/developer…）拉进候选池，再由 JS 一个个扔掉：某真实产品画像 1,216 个候选里
  // 1,053 个被方向门拒掉，光「研发」职能就 724 个（2026-08-27 实测）。这里用**同一套** userTargetFunctions
  // + classifyJobFunction 提前剪掉，两端判据一致、不会各说各话。
  // 三条边界（有测试钉着，见 tests/opportunity-recall-function-prune.test.js）：
  //   ① 用户自己写的原词一律保留——他写「工程师」就是要搜工程师；
  //   ② 职能判不出（"其他"）的词保留——职能门本来就放行这类岗；
  //   ③ 用户没填 targetRoles（目标职能集为空）时一个词都不剪——无从判断就别猜。
  const targetFns = userTargetFunctions(profile);
  const rawTerms = new Set(terms.map((t) => String(t).trim().toLowerCase()));
  const outOfScope = (term: string): boolean => {
    if (!targetFns.size) return false;
    if (rawTerms.has(String(term).trim().toLowerCase())) return false;
    const fn = classifyJobFunction({ title: term });
    return Boolean(fn && fn !== "其他" && !targetFns.has(fn));
  };
  // 每个查询词按**它自己的 AND 单元结构**建子句，词与词之间才 OR。
  //
  // 旧实现把所有词的词库扩展**全部拍平成一个大 OR**，代价是召回池被泛词彻底稀释：
  // 「前端开发工程师」扩展后含「工程师 / engineer / 研发 / developer」，而库里泛工程师岗有 82,738 个、
  // 真前端岗只有 1,225 个 → 1,800 的召回预算几乎全被泛工程师岗吃掉，stage-2 再把它们一个个拒掉
  // （实测 1,125 个候选里 1,094 个 role_mismatch），真前端岗只剩 24 个能展示。**这不是精度问题，
  // 是召回池根本没捞到货**：过滤器修得再准，池子里没有对的岗也白搭。
  //
  // 改成 AND-of-ORs 后同一个查询变成 `(前端|frontend|react|…) & (工程师|engineer|…)`，
  // 与 stage-2 的 keywordMatchUnits 用**同一套**单元拆分，两端口径一致、召回不再喂给过滤器一池垃圾。
  const clauses: string[] = [];
  const seenClause = new Set<string>();
  const seenTerm = new Set<string>();
  let clauseBudget = ROLE_TSQUERY_CLAUSE_BUDGET;

  for (const t of terms) {
    // 超出扩展预算后**不丢词**，只是不再展开词库——原词单独成子句仍能精确召回。
    // （沿用旧实现的语义：预算砍掉的是长尾近义扩展，不是用户的检索意图。）
    const units = clauseBudget > 0 ? keywordMatchUnits(t, { includeOverseasLexicon }) : [];
    const unitClauses: string[] = [];
    for (const unit of units) {
      // 职能剪枝沿用旧口径：跨职能的**扩展词**剪掉。
      // 单单元的词还要过一遍全局词去重：单单元子句本质就是顶层的一段扁平 OR，
      // 同一个词在多段里重复只会让 GIN 白扫（实测「AI」的单向展开含整个算法组，
      // 与用户另外写的「算法」整组重叠 10 个词）。OR 幂等，去重不改语义。
      // 多单元（AND）子句不参与：它的每个 OR 组都是 AND 的一侧，缺词会放宽匹配。
      const singleUnit = units.length === 1;
      const kept = unit.filter(
        (term) => !outOfScope(term) && !(singleUnit && seenTerm.has(term)),
      );
      if (singleUnit) for (const term of kept) seenTerm.add(term);
      // 整个单元被剪光 → 这个词的这一层完全跨职能，AND 结构不成立，整条走下面的原词回退。
      if (!kept.length) { unitClauses.length = 0; break; }
      const q = buildTsquery(kept, []);
      if (!q) { unitClauses.length = 0; break; }
      unitClauses.push(q);
      clauseBudget -= kept.length;
    }

    // 回退到用户原词：**原词一律不剪**（他写「Prompt Engineering」就是要搜它，哪怕这个词
    // 整体属于别的职能）。只有词库**扩展**出来的跨职能词才该被剪——丢掉原词等于把用户
    // 明确写下的检索意图吃掉。契约钉在 tests/opportunity-recall-function-prune.test.js。
    const clause = unitClauses.length
      ? unitClauses.length === 1
        ? unitClauses[0]
        : `(${unitClauses.join(" & ")})`
      : buildTsquery([t], []);
    if (!clause) continue;
    if (seenClause.has(clause)) continue; // SQL/Python/数据分析 常拆出同一组单元，去重免得 GIN 白干
    seenClause.add(clause);
    clauses.push(clause);
  }

  return clauses.length ? clauses.join(" | ") : null;
}

function mergeById(target: Map<string, any>, rows: any[] | null | undefined): void {
  for (const r of rows || []) {
    if (r && r.id != null && !target.has(r.id)) target.set(r.id, r);
  }
}

function finalize(byId: Map<string, any>, limit: number): RecallResult {
  const jobs = Array.from(byId.values()).sort((a, b) =>
    String(b.first_seen_at || "").localeCompare(String(a.first_seen_at || "")),
  );
  return { jobs: jobs.slice(0, limit), capped: jobs.length > limit };
}

// ---- 香港 pg 路径：三分支均走 search_doc GIN，并行 ----
function excludePatterns(profile: RadarProfile): string[] {
  return profile.excludeKeywords
    .map((k) => String(k || "").trim().toLowerCase())
    .filter(Boolean)
    .map((k) => `%${k}%`);
}

function stageRecallPatterns(profile: RadarProfile): { text: string[]; url: string[] } | null {
  if (profile.experienceStage === "实习") {
    return { text: ["%实习%", "%intern%"], url: ["%shixi%", "%intern%"] };
  }
  if (profile.experienceStage === "校招") {
    return {
      text: ["%校招%", "%校园%", "%应届%", "%campus%", "%graduate%", "%届%"],
      url: ["%campus%"],
    };
  }
  return null;
}

function appendStageRecallWhere(profile: RadarProfile, conds: string[], params: unknown[]): void {
  const patterns = stageRecallPatterns(profile);
  if (!patterns) return;
  params.push(patterns.text);
  conds.push(
    `(lower(title) like any($${params.length}::text[]) or ` +
      `lower(coalesce(job_type,'')) like any($${params.length}::text[]) or ` +
      `lower(coalesce(jd_url,'')) like any($${params.length + 1}::text[]))`,
  );
  params.push(patterns.url);
}

function stageRecallOr(profile: RadarProfile): string | null {
  const patterns = stageRecallPatterns(profile);
  if (!patterns) return null;
  const clauses = [
    ...patterns.text.flatMap((p) => [`title.ilike.${p}`, `job_type.ilike.${p}`]),
    ...patterns.url.map((p) => `jd_url.ilike.${p}`),
  ];
  return clauses.join(",");
}

function applyStageRecallFilter(query: any, profile: RadarProfile): any {
  const stageOr = stageRecallOr(profile);
  return stageOr ? query.or(stageOr) : query;
}

function patternMatches(value: unknown, pattern: string): boolean {
  const needle = pattern.replace(/%/g, "").toLowerCase();
  return Boolean(needle) && String(value || "").toLowerCase().includes(needle);
}

function jobMatchesStageRecall(job: any, profile: RadarProfile): boolean {
  const patterns = stageRecallPatterns(profile);
  if (!patterns) return true;
  return (
    patterns.text.some((p) => patternMatches(job.title, p) || patternMatches(job.job_type, p)) ||
    patterns.url.some((p) => patternMatches(job.jd_url, p))
  );
}

/**
 * stage-1 分层召回 SQL（纯函数，便于单测与离线评测）。
 *
 * 三层：方向（role）/ 目标公司（company）/ 目标城市近 7 天新增（cityNew）。
 * 最后一层同时是「方向只写在 JD 正文里」的岗唯一的进池通道——search_doc 只索引
 * 标题/公司/城市/类型、不含正文，而 stage-2 的 keywordMatchTier 会读正文，
 * 所以 SQL 的方向层并不是 JS 方向门的超集。
 *
 * **加权轮转取用**（按 `层内序号 ÷ 层权重` 排序）而不是「每层一个固定 cap」：固定 cap 下某层取不满
 * 就白白浪费预算（实测有画像因此只召回 349 行、展示岗位从 25 掉到 15）。轮转让取不满的层自动把名额
 * 让给其他层，总量恒等于 min(budget, 可用量)。层之间会有重叠，重复行在 JS 侧按 id 去掉。
 */
export function buildRecallSql(
  profile: RadarProfile,
  sinceIso: string,
  budget: number,
  actionedJobIds: readonly string[] = [],
): { sql: string; params: unknown[]; tiers: RecallTier[] } | null {
  const excl = excludePatterns(profile);
  const roleTs = roleTsquery(profile);
  const companyTs = profile.targetCompanies.length
    ? buildTsquery(profile.targetCompanies.slice(0, 30), [])
    : null;
  const cityTs = profile.targetLocations.length
    ? buildTsquery(profile.targetLocations.slice(0, 10), [])
    : null;

  const params: unknown[] = [sinceIso];
  const base = [
    "status = 'active'",
    "last_seen_at >= $1",
    "summary is not null",
    "char_length(btrim(summary)) >= 60",
  ];
  if (excl.length) {
    params.push(excl);
    // 排除词用完整 summary 比对（不受 left 截断影响），逐字对齐 crawler jobExcluded 的字段集
    base.push(`not (lower(concat_ws(' ', title, company, location, job_type, summary, salary_text)) like any($${params.length}::text[]))`);
  }
  appendJobScopeWhere(base, params, { job_scope: profile.jobScope, target_regions: profile.targetRegions });
  appendStageRecallWhere(profile, base, params);
  const actioned = actionedJobIds.slice(0, ACTIONED_EXCLUDE_CAP);
  if (actioned.length) {
    params.push(actioned);
    base.push(`id <> all($${params.length}::uuid[])`);
  }

  const roleRef = roleTs ? (params.push(roleTs), `search_doc @@ to_tsquery('simple', $${params.length})`) : null;
  const companyRef = companyTs
    ? (params.push(companyTs), `search_doc @@ to_tsquery('simple', $${params.length})`)
    : null;
  const cityRef = cityTs ? (params.push(cityTs), `search_doc @@ to_tsquery('simple', $${params.length})`) : null;

  // 层内排序：国内是「城市命中 → 城市未知 → 其余」；含海外范围时是
  // 「目标地区命中 → 目标城市命中 → 其余」。城市/地区判断只在每层限量候选上逐行算，
  // 不另拆一层，避免昂贵的方向 GIN 再扫一次。
  const cityFirst = cityRef
    ? `(case when ${cityRef} then 0 when location is null or btrim(location) = '' then 1 else 2 end), first_seen_at desc`
    : "first_seen_at desc";
  let regionMatch: string | null = null;
  if (profile.jobScope !== "domestic") {
    const regions = effectiveTargetRegions({ job_scope: profile.jobScope, target_regions: profile.targetRegions });
    const countryRegions = regions.filter((region) => region !== "Remote");
    const parts: string[] = [];
    if (countryRegions.length) {
      params.push(countryRegions);
      parts.push(`country_code = any($${params.length}::text[])`);
    }
    if (regions.includes("Remote")) {
      parts.push(
        "(country_code is null and (lower(coalesce(location, '')) like '%remote%' or coalesce(location, '') like '%远程%'))",
      );
    }
    if (parts.length) regionMatch = `(job_scope = 'overseas' and (${parts.join(" or ")}))`;
  }
  const regionCityFirst = regionMatch
    ? cityRef
      ? `(case when ${regionMatch} then 0 when ${cityRef} then 1 else 2 end), first_seen_at desc`
      : `(case when ${regionMatch} then 0 else 1 end), first_seen_at desc`
    : cityFirst;
  // companyHit 不豁免 JS 的方向硬门，cityNew 也会捞到仅城市命中的岗位；两层都先把
  // 方向命中放前面。它只是已限量候选的逐行布尔判断，不会新增方向 GIN 扫描。
  const directionFirst = roleRef ? `(case when ${roleRef} then 0 else 1 end), ` : "";

  const tiers: Array<{ tier: RecallTier; conds: string[]; order: string }> = [];
  if (roleRef) tiers.push({ tier: "role", conds: [roleRef], order: regionCityFirst });
  if (companyRef) tiers.push({ tier: "company", conds: [companyRef], order: `${directionFirst}${regionCityFirst}` });
  if (cityRef) {
    tiers.push({
      tier: "cityNew",
      conds: [cityRef, "first_seen_at >= $1"],
      order: `${directionFirst}${regionCityFirst}`,
    });
  }
  if (!tiers.length) return null; // profile_ready 应保证至少一项；防御性返回

  params.push(budget);
  const capRef = `$${params.length}`;
  const parts = tiers.map(({ conds, order }, i) =>
    `(select ${i} as _tier, row_number() over (order by ${order}) as _rn, ${RECALL_COLUMNS} from jobs ` +
    `where ${[...base, ...conds].join(" and ")} order by ${order} limit ${capRef})`,
  );
  params.push(tiers.map(({ tier }) => TIER_WEIGHTS[tier]));
  const weightsRef = `$${params.length}::float[]`;
  // 加权轮转：权重 5 的层每被取 5 条，权重 2 的层才被取 2 条；某层取空后其名额自动流向其余层。
  const sql =
    `select * from (\n${parts.join("\nunion all\n")}\n) q ` +
    `order by _rn::float / (${weightsRef})[_tier + 1], _tier limit ${capRef}`;
  return { sql, params, tiers: tiers.map(({ tier }) => tier) };
}

/** 剥掉排序用的辅助列（_tier/_rn）并按 id 去重：层之间会重叠（如目标公司的岗同时命中方向层）。 */
export function stripTierColumns(rows: any[]): any[] {
  const seen = new Set<string>();
  const out: any[] = [];
  for (const r of rows || []) {
    if (!r || r.id == null || seen.has(r.id)) continue;
    seen.add(r.id);
    const job = { ...r };
    delete job._tier;
    delete job._rn;
    out.push(job);
  }
  return out;
}

// 各层合成**一条** SQL：单连接、单次跨区往返。
// P0-1 复验真因 = 连接/跨区往返开销（服务端 plan 4ms、110 行仍 22s 并连接超时），不是 plan 也不是行数；
// 并行分支 = serverless 冷池下多次 SSL 握手 → 合并为 1 连接最稳。不抬 timeout、不加无关硬窗。
async function recallViaStore(
  profile: RadarProfile,
  sinceIso: string,
  budget: number,
  actionedJobIds: readonly string[],
): Promise<RecallResult> {
  const built = buildRecallSql(profile, sinceIso, budget, actionedJobIds);
  if (!built) return { jobs: [], capped: false };
  const rows = await jobsQuery(built.sql, built.params);
  // 取满预算 = 库里还有没取到的候选 → capped 诚实为 true
  return { jobs: stripTierColumns(rows), capped: rows.length >= budget };
}

// ---- Supabase 回退（本地/回滚；prod jobs 表已空，非性能关键路径）----
async function recallViaSupabase(
  profile: RadarProfile,
  sinceIso: string,
  supabase: SupabaseLike,
  limit: number,
): Promise<RecallResult> {
  const byId = new Map<string, any>();
  let branchCapped = false;
  const summaryOk = (j: any) => String(j?.summary || "").trim().length >= 60;
  const take = (data: any[] | null | undefined) => {
    const rows = data || [];
    if (rows.length >= limit) branchCapped = true; // 分支命中 limit = 截断
    mergeById(
      byId,
      rows.filter(
        (j) =>
          summaryOk(j) &&
          jobMatchesScope(j, { job_scope: profile.jobScope, target_regions: profile.targetRegions }) &&
          jobMatchesStageRecall(j, profile),
      ),
    );
  };

  const roleTs = roleTsquery(profile);
  if (roleTs) {
    const query = applyStageRecallFilter(
      supabase
        .from("jobs")
        .select("*")
        .eq("status", "active")
        .gte("last_seen_at", sinceIso)
        .textSearch("search_doc", roleTs, { config: "simple" }),
      profile,
    );
    const { data } = await query.limit(limit);
    take(data);
  }
  const companies = profile.targetCompanies.slice(0, 30);
  const companyTs = companies.length ? buildTsquery(companies, []) : null;
  if (companyTs) {
    const query = applyStageRecallFilter(
      supabase
        .from("jobs")
        .select("*")
        .eq("status", "active")
        .gte("last_seen_at", sinceIso)
        .textSearch("search_doc", companyTs, { config: "simple" }),
      profile,
    );
    const { data } = await query.limit(limit);
    take(data);
  }
  const cityTs = profile.targetLocations.length
    ? buildTsquery(profile.targetLocations.slice(0, 10), [])
    : null;
  if (cityTs) {
    const query = applyStageRecallFilter(
      supabase
        .from("jobs")
        .select("*")
        .eq("status", "active")
        .gte("last_seen_at", sinceIso)
        .gte("first_seen_at", sinceIso)
        .textSearch("search_doc", cityTs, { config: "simple" }),
      profile,
    );
    const { data } = await query.limit(limit);
    take(data);
  }
  const r = finalize(byId, limit);
  return { jobs: r.jobs, capped: branchCapped || r.capped };
}

export async function recallOpportunityCandidates(
  profile: RadarProfile,
  now: Date,
  supabaseFallback: SupabaseLike | null,
  options: { budget?: number; actionedJobIds?: readonly string[] } = {},
): Promise<RecallResult> {
  const sinceIso = new Date(now.getTime() - SEVEN_DAYS_MS).toISOString();
  const budget = options.budget ?? RECALL_BUDGET;
  if (jobsStoreEnabled()) {
    return recallViaStore(profile, sinceIso, budget, options.actionedJobIds ?? []);
  }
  if (supabaseFallback) {
    return recallViaSupabase(profile, sinceIso, supabaseFallback, budget);
  }
  return { jobs: [], capped: false };
}

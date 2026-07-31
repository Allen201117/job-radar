// Opportunity Engine 编排（§6.1 / §7 + v3）：读画像 → 召回 → 逐岗算事实/硬门/打分/派生信号 → 关键提醒(saved)
// → 按身份×强度分区 → 组装 OpportunityFeed。纯逻辑（facts/eligibility/scoring/signals/grouping）各自单测；
// 本文件只做 DB 编排与组装，不重写匹配/信号规则。
import "server-only";
import type { JobAction, Job } from "../types";
import type {
  RadarProfile,
  Opportunity,
  OpportunityFeed,
  OpportunityFeedOptions,
  FeedSections,
  FeedCounts,
  SourceMeta,
  RadarIntensity,
} from "./types";
import { isProfileReady } from "./profile";
import { computeMatchFacts, checkEligibility, type ActionState } from "./eligibility";
import { scoreOpportunity } from "./scoring";
import { groupOpportunities, resolveNoveltySince } from "./grouping";
import { deriveOpportunitySignals } from "./signals";
import { parseDeadline } from "./deadline";
import { recallOpportunityCandidates } from "../jobs-store/opportunities";
import { jobsByIds, jobsStoreEnabled } from "../jobs-store/read";
import { hydrateOpportunityJobs } from "./hydration";

type SupabaseLike = { from: (table: string) => any };

const EMPTY_COUNTS: FeedCounts = { total: 0, critical: 0, main: 0, by_signal: {} };
const EMPTY_SECTIONS: FeedSections = { critical: [], main: [], explore: [], momentum: [], waiting: [] };

// 把 job_actions 折叠成每岗位的 {primary, viewed}
function buildActionMap(actions: JobAction[]): Map<string, ActionState> {
  const map = new Map<string, ActionState>();
  for (const a of actions || []) {
    const cur = map.get(a.job_id) || { primary: null, viewed: false };
    if (a.action === "viewed") cur.viewed = true;
    else if (a.action === "saved" || a.action === "ignored" || a.action === "applied") cur.primary = a.action;
    map.set(a.job_id, cur);
  }
  return map;
}

const SOURCE_META_COLUMNS = "id, company, adapter_name, crawl_method, last_checked_at, enabled";
/** freshness 徽章只看「上次检查时间」的粗粒度，5 分钟内完全够新鲜。 */
const SOURCE_META_TTL_MS = 5 * 60 * 1000;
/** 单次 `.in()` 带几个 id：PostgREST 的 select 走 GET，id 太多会把 URL 撑爆。 */
const SOURCE_META_CHUNK = 100;

let sourceMetaCache = new Map<string, SourceMeta>();
let sourceMetaCacheAt = 0;

/** 供测试重置模块级缓存，避免用例间互相污染。 */
export function __resetSourceMetaCache(): void {
  sourceMetaCache = new Map();
  sourceMetaCacheAt = 0;
}

/**
 * 取本次召回**真正涉及到**的那些 source 的元信息（sources 永远在 Supabase）。
 * 失败不抛，freshness 退化为 manual SLA（§14.2）。
 *
 * ⚠️ 为什么不再取全表：旧实现一次性拉全部 sources，理由是「可与召回并行、省一条串行往返」。
 * 但 sources 已越过 PostgREST 单次 1000 行上限（实测 1121），`fetchAllSources` 内部因此是
 * **串行**翻页 —— 所谓的"并行"里藏着 2 趟跨洋往返 + 1121 行传输，本地实测这一条就要 1434ms，
 * 反而成了 buildOpportunityFeed 那个 Promise.all 阶段的最慢一条。
 * 而实测一次召回（limit 4000）只涉及 **395 个源**：改成按 id 取后 395 < 1000 → 一次往返、
 * 行数少 65%，即使排在召回之后串行执行也更快。
 *
 * 另加按 id 的进程内缓存（TTL 5 分钟）：同实例的后续渲染只补差集。⚠️ 但别指望它——
 * 低流量下 Vercel 几乎每请求一个新实例，命中率很低（本轮实测：只加缓存不改取数方式，
 * /today 总时长纹丝不动）。真正的收益来自「少取行」，缓存只是锦上添花。
 */
async function fetchSourceMetaFor(
  supabase: SupabaseLike,
  jobs: Array<{ source_id?: string | null }>,
): Promise<Map<string, SourceMeta>> {
  const wanted = new Set<string>();
  for (const j of jobs) if (j.source_id) wanted.add(j.source_id);
  if (!wanted.size) return new Map();

  if (Date.now() - sourceMetaCacheAt > SOURCE_META_TTL_MS) {
    sourceMetaCache = new Map();
    sourceMetaCacheAt = Date.now();
  }
  const missing = Array.from(wanted).filter((id) => !sourceMetaCache.has(id));
  if (missing.length) {
    const chunks: string[][] = [];
    for (let i = 0; i < missing.length; i += SOURCE_META_CHUNK) {
      chunks.push(missing.slice(i, i + SOURCE_META_CHUNK));
    }
    try {
      const results = await Promise.all(
        chunks.map((ids) => supabase.from("sources").select(SOURCE_META_COLUMNS).in("id", ids)),
      );
      for (const r of results) {
        if (r?.error) throw new Error(r.error.message);
        for (const s of (r?.data || []) as SourceMeta[]) sourceMetaCache.set(s.id, s);
      }
    } catch (e) {
      console.warn("[opportunities] source metadata query threw:", (e as Error).message);
    }
  }
  const out = new Map<string, SourceMeta>();
  for (const id of wanted) {
    const s = sourceMetaCache.get(id);
    if (s) out.set(id, s);
  }
  return out;
}

// recall 为省跨区传输只回硬门/打分必需列（截断 summary）；展示卡在这里按 id 用**完整行**回填。
async function hydrateDisplayJobs(sections: FeedSections): Promise<void> {
  if (!jobsStoreEnabled()) return;
  const all = Object.values(sections).flat();
  const ids = all.map((o) => o.job.id).filter(Boolean);
  if (!ids.length) return;
  try {
    const rows = await jobsByIds(ids, false);
    hydrateOpportunityJobs(sections, rows);
  } catch (e) {
    console.warn("[opportunities] display-job hydrate failed:", (e as Error).message);
  }
}

// 关键提醒（§3 / §4.4）：用户 saved/applied 的岗位若关闭/陈旧/快截止 → 进关键提醒区（不受强度压制）。
// saved 岗被 eligibility 的 already_actioned 排除出主召回，所以这里单独取当前库状态派生。
async function buildCriticalAlerts(
  actions: JobAction[],
  profile: RadarProfile,
  intensity: RadarIntensity,
  now: Date
): Promise<Opportunity[]> {
  const watched = (actions || []).filter((a) => a.action === "saved" || a.action === "applied");
  const ids = Array.from(new Set(watched.map((a) => a.job_id).filter(Boolean))).slice(0, 50);
  if (!ids.length || !jobsStoreEnabled()) return [];

  let rows: Job[] = [];
  try {
    rows = await jobsByIds(ids, false);
  } catch (e) {
    console.warn("[opportunities] critical-alert lookup failed:", (e as Error).message);
    return [];
  }
  const byId = new Map(rows.map((r) => [r.id, r]));
  const actionById = new Map<string, "saved" | "applied">();
  for (const a of watched) if (a.action === "saved" || a.action === "applied") actionById.set(a.job_id, a.action);

  const out: Opportunity[] = [];
  for (const id of ids) {
    const job = byId.get(id);
    if (!job) continue;
    const signals = deriveOpportunitySignals(
      job,
      { freshness: "unknown", stageLabel: null },
      profile,
      now,
      { isWatched: true }
    );
    // 被关注岗：关闭与快截止都是关键提醒（即便社招 deadline 也对 saved 岗升级为关键）。
    for (const s of signals) {
      if (s.type === "CLOSED_OR_STALE" || s.type === "DEADLINE_SOON") s.isCritical = true;
    }
    if (!signals.some((s) => s.isCritical)) continue; // 仍在招且无快截止 → 不打扰（留在 /saved）
    out.push({
      job,
      score: 100,
      tier: "high",
      reasons: [{ type: "company", label: `你保存的岗位 ${job.company}` }],
      freshness: "unknown",
      firstSeenAt: job.first_seen_at ?? null,
      lastSeenAt: job.last_seen_at ?? null,
      userAction: actionById.get(id) ?? "saved",
      viewed: false,
      isNew: false,
      exploreEligible: false,
      signals,
      intensity,
      lastCheckedAt: job.enrich_checked_at ?? null,
      officialPostedAt: job.posted_at ?? null,
      deadlineAt: parseDeadline(job.deadline, now)?.date ?? null,
    });
  }
  return out;
}

export async function buildOpportunityFeed(
  supabase: SupabaseLike,
  profile: RadarProfile,
  actions: JobAction[],
  radarState: { last_opened_at: string | null } | null,
  options: OpportunityFeedOptions,
): Promise<OpportunityFeed> {
  const now = options.now ?? new Date();
  const intensity: RadarIntensity = options.intensity ?? "active";
  const lastOpenedAt = radarState?.last_opened_at ?? null;

  if (!isProfileReady(profile)) {
    return {
      generated_at: now.toISOString(),
      profile_ready: false,
      candidate_capped: false,
      last_opened_at: lastOpenedAt,
      stage: profile.experienceStage,
      intensity,
      counts: { ...EMPTY_COUNTS },
      sections: { critical: [], main: [], explore: [], momentum: [], waiting: [] },
    };
  }

  const actionMap = buildActionMap(actions);
  const actionedIds = Array.from(actionMap.entries())
    .filter(([, state]) => state.primary !== null)
    .map(([jobId]) => jobId);
  // 各阶段耗时（诊断用，见文件顶部 FeedTiming 注释）。performance.now() 成本可忽略，常开无妨；
  // 只有 /today?__timing=1 才会把它渲染出来，普通用户拿不到。
  const clock = () => performance.now();
  const t0 = clock();
  const mark: Record<string, number> = {};

  // 两条互相独立的 I/O 并行：① 岗位召回（香港库）② 关键提醒（香港库，按 saved/applied 岗）。
  // source 元信息改为召回之后按 id 取（只要这一批真正涉及的源）——它原本挤在这个 Promise.all 里
  // 号称"并行"，实际是全表分页的 2 趟串行跨洋往返 + 1121 行，反而是最慢的一条。
  // 详见 fetchSourceMetaFor 的注释与实测数字。
  let recallMs = 0;
  let criticalMs = 0;
  const [recall, critical] = await Promise.all([
    (async () => {
      const s = clock();
      try {
        // 已处理过的岗（saved/ignored/applied）下推到 SQL 排除：它们在 stage-2 必被 already_actioned 挡掉，
        // 留在候选里只是白占名额。viewed 不算——那类岗仍可展示（只在打分里 -8）。
        return await recallOpportunityCandidates(profile, now, supabase, { actionedJobIds: actionedIds });
      } finally {
        recallMs = clock() - s;
      }
    })(),
    (async () => {
      const s = clock();
      try {
        return await buildCriticalAlerts(actions, profile, intensity, now);
      } finally {
        criticalMs = clock() - s;
      }
    })(),
  ]);
  mark.recall = recallMs;
  mark.critical = criticalMs;
  mark.parallel = clock() - t0; // 这一阶段的墙钟（= 两条里最慢的那条）

  const tSrc = clock();
  const sourceMeta = await fetchSourceMetaFor(supabase, recall.jobs);
  mark.sourcemeta = clock() - tSrc;
  const tCompute = clock();

  const opps: Opportunity[] = [];
  // 计分板置换：统计每一次静默 continue（用户看不见的过滤劳动），随 feed 外显。
  // already_actioned 不计——那是用户自己处理过的，不是系统替他挡的。
  const filtered = { inactive: 0, mismatch: 0, low_score: 0, thin: 0 };
  for (const job of recall.jobs) {
    const action = actionMap.get(job.id) || { primary: null, viewed: false };
    const facts = computeMatchFacts(job, profile, job.source_id ? sourceMeta.get(job.source_id) : undefined, action, now);
    const elig = checkEligibility(facts);
    if (!elig.eligible) {
      if (elig.reason === "inactive" || elig.reason === "stale" || elig.reason === "source_disabled") filtered.inactive += 1;
      else if (elig.reason === "thin_summary") filtered.thin += 1;
      else if (elig.reason !== "already_actioned") filtered.mismatch += 1;
      continue;
    }
    const { score, tier, reasons } = scoreOpportunity(facts, elig.degraded);
    if (tier === null) {
      filtered.low_score += 1;
      continue; // score < 30，不展示
    }
    const parsed = parseDeadline(job.deadline ?? null, now);
    const signals = deriveOpportunitySignals(job, facts, profile, now, { isWatched: false, parsedDeadline: parsed });
    opps.push({
      job,
      score,
      tier,
      reasons,
      freshness: facts.freshness,
      firstSeenAt: job.first_seen_at ?? null,
      lastSeenAt: job.last_seen_at ?? null,
      userAction: facts.userAction,
      viewed: facts.viewed,
      isNew: false, // grouping 据 noveltySince 填充
      exploreEligible: facts.roleTier === "related" || facts.companyHit,
      signals,
      intensity,
      lastCheckedAt: (job.enrich_checked_at as string | null) ?? null,
      officialPostedAt: job.posted_at ?? null,
      deadlineAt: parsed?.date ?? null,
    });
  }

  mark.compute = clock() - tCompute;

  // 关键提醒（saved 岗关闭/快截止）已在上面与召回并行取好，置顶不受强度压制。
  const overrideProvided = options.noveltySinceOverride !== undefined && options.noveltySinceOverride !== null;
  const noveltySince = resolveNoveltySince(overrideProvided ? options.noveltySinceOverride! : lastOpenedAt, now);

  const tGroup = clock();
  // 关键提醒在截断前与完整召回候选统一语义去重/分区，冲突主卡被淘汰时后续候选可正常回填。
  const { sections, counts } = groupOpportunities([...critical, ...opps], {
    dailyLimit: profile.dailyLimit,
    intensity,
    noveltySince,
    now,
  });
  counts.screened = recall.jobs.length;
  counts.filtered = filtered;
  mark.group = clock() - tGroup;

  const tHydrate = clock();
  await hydrateDisplayJobs(sections);
  mark.hydrate = clock() - tHydrate;
  mark.total = clock() - t0;
  mark.candidates = recall.jobs.length;
  mark.displayed = Object.values(sections).reduce((n, arr) => n + arr.length, 0);

  return {
    generated_at: now.toISOString(),
    profile_ready: true,
    candidate_capped: recall.capped,
    last_opened_at: lastOpenedAt,
    stage: profile.experienceStage,
    intensity,
    counts,
    sections,
    timing: {
      recall: Math.round(mark.recall),
      critical: Math.round(mark.critical),
      parallel: Math.round(mark.parallel),
      sourcemeta: Math.round(mark.sourcemeta),
      compute: Math.round(mark.compute),
      group: Math.round(mark.group),
      hydrate: Math.round(mark.hydrate),
      total: Math.round(mark.total),
      candidates: mark.candidates,
      displayed: mark.displayed,
    },
  };
}

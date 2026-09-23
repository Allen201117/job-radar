// Opportunity Engine 编排（§6.1 / §7 + v3）：读画像 → 召回 → 逐岗算事实/硬门/打分/派生信号 → 关键提醒(saved)
// → 按身份×强度分区 → 组装 OpportunityFeed。纯逻辑（facts/eligibility/scoring/signals/grouping）各自单测；
// 本文件只做 DB 编排与组装，不重写匹配/信号规则。
import "server-only";
import type { Job } from "../types";
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
import { recallOpportunityCandidates, type RecallResult } from "../jobs-store/opportunities";
import type { RecallSnapshot } from "../jobs-store/recall-snapshot";
import { jobsByIds, jobsStoreEnabled } from "../jobs-store/read";
import { estimateRowBytes, kb } from "../jobs-store/row-bytes";
import { hydrateOpportunityJobs } from "./hydration";
import { SOURCE_META_COLUMNS, loadSourceMetaSnapshot } from "./source-meta";
import type { RadarJobAction } from "./types";

type SupabaseLike = { from: (table: string) => any };

const EMPTY_COUNTS: FeedCounts = { total: 0, critical: 0, main: 0, by_signal: {} };
const EMPTY_SECTIONS: FeedSections = { critical: [], main: [], explore: [], momentum: [], waiting: [] };

// 把 job_actions 折叠成每岗位的 {primary, viewed}
function buildActionMap(actions: RadarJobAction[]): Map<string, ActionState> {
  const map = new Map<string, ActionState>();
  for (const a of actions || []) {
    const cur = map.get(a.job_id) || { primary: null, viewed: false };
    if (a.action === "viewed") cur.viewed = true;
    else if (a.action === "saved" || a.action === "ignored" || a.action === "applied") cur.primary = a.action;
    map.set(a.job_id, cur);
  }
  return map;
}

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
 * 【兜底路径】取本次召回**真正涉及到**的那些 source 的元信息（sources 永远在 Supabase）。
 *
 * 主路径已改为 `loadSourceMetaSnapshot()` 的跨实例全表快照（见 lib/opportunities/source-meta.ts），
 * 它不依赖召回结果、可与召回并行；这里只在快照取不到时兜底，**不是死代码**：
 * 快照一旦静默失败而这里又不补，`checkEligibility` 的 `source_disabled` 硬门会整体失效。
 *
 * 历史（别再原地打转）：一次请求一次全表拉取 → 改按 id 分块取（395 个源、一次往返）→
 * 线上实测这一跳仍要 **480ms**，因为它**只能串在召回之后**。进程内缓存（TTL 5 分钟）
 * 在 serverless 低流量下几乎不命中（每请求一个新实例），别指望它。
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
async function hydrateDisplayJobs(sections: FeedSections): Promise<{ rows: number; bytes: number }> {
  if (!jobsStoreEnabled()) return { rows: 0, bytes: 0 };
  const all = Object.values(sections).flat();
  const ids = all.map((o) => o.job.id).filter(Boolean);
  if (!ids.length) return { rows: 0, bytes: 0 };
  try {
    const rows = await jobsByIds(ids, false);
    hydrateOpportunityJobs(sections, rows);
    return { rows: rows.length, bytes: estimateRowBytes(rows) };
  } catch (e) {
    console.warn("[opportunities] display-job hydrate failed:", (e as Error).message);
    return { rows: 0, bytes: 0 };
  }
}

// 关键提醒（§3 / §4.4）：用户 saved/applied 的岗位若关闭/陈旧/快截止 → 进关键提醒区（不受强度压制）。
// saved 岗被 eligibility 的 already_actioned 排除出主召回，所以这里单独取当前库状态派生。
async function buildCriticalAlerts(
  actions: RadarJobAction[],
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

/**
 * 召回快照（见 lib/jobs-store/recall-snapshot.ts）。只给「用户本人真实画像」那一次构建传——
 * 放宽条件 / 范围兜底重算用的是改过的画像，指纹对不上，传了也用不上，更不能拿它们的结果回写快照。
 */
export interface FeedRecallSnapshotOption {
  /** 页面在等悉尼那几条查询时就已经发出去的快照读取（永不 reject）。 */
  snapshot: Promise<RecallSnapshot | null> | RecallSnapshot | null;
  /** 召回做完后回调：页面据此在响应之后写 / 刷新快照（写库不进请求路径）。 */
  onRecall?: (info: Pick<RecallResult, "snapshot" | "snapshotWrite">) => void;
}

export async function buildOpportunityFeed(
  supabase: SupabaseLike,
  profile: RadarProfile,
  actions: RadarJobAction[],
  radarState: { last_opened_at: string | null } | null,
  options: OpportunityFeedOptions & { recallSnapshot?: FeedRecallSnapshotOption },
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

  // 三条互相独立的 I/O 并行：① 岗位召回（香港库）② 关键提醒（香港库，按 saved/applied 岗）
  // ③ source 元信息快照（Supabase 悉尼，跨实例缓存、**不依赖召回结果**）。
  //
  // ③ 之所以能回到并行里：它不再是「按召回涉及的 id 取」（那必须等召回出结果，线上实测这一跳
  // 串行 480ms = feed 总时长的 25%），而是全表 1,655 行 / 170KB 的跨实例快照——命中即零往返，
  // 未命中的那一次也躲在召回的影子里。详见 lib/opportunities/source-meta.ts。
  let recallMs = 0;
  let criticalMs = 0;
  let sourcemetaMs = 0;
  const [recall, critical, snapshot] = await Promise.all([
    (async () => {
      const s = clock();
      try {
        // 已处理过的岗（saved/ignored/applied）下推到 SQL 排除：它们在 stage-2 必被 already_actioned 挡掉，
        // 留在候选里只是白占名额。viewed 不算——那类岗仍可展示（只在打分里 -8）。
        const snapOpt = options.recallSnapshot;
        const r = await recallOpportunityCandidates(profile, now, supabase, {
          actionedJobIds: actionedIds,
          ...(snapOpt ? { snapshot: await snapOpt.snapshot } : {}),
        });
        snapOpt?.onRecall?.({ snapshot: r.snapshot, snapshotWrite: r.snapshotWrite });
        return r;
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
    (async () => {
      const s = clock();
      try {
        return await loadSourceMetaSnapshot();
      } finally {
        sourcemetaMs = clock() - s;
      }
    })(),
  ]);
  mark.recall = recallMs;
  mark.critical = criticalMs;
  mark.sourcemeta = sourcemetaMs;
  mark.parallel = clock() - t0; // 这一阶段的墙钟（= 三条里最慢的那条）

  // 快照取不到（首次部署 / Supabase 抖 / 缓存里是旧形状）→ 退回按 id 取，**不许当成「这批岗没有元信息」**：
  // 那会让 source_disabled 硬门整体失效，把已禁用源的岗静默放行。兜底是串行的，记进账本好识别。
  let sourceMeta = snapshot ?? new Map<string, SourceMeta>();
  let sourcemetaFallback = 0;
  if (!snapshot) {
    const s = clock();
    sourceMeta = await fetchSourceMetaFor(supabase, recall.jobs);
    sourcemetaFallback = clock() - s;
    mark.sourcemeta += sourcemetaFallback;
  }
  // 「这批候选涉及的源里，有几个真的拿到了元信息」——账本里唯一能看出静默降级的数字。
  // 报全表行数没用（快照恒 1,655）；命中率掉下来才说明 freshness / source_disabled 正在失效。
  const wantedSources = new Set<string>();
  for (const j of recall.jobs) if (j.source_id) wantedSources.add(j.source_id);
  let sourcemetaHits = 0;
  for (const id of wantedSources) if (sourceMeta.has(id)) sourcemetaHits += 1;

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
      exploreEligible: facts.roleTier === "related" || facts.companyHit || Boolean((job as any).recall_function_only),
      functionOnly: Boolean((job as any).recall_function_only) && facts.roleTier !== "exact",
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
  const hydrated = await hydrateDisplayJobs(sections);
  mark.hydrate = clock() - tHydrate;
  mark.total = clock() - t0;
  mark.candidates = recall.jobs.length;
  mark.displayed = Object.values(sections).reduce((n, arr) => n + arr.length, 0);

  // 一行可 grep 的分段账本（/today 要登录，外部 curl 不到，只能靠服务端日志；与 /jobs 的
  // `[jobs-search]` 同款）。**跨库传了多少字节**是这条链最该常开观测的数字：香港库出口带宽个位数 Mbps。
  console.log(
    `[today-feed] candidates=${mark.candidates} displayed=${mark.displayed} ` +
      `recall_rows=${recall.timing?.rows ?? mark.candidates} recall_kb=${kb(recall.timing?.bytes ?? 0)} ` +
      `hydrate_rows=${hydrated.rows} hydrate_kb=${kb(hydrated.bytes)} ` +
      `recall_ms=${Math.round(mark.recall)} critical_ms=${Math.round(mark.critical)} ` +
      `sourcemeta_ms=${Math.round(mark.sourcemeta)} sourcemeta_hit=${sourcemetaHits}/${wantedSources.size}` +
      `${sourcemetaFallback ? `(fallback ${Math.round(sourcemetaFallback)}ms)` : ""} ` +
      `recall_source=${recall.snapshot ? (recall.snapshot.used ? "snapshot" : `live:${recall.snapshot.reason}`) : "live"} ` +
      `snapshot_age_min=${recall.snapshot?.ageMs != null ? Math.round(recall.snapshot.ageMs / 60_000) : "-"} ` +
      `compute_ms=${Math.round(mark.compute)} ` +
      `group_ms=${Math.round(mark.group)} hydrate_ms=${Math.round(mark.hydrate)} total_ms=${Math.round(mark.total)}`,
  );

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
      // 跨库载荷（KB）：耗时会随实例/网络抖，字节数不会 —— 判「是不是又在拖行」看这两个。
      recallKb: kb(recall.timing?.bytes ?? 0),
      hydrateKb: kb(hydrated.bytes),
      recallSource: recall.snapshot?.used ? "snapshot" : "live",
      snapshotReason: recall.snapshot?.reason,
      snapshotAgeMin: recall.snapshot?.ageMs != null ? Math.round(recall.snapshot.ageMs / 60_000) : null,
    },
  };
}

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

// 批量取 source 元信息（sources 永远在 Supabase）；失败不抛，freshness 退化为 manual SLA（§14.2）。
// 取**全部** source 元信息（sources 是小表 ~800 行）。一次性取全表 = 可与召回并行（不再依赖召回回来的 source_ids，
// 省掉一条串行跨区往返）；失败不抛，freshness 退化为 manual SLA（§14.2）。
async function fetchSourceMeta(supabase: SupabaseLike): Promise<Map<string, SourceMeta>> {
  const map = new Map<string, SourceMeta>();
  try {
    const { data, error } = await supabase
      .from("sources")
      .select("id, company, adapter_name, crawl_method, last_checked_at, enabled");
    if (error) {
      console.warn("[opportunities] source metadata query failed:", error.message);
      return map;
    }
    for (const s of data || []) map.set(s.id, s as SourceMeta);
  } catch (e) {
    console.warn("[opportunities] source metadata query threw:", (e as Error).message);
  }
  return map;
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
  // 三条互相独立的 I/O 并行（旧实现是 recall→sourceMeta→…→critical 顺序 await，跨区往返串行叠加）：
  //   ① 岗位召回（香港库）② source 元信息（Supabase 全表）③ 关键提醒（香港库，按 saved/applied 岗）。
  // 并行后 today SSR 只吃最慢一条，而非三条之和。
  const [recall, sourceMeta, critical] = await Promise.all([
    recallOpportunityCandidates(profile, now, supabase),
    fetchSourceMeta(supabase),
    buildCriticalAlerts(actions, profile, intensity, now),
  ]);

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

  // 关键提醒（saved 岗关闭/快截止）已在上面与召回并行取好，置顶不受强度压制。
  const overrideProvided = options.noveltySinceOverride !== undefined && options.noveltySinceOverride !== null;
  const noveltySince = resolveNoveltySince(overrideProvided ? options.noveltySinceOverride! : lastOpenedAt, now);

  // 关键提醒在截断前与完整召回候选统一语义去重/分区，冲突主卡被淘汰时后续候选可正常回填。
  const { sections, counts } = groupOpportunities([...critical, ...opps], {
    dailyLimit: profile.dailyLimit,
    intensity,
    noveltySince,
    now,
  });
  counts.screened = recall.jobs.length;
  counts.filtered = filtered;

  await hydrateDisplayJobs(sections);

  return {
    generated_at: now.toISOString(),
    profile_ready: true,
    candidate_capped: recall.capped,
    last_opened_at: lastOpenedAt,
    stage: profile.experienceStage,
    intensity,
    counts,
    sections,
  };
}

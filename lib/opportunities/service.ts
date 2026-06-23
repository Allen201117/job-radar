// Opportunity Engine 编排（§6.1 / §7）：读画像 → 召回 → 逐岗算事实/硬门/打分 → 分区 → 组装 OpportunityFeed。
// 纯逻辑（facts/eligibility/scoring/grouping）已各自单测；本文件只做 DB 编排与组装，不重写匹配规则。
import "server-only";
import type { JobAction } from "../types";
import type {
  RadarProfile,
  Opportunity,
  OpportunityFeed,
  OpportunityFeedOptions,
  SourceMeta,
} from "./types";
import { isProfileReady } from "./profile";
import { computeMatchFacts, checkEligibility, type ActionState } from "./eligibility";
import { scoreOpportunity } from "./scoring";
import { groupOpportunities, resolveNoveltySince } from "./grouping";
import { recallOpportunityCandidates } from "@/lib/jobs-store/opportunities";

type SupabaseLike = { from: (table: string) => any };

const EMPTY_COUNTS = { new_since_last_open: 0, high_match: 0, verified: 0, aging: 0 };
const EMPTY_SECTIONS = { new: [], priority: [], explore: [], aging: [] };

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
async function fetchSourceMeta(supabase: SupabaseLike, sourceIds: string[]): Promise<Map<string, SourceMeta>> {
  const map = new Map<string, SourceMeta>();
  if (!sourceIds.length) return map;
  try {
    const { data, error } = await supabase
      .from("sources")
      .select("id, company, adapter_name, crawl_method, last_checked_at, enabled")
      .in("id", sourceIds);
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

export async function buildOpportunityFeed(
  supabase: SupabaseLike,
  profile: RadarProfile,
  actions: JobAction[],
  radarState: { last_opened_at: string | null } | null,
  options: OpportunityFeedOptions,
): Promise<OpportunityFeed> {
  const now = options.now ?? new Date();
  const lastOpenedAt = radarState?.last_opened_at ?? null;

  if (!isProfileReady(profile)) {
    return {
      generated_at: now.toISOString(),
      profile_ready: false,
      candidate_capped: false,
      last_opened_at: lastOpenedAt,
      counts: { ...EMPTY_COUNTS },
      sections: { ...EMPTY_SECTIONS },
    };
  }

  const recall = await recallOpportunityCandidates(profile, now, supabase);
  const actionMap = buildActionMap(actions);

  const sourceIds = Array.from(new Set(recall.jobs.map((j) => j.source_id).filter(Boolean) as string[]));
  const sourceMeta = await fetchSourceMeta(supabase, sourceIds);

  const opps: Opportunity[] = [];
  for (const job of recall.jobs) {
    const action = actionMap.get(job.id) || { primary: null, viewed: false };
    const facts = computeMatchFacts(job, profile, job.source_id ? sourceMeta.get(job.source_id) : undefined, action, now);
    const elig = checkEligibility(facts);
    if (!elig.eligible) continue;
    const { score, tier, reasons } = scoreOpportunity(facts, elig.degraded);
    if (tier === null) continue; // score < 30，不展示
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
    });
  }

  // 新增窗口：Today 用 last_opened_at；Email 传 noveltySinceOverride=max(last_sent,last_opened)；首访 → now-72h
  const overrideProvided = options.noveltySinceOverride !== undefined && options.noveltySinceOverride !== null;
  const noveltySince = resolveNoveltySince(overrideProvided ? options.noveltySinceOverride! : lastOpenedAt, now);

  const { sections, counts } = groupOpportunities(opps, profile.dailyLimit, noveltySince);

  return {
    generated_at: now.toISOString(),
    profile_ready: true,
    candidate_capped: recall.capped,
    last_opened_at: lastOpenedAt,
    counts,
    sections,
  };
}

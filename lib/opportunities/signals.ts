// 信号派生（04 spec §6）：信号是「标签」，不是入选唯一理由。返回按优先级排序的 OpportunitySignal[]（≥1）。
// 当前上线：STILL_OPEN（主力）/ DEADLINE_SOON / CLOSED_OR_STALE / CAMPUS_WINDOW(简单)。
// 暂不上：NEWLY_DISCOVERED / COMPANY_MOMENTUM —— 依赖官方 posted_at + job_events（Phase 3，见 04 §11.1）。
//
// 约束：
//  - enrich_checked_at 缺失 → 不产生 STILL_OPEN（meetsVerifyTier 兜底）；
//  - content_hash 变化不产生任何用户侧 signal（此处根本不读 content_hash）；
//  - 每个进 today 的 opportunity signals.length ≥ 1（active 岗必得 STILL_OPEN 或 CLOSED_OR_STALE 之一）。
import type { Job } from "../types";
import type { MatchFacts, RadarProfile, OpportunitySignal, OpportunitySignalType } from "./types";
import { meetsVerifyTier } from "./freshness";
import { parseDeadline } from "./deadline";

// 优先级：数字越小越优先（决定 primary signal = signals[0]、决定分区落点）。
const PRIORITY: Record<OpportunitySignalType, number> = {
  CLOSED_OR_STALE: 1,
  DEADLINE_SOON: 2,
  STILL_OPEN: 3,
  CAMPUS_WINDOW: 4,
  NEWLY_DISCOVERED: 5,
  COMPANY_MOMENTUM: 6,
};

const CLOSED_STATUSES = new Set(["expired", "removed", "error"]);

function deadlineWindowDays(profileStage: string, jobStage: string | null): number {
  // 校招 14 天、社招/实习 7 天（04 §6.2）。身份优先，其次岗位阶段。
  if (profileStage === "校招" || jobStage === "校招") return 14;
  return 7;
}

export interface SignalContext {
  isWatched?: boolean; // 该岗是否被用户 saved/applied/关注（决定 CLOSED_OR_STALE 是否升为关键提醒）
  parsedDeadline?: { date: string; confidence: "high" | "medium" } | null; // 不传则内部解析
}

export function deriveOpportunitySignals(
  job: Pick<Job, "status" | "enrich_checked_at" | "posted_at" | "deadline">,
  facts: Pick<MatchFacts, "freshness" | "stageLabel">,
  profile: Pick<RadarProfile, "experienceStage">,
  now: Date,
  ctx: SignalContext = {}
): OpportunitySignal[] {
  const out: OpportunitySignal[] = [];
  const isWatched = ctx.isWatched ?? false;
  const tier = meetsVerifyTier(job, "today", now);
  const lastCheckedAt = job.enrich_checked_at ?? null;
  const officialPostedAt = job.posted_at ?? null;
  const active = job.status === "active";

  const parsed = ctx.parsedDeadline !== undefined ? ctx.parsedDeadline : parseDeadline(job.deadline, now);

  // 1. CLOSED_OR_STALE —— 关闭（status 非 active）或陈旧（active 但未在 today SLA 内核验）。
  if (!active && CLOSED_STATUSES.has(job.status)) {
    out.push({
      type: "CLOSED_OR_STALE",
      label: "可能已关闭",
      priority: PRIORITY.CLOSED_OR_STALE,
      isCritical: isWatched, // 用户关注对象关闭 → 关键提醒；否则只是状态告知
      evidence: { lastCheckedAt, status: job.status, freshness: facts.freshness },
    });
  } else if (active && !tier.ok) {
    // active 但超 today 核验时限 / 从未核验 → 「长时间未确认」，进「等待再次确认」（非关键，除非被关注）。
    out.push({
      type: "CLOSED_OR_STALE",
      label: "长时间未确认",
      priority: PRIORITY.CLOSED_OR_STALE,
      isCritical: false,
      evidence: { lastCheckedAt, status: job.status, freshness: tier.freshness },
    });
  }

  // 2. DEADLINE_SOON —— 解析出明确日期且在窗口内（含今天，未过期）。校招身份置关键。
  if (active && parsed) {
    const ddl = new Date(`${parsed.date}T23:59:59Z`).getTime();
    const days = (ddl - now.getTime()) / 86_400_000;
    const window = deadlineWindowDays(profile.experienceStage, facts.stageLabel);
    if (days >= 0 && days <= window) {
      const dleft = Math.max(1, Math.ceil(days));
      out.push({
        type: "DEADLINE_SOON",
        label: `${dleft}天内截止`,
        priority: PRIORITY.DEADLINE_SOON,
        isCritical: profile.experienceStage === "校招",
        evidence: { deadlineAt: parsed.date, lastCheckedAt, freshness: facts.freshness },
      });
    }
  }

  // 3. STILL_OPEN —— active + 在 today 核验时限内（≤24h）+ 非关闭。护城河外显，主力标签。
  if (active && tier.ok) {
    out.push({
      type: "STILL_OPEN",
      label: "最近确认仍在招",
      priority: PRIORITY.STILL_OPEN,
      isCritical: false,
      evidence: { lastCheckedAt, officialPostedAt, freshness: tier.freshness },
    });
  }

  out.sort((a, b) => a.priority - b.priority);
  return out;
}

// 主信号（决定卡片首要标签与分区落点）。空数组返回 null（调用方保证 today 卡 ≥1）。
export function primarySignal(signals: OpportunitySignal[]): OpportunitySignal | null {
  return signals.length ? signals[0] : null;
}

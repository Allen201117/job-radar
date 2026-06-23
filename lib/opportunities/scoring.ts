// Opportunity Score V2（§6.6）+ 匹配原因（§6.7）。纯函数：只读 MatchFacts + degraded 列表，
// 不读 LLM、不读网络、不散落 Date.now()。所有权重写死在此，改权重必同步 tests/opportunity-scoring.test.js。
import type {
  MatchFacts,
  ScoreResult,
  OpportunityReason,
  OpportunityTier,
  DegradedDimension,
} from "./types";

// 内部 score → 展示档；<30 返回 null（不展示，由上层过滤）。
export function scoreTier(score: number): OpportunityTier | null {
  if (score >= 70) return "high";
  if (score >= 45) return "related";
  if (score >= 30) return "explore";
  return null;
}

// freshness 原因用「绝对可信表述」：24h 内 = 今天首次发现；否则 verified = 已确认仍在招；其余不出正向理由。
function freshnessReason(f: MatchFacts): OpportunityReason | null {
  if (f.noveltyHours != null && f.noveltyHours <= 24) return { type: "freshness", label: "今天首次发现" };
  if (f.freshness === "verified") return { type: "freshness", label: "已确认仍在招" };
  return null;
}

// 只展示正向理由；顺序 role→location→stage→industry→company→skill→freshness；最多 4 条。
export function buildReasons(f: MatchFacts): OpportunityReason[] {
  const out: OpportunityReason[] = [];
  if (f.roleTier === "exact") out.push({ type: "role", label: `方向匹配：${f.roleMatchLabel ?? "目标方向"}` });
  else if (f.roleTier === "related") out.push({ type: "role", label: `相关方向：${f.roleMatchLabel ?? "目标方向"}` });
  if (f.location === "match" && f.locationName) out.push({ type: "location", label: `目标城市 ${f.locationName}` });
  if (f.stage === "match" && f.stageLabel) out.push({ type: "stage", label: `${f.stageLabel}岗位` });
  if (f.industry === "match" && f.industryName) out.push({ type: "industry", label: `目标行业 ${f.industryName}` });
  if (f.companyHit && f.companyName) out.push({ type: "company", label: `你关注的公司 ${f.companyName}` });
  if (f.skillsHit.length > 0) out.push({ type: "skill", label: `技能匹配 ${f.skillsHit.slice(0, 3).join("、")}` });
  const fr = freshnessReason(f);
  if (fr) out.push(fr);
  return out.slice(0, 4);
}

export function scoreOpportunity(f: MatchFacts, degraded: readonly DegradedDimension[]): ScoreResult {
  let raw = 0;

  if (f.roleTier === "exact") raw += 35;
  else if (f.roleTier === "related") raw += 22;

  if (f.companyHit) raw += 15;

  if (f.location === "match") raw += 15;
  else if (f.location === "unknown") raw += 3;

  if (f.stage === "match") raw += 10;
  else if (f.stage === "unknown") raw += 3;

  if (f.industry === "match") raw += 10;
  else if (f.industry === "unknown") raw += 2;

  raw += Math.min(15, f.skillsHit.length * 3);

  if (f.noveltyHours != null) {
    if (f.noveltyHours <= 24) raw += 10;
    else if (f.noveltyHours <= 72) raw += 7;
    else if (f.noveltyHours <= 168) raw += 3;
  }

  if (f.summaryLong && f.freshness === "verified") raw += 5;

  if (f.viewed && !f.userAction) raw -= 8;

  raw += Math.max(-8, -2 * degraded.length);

  const score = Math.max(0, Math.min(100, raw));
  return { score, tier: scoreTier(score), reasons: buildReasons(f) };
}

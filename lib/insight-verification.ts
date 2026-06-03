// ============================================================
// 模块 B 职业洞察层 — 验证流水线（纯函数，PRD §7 合规 / §8.2 分级）
// 把「录入规则 + 自动校验门」落地为可单测的纯函数：
//   grade 门 / 去标识门 / 时效门 / 归因 lint / failure_reason 决策
// 不依赖网络、不依赖 DB，输入 item + 其溯源 sources，输出可否展示。
// ============================================================

import type { InsightItem, InsightSource } from "./types";

// experience 类条目要求的最小支撑样本量（PRD §8.2 阈值示例 N>=5）
export const EXPERIENCE_MIN_SAMPLE = 5;

// 洞察层失败原因（PRD §12）
export type InsightFailureReason = "insight_unverified" | "insight_outdated";

export interface InsightEvaluation {
  displayable: boolean;
  // 仍可展示但需标「可能已过时」
  outdated: boolean;
  failure_reason: InsightFailureReason | null;
}

// 产品口吻断言黑名单：一切评价必须聚合 + 归因，禁止产品自己下断言（PRD §7.2 / §14）
const BANNED_ASSERTIONS: RegExp[] = [
  /我们(认定|认为|断定|判定|觉得)/,
  /本产品(认为|认定|判定|断定)/,
  /平台(认定|断定|判定)/,
  /(毫无疑问|绝对|百分百|一定)是最/,
];

// 归因标记：评价性内容必须带「据 N 位反馈 / 根据公开数据」这类口径
const ATTRIBUTION =
  /据|根据|反馈|公开|官方|财报|公告|招股|统计|调查|报道|多位|多家|网友|社区|[0-9]+\s*[位名家]/;

export function hasTimeWindow(item: Pick<InsightItem, "time_window" | "valid_from" | "valid_until">): boolean {
  return Boolean(
    (item.time_window && item.time_window.trim()) || item.valid_from || item.valid_until,
  );
}

// valid_until 含当日有效；过当日则视为过时。time_window-only（如「每年 5–7 月」）属周期性，不自动过时。
export function isOutdated(
  item: Pick<InsightItem, "valid_until">,
  now: Date = new Date(),
): boolean {
  if (!item.valid_until) return false;
  const until = new Date(`${item.valid_until}T23:59:59.999Z`).getTime();
  if (Number.isNaN(until)) return false;
  return until < now.getTime();
}

function validSources(sources: InsightSource[] | undefined): InsightSource[] {
  return (sources || []).filter((s) => s && s.url && s.deidentified);
}

export function countDistinctPublishers(sources: InsightSource[] | undefined): number {
  const set = new Set<string>();
  for (const s of validSources(sources)) {
    set.add((s.publisher || s.url).trim().toLowerCase());
  }
  return set.size;
}

// grade 门：fact 须 >=1 有效来源；experience 须样本达标且来源 >=2 个不同 publisher；rumor 默认拦截
export function passesGradeGate(
  item: Pick<InsightItem, "grade" | "sample_size">,
  sources: InsightSource[] | undefined,
): boolean {
  const valid = validSources(sources);
  if (item.grade === "fact") return valid.length >= 1;
  if (item.grade === "experience") {
    const enoughSample = (item.sample_size || 0) >= EXPERIENCE_MIN_SAMPLE;
    return enoughSample && countDistinctPublishers(sources) >= 2;
  }
  // rumor：不进入 active 展示
  return false;
}

// 去标识门：item 自身与其引用的每个 source 都必须已去标识（PRD §7.2 PIPL / §8.5）
export function passesDeidentifiedGate(
  item: Pick<InsightItem, "deidentified">,
  sources: InsightSource[] | undefined,
): boolean {
  if (!item.deidentified) return false;
  return (sources || []).every((s) => s.deidentified);
}

export function containsBannedAssertion(content: string): boolean {
  return BANNED_ASSERTIONS.some((re) => re.test(content || ""));
}

export function hasAttribution(content: string): boolean {
  return ATTRIBUTION.test(content || "");
}

// 归因 lint：任何条目不得用产品口吻断言；experience 类还必须带归因口径
export function passesAssertionLint(
  item: Pick<InsightItem, "grade" | "content">,
): boolean {
  const content = item.content || "";
  if (containsBannedAssertion(content)) return false;
  if (item.grade === "experience" && !hasAttribution(content)) return false;
  return true;
}

// 单条评估：按顺序过 status / 去标识 / grade / 归因 / 时效 门，再判过时
export function evaluateInsight(
  item: InsightItem,
  sources: InsightSource[] | undefined,
  now: Date = new Date(),
): InsightEvaluation {
  if (item.status !== "active") {
    return { displayable: false, outdated: false, failure_reason: "insight_unverified" };
  }
  if (!passesDeidentifiedGate(item, sources)) {
    return { displayable: false, outdated: false, failure_reason: "insight_unverified" };
  }
  if (!passesGradeGate(item, sources)) {
    return { displayable: false, outdated: false, failure_reason: "insight_unverified" };
  }
  if (!passesAssertionLint(item)) {
    return { displayable: false, outdated: false, failure_reason: "insight_unverified" };
  }
  if (!hasTimeWindow(item)) {
    return { displayable: false, outdated: false, failure_reason: "insight_unverified" };
  }
  const outdated = isOutdated(item, now);
  return { displayable: true, outdated, failure_reason: outdated ? "insight_outdated" : null };
}

// 公司维度的 bundle 级失败决策（PRD §12）：
//   无任何可展示 → insight_unverified；仅有过时可展示 → insight_outdated；有新鲜 → null
export function resolveInsightFailure(
  evaluations: InsightEvaluation[],
): InsightFailureReason | null {
  const displayable = evaluations.filter((e) => e.displayable);
  if (displayable.length === 0) return "insight_unverified";
  const fresh = displayable.filter((e) => !e.outdated);
  if (fresh.length === 0) return "insight_outdated";
  return null;
}

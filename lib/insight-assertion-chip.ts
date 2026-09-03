// ============================================================
// v3 三档承诺芯片：事实（绿）/ 数据（蓝）/ 说法（灰）。
//
// 抽出来共享的理由：抽屉（CompanyInsightDrawer）与洞察库（/insights）必须**逐字一致**。
// 同一条洞察在两个地方读起来承诺不同，比没有承诺更糟——用户会以为是两回事。
// 文案遵循 spec §1.5：signal 只给数字（样本量是核心承诺），claim 必须读起来像转述，
// fact 才可以肯定陈述。
// ============================================================
import type { InsightAssertion, InsightGrade } from "./types";

export interface AssertionChip {
  text: string;
  cls: string;
}

const FACT_CLS =
  "border border-[#bcdcae] bg-[#e6f2d6] text-[#4f6f2a] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]";
const SIGNAL_CLS =
  "border border-[#a9cfd8] bg-[#dcf0f2] text-[#2f7d8a] dark:border-[#6cc0cf]/[0.30] dark:bg-[#6cc0cf]/[0.15] dark:text-[#6cc0cf]";
const CLAIM_CLS =
  "border border-black/[0.08] bg-[#f4efe6] ink-3 dark:border-white/[0.1] dark:bg-white/[0.08]";
const LEGACY_EXPERIENCE_CLS =
  "border border-[#e7c98a] bg-[#fbeecb] text-[#8a6312] dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]";

export const ASSERTION_LABEL: Record<InsightAssertion, string> = {
  fact: "事实",
  signal: "数据",
  claim: "说法",
};

/** 三档各自的一句话承诺，用于筛选器与图例——不许各处自己编。 */
export const ASSERTION_PROMISE: Record<InsightAssertion, string> = {
  fact: "有官方出处、有口径与时点，可核验",
  signal: "我们从自有在招岗位算出的观测量，只给数字不下结论",
  claim: "公开讨论里的说法，是转述不是我们的结论",
};

export function assertionChip(
  assertion: InsightAssertion | null | undefined,
  grade: InsightGrade,
  sampleSize: number | null,
  publisherCount: number,
  payload?: Record<string, unknown> | null,
): AssertionChip {
  // 取实际 sample_n（v3 派生层写在 payload.sample_n）
  const sampleN =
    sampleSize ??
    (typeof payload?.sample_n === "number" ? payload.sample_n : null) ??
    (typeof payload?.active_count === "number" ? payload.active_count : null);

  if (assertion === "fact") {
    return { text: "事实 · 据官方披露", cls: FACT_CLS };
  }
  if (assertion === "signal") {
    // signal：只给数字，不下结论。样本量是核心承诺。
    const nLabel = sampleN != null ? `基于 ${sampleN} 个在招岗` : "基于在招岗位";
    return { text: `数据 · ${nLabel}`, cls: SIGNAL_CLS };
  }
  if (assertion === "claim") {
    // claim：必须读起来像转述，来源数是承诺。
    const claimLabel = publisherCount > 0 ? `据 ${publisherCount} 处公开讨论` : "公开讨论";
    return { text: `说法 · ${claimLabel}`, cls: CLAIM_CLS };
  }
  // assertion=null：存量行，回落 grade 逻辑（兼容迁移期）
  if (grade === "fact") {
    return { text: "事实 · 公开来源", cls: FACT_CLS };
  }
  const expText = sampleSize
    ? `经验 · 据约 ${sampleSize} 条反馈`
    : publisherCount > 0
      ? `经验 · 据 ${publisherCount} 个公开来源`
      : "经验 · 群体反馈";
  return { text: expText, cls: LEGACY_EXPERIENCE_CLS };
}

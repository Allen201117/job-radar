// 「匹配岗位数」的展示口径（/jobs 计数行、筛选弹窗的「查看 N 个岗位」共用同一份）。
//
// 为什么需要它：检索层是「先取一批候选、再在 JS 里精筛」的，候选有取数上限（FTS 8000 /
// 扫描 28000）。候选撞上限时 total 只是「取到这么多」，不是真实匹配数——线上「深圳 + 社招」
// 因此长期显示「8000 个匹配岗位」，而库里其实有 15,290 个（2026-09-03 实测）。
// 「指标诚实」是本产品的最高优先级原则之一：拿不到真实值时就别给确定数字。
export type MatchTotal = {
  /** 展示用文案：精确时是数字本身，只知道下限时是「8000+」。 */
  text: string;
  /** true = 只知道「至少这么多」，调用方不得再基于它算差值（如「还有 N 个」）。 */
  approximate: boolean;
};

export function formatMatchTotal(
  total: number,
  capped: boolean,
  exactTotal?: number | null,
): MatchTotal {
  const shown = Number.isFinite(total) && total > 0 ? Math.floor(total) : 0;
  if (!capped) return { text: String(shown), approximate: false };
  // 服务端只在能证明数字正确时才回填 exactTotal（见 lib/jobs-store/search.ts）。
  // 真实总数不可能比已经排出来的还少，比它小说明这个数不可信 → 退回下限表述。
  if (typeof exactTotal === "number" && Number.isFinite(exactTotal) && exactTotal >= shown) {
    return { text: String(Math.floor(exactTotal)), approximate: false };
  }
  return { text: `${shown}+`, approximate: true };
}

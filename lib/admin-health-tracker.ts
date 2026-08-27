
// ⚠️ 这里原本还有一个 dailyTrackerTone（热力图专用的「任一失败即红」判据），已于 2026-08-27 删除。
// 它是全站第二套模块判据，与模块卡的判据方向相反 —— 同一天同一份 ops_runs，热力图判红、模块卡判绿，
// 线上出现过「热力图 29 格 28 格红，而每个模块卡都写着 ● 正常」。
// 现在全站唯一判据是 lib/admin-health.ts 的 moduleVerdict（产出量是入参）。**不要再在这里加第二套。**

export function nullableShare(numerator: number | null | undefined, denominator: number | null | undefined): number | null {
  if (numerator == null || denominator == null || denominator <= 0) return null;
  return numerator / denominator;
}

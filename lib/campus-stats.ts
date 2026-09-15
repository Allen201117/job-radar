// 校招看板「计数 + 新鲜度」的纯聚合：把库里按 company 分组的原始计数行，按必投清单归属规则
// 折叠成 per-pattern 的 {campusTotal, internTotal, lastSeenAtMs}。无网络无 DB，独立可测。
//
// 为什么单独拆出来（2026-09-15）：/campus 把整块看板（分面/时间线/计数）打包进一个
// unstable_cache 快照，这块重活偶发跑不完/报错 → Next **永远服务旧快照且不报错** → 快照里的
// 计数与 last_seen 一起冻住 → 每张卡算出「距今>72h」→ 全部「数据待更新」（实测冻 3 天，数据其实
// 当天还在更新）。计数和 last_seen 都是轻字段，独立现算既便宜又不受重快照成败影响。此文件只管
// 折叠逻辑，取数在 lib/jobs-store/read.ts 的 getCampusFreshStats。彻底解法是物化派生字段（重构项目）。
//
// ⚠️ 归属规则必须与 getCampusZone / getCampusCompanyJobs / 分面计数**逐字一致**：
//    list 里第一个 pattern 命中（不区分大小写子串）者得（%腾讯音乐% 排在 %腾讯% 前，所以
//    「腾讯音乐 TME」归前者不归后者）。这是第四处用到该规则，任一处漂移都会让卡面计数对不上列表。

export type CampusStatRow = {
  company: string | null;
  campus_total: number | string | null;
  intern_total: number | string | null;
  last_seen: string | null;
};

export type CampusFreshStat = {
  campusTotal: number;
  internTotal: number;
  lastSeenAtMs: number | null;
};

export function aggregateCampusFreshStats(
  rows: CampusStatRow[],
  list: Array<{ name: string; pattern: string }>,
): Map<string, CampusFreshStat> {
  const byPattern = new Map<string, CampusFreshStat>();
  for (const c of list) byPattern.set(c.pattern, { campusTotal: 0, internTotal: 0, lastSeenAtMs: null });
  for (const r of rows) {
    const companyLower = String(r.company || "").toLowerCase();
    if (!companyLower) continue;
    // 第一个命中的 pattern 得（与 getCampusZone 同序同规则）；patterns 是人工策展的互异公司名。
    const owner = list.find((c) => companyLower.includes(c.pattern.replace(/%/g, "").toLowerCase()));
    if (!owner) continue;
    const agg = byPattern.get(owner.pattern);
    if (!agg) continue;
    agg.campusTotal += Number(r.campus_total) || 0;
    agg.internTotal += Number(r.intern_total) || 0;
    const seen = r.last_seen ? Date.parse(r.last_seen) : NaN;
    if (!Number.isNaN(seen)) agg.lastSeenAtMs = Math.max(agg.lastSeenAtMs ?? 0, seen);
  }
  return byPattern;
}

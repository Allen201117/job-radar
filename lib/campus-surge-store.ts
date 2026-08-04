import { createServiceClient } from "@/lib/supabaseService";

// 「刚开正式批」读侧：取近 N 天判定为开闸（surge）的快照，按必投清单公司归位（key=pattern）。
//
// 数据来源 campus_board_snapshots 由 crawler/campus_crawl.py 在校招高频车道跑完后写入，
// 判据是 campus_lane.detect_surge（校招岗数 ≥ 上次的 3 倍，或 ≥ 上次 +50）。
// 展示这条信息的价值：秋招正式批是**一次性放量**，用户最需要知道「谁刚开、该马上投」。

export type CampusSurge = {
  atMs: number;          // 判定开闸的时刻
  fromCount: number | null;
  toCount: number;
};

const SURGE_WINDOW_DAYS = 7;

export async function getRecentCampusSurges(
  list: Array<{ name: string; pattern: string }>,
  withinDays: number = SURGE_WINDOW_DAYS,
): Promise<Map<string, CampusSurge>> {
  const out = new Map<string, CampusSurge>();
  if (!list.length) return out;
  const since = new Date(Date.now() - withinDays * 86400_000).toISOString();
  const service = createServiceClient();
  const { data, error } = await service
    .from("campus_board_snapshots")
    .select("company, campus_job_count, prev_campus_job_count, captured_at")
    .eq("surge", true)
    .gte("captured_at", since)
    .order("captured_at", { ascending: false });
  if (error) {
    // 不吞错：开闸标记缺失只是少一个徽章，绝不该让整个校招专区挂掉。
    console.error("[campus-surge] 读取失败", error.message);
    return out;
  }

  for (const c of list) {
    const needle = c.pattern.replace(/%/g, "").toLowerCase();
    if (!needle) continue;
    // 已按 captured_at 倒序，find 命中的即该公司最近一次开闸。
    // 匹配用 sources.company 含 pattern 关键词（与 campus-sources.ts 的归位口径一致）。
    const row = (data || []).find((r: any) => String(r.company || "").toLowerCase().includes(needle));
    if (!row) continue;
    const atMs = Date.parse(row.captured_at);
    if (Number.isNaN(atMs)) continue;
    out.set(c.pattern, {
      atMs,
      fromCount: row.prev_campus_job_count ?? null,
      toCount: row.campus_job_count,
    });
  }
  return out;
}

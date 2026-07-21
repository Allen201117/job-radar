// ============================================================
// 校招洞察 P2 — 招聘周期纯函数（无 LLM/网络/DB，node --test 可测）
// 只 import 类型（被 transpile 擦除）；禁 @/ 别名运行时 import（见 Global Constraints）。
// ============================================================

export type CycleSeason = "秋招" | "春招";
export type CycleBatch = "提前批" | "正式批" | "补录" | "实习转正";
export type CycleEvent = "开放" | "截止" | "黄金期" | "结束";

export interface RecruitmentObservation {
  id?: string;
  grad_class: string;
  season: CycleSeason;
  batch: CycleBatch;
  event: CycleEvent;
  time_expr_type?: string;
  value_text: string;
  month_start: number | null;
  month_end: number | null;
  date_start?: string | null;
  date_end?: string | null;
  confidence?: string | null;
  evidence_url?: string | null;
  evidence_excerpt?: string | null;
  source_kind?: string | null;
  verify_status?: string | null;
  valid_until?: string | null;
}

export interface CampusTimeline {
  gradClass: string;
  season: CycleSeason;
  batchBits: string[];
  phaseLabel: string | null;
}

const BATCH_ORDER: Record<CycleBatch, number> = {
  提前批: 0,
  正式批: 1,
  补录: 2,
  实习转正: 3,
};

function ymd(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

// 是否落在窗口内（支持 month_start>month_end 的跨年环绕）
function inWindow(m: number, start: number, end: number): boolean {
  return start <= end ? m >= start && m <= end : m >= start || m <= end;
}

export function campusTimelineSummary(
  observations: RecruitmentObservation[],
  now: Date = new Date(),
): CampusTimeline | null {
  const today = ymd(now);
  const usable = (observations || []).filter(
    (o) =>
      o &&
      o.month_start != null &&
      (o.event === "开放" || o.event === "黄金期") &&
      (!o.verify_status || o.verify_status === "verified") &&
      (!o.valid_until || o.valid_until >= today),
  );
  if (usable.length === 0) return null;

  const m = now.getMonth() + 1;
  const preferred: CycleSeason = m >= 5 && m <= 12 ? "秋招" : "春招";
  const inPreferred = usable.filter((o) => o.season === preferred);
  const picked = inPreferred.length > 0 ? inPreferred : usable;
  const season = picked[0].season;
  const seasonObs = usable.filter((o) => o.season === season);

  // 按批次去重（保留 month_start 最小），再按批次序排
  const byBatch = new Map<CycleBatch, RecruitmentObservation>();
  for (const o of seasonObs) {
    const cur = byBatch.get(o.batch);
    if (!cur || (o.month_start ?? 99) < (cur.month_start ?? 99)) byBatch.set(o.batch, o);
  }
  const batches = Array.from(byBatch.values()).sort(
    (a, b) => BATCH_ORDER[a.batch] - BATCH_ORDER[b.batch],
  );

  const batchBits = batches.map((o) => `${o.batch}${o.value_text}`);

  // 当前阶段
  let phaseLabel: string | null = null;
  const hit = batches.find(
    (o) => o.month_start != null && o.month_end != null && inWindow(m, o.month_start, o.month_end),
  );
  if (hit) {
    phaseLabel = hit.event === "黄金期" ? "现处黄金期" : `现处${hit.batch}`;
  } else {
    const maxEnd = Math.max(...batches.map((o) => o.month_end ?? o.month_start ?? 0));
    if (m > maxEnd && m - maxEnd <= 3) phaseLabel = "往年这时多已近尾声";
  }

  return { gradClass: batches[0].grad_class, season, batchBits, phaseLabel };
}

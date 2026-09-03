// ============================================================
// 校招洞察 P2 — 招聘周期纯函数（无 LLM/网络/DB，node --test 可测）
// 只 import 类型（被 transpile 擦除）；禁 @/ 别名运行时 import（见 Global Constraints）。
// ============================================================

import { currentGradClass } from "@/lib/grad-class";

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
  /** 这条时间线**依据什么**——决定 UI 该说「今年·据官方公告」/「今年·据公开信息」/「据往年」。
   *  ⚠️ 措辞必须由数据推出来，不能写死在 JSX 里：库里 113 条观测 grad_class 全是「2027届」，
   *  UI 却硬编码「据往年」，卡面就出现了「据往年 2027届」这种字面自相矛盾的标签（用户实锤）。 */
  basis: "official" | "public" | "historical";
}

/** 额外事实输入。目前只有一项：该公司**当下的在招校招岗数**。 */
export interface CampusTimelineFacts {
  campusJobCount?: number;
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

/** 观测的届别（"2027届"）取整数年；取不到返回 null。 */
function gradYear(gradClass: string | undefined | null): number | null {
  const m = /(\d{4})/.exec(String(gradClass || ""));
  return m ? Number(m[1]) : null;
}

export function campusTimelineSummary(
  observations: RecruitmentObservation[],
  now: Date = new Date(),
  facts: CampusTimelineFacts = {},
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
    // 肯定性判断：与「正在招聘」不矛盾，照常输出。
    phaseLabel = hit.event === "黄金期" ? "现处黄金期" : `现处${hit.batch}`;
  } else {
    const maxEnd = Math.max(...batches.map((o) => o.month_end ?? o.month_start ?? 0));
    if (m > maxEnd && m - maxEnd <= 3) {
      // ⚠️ 否定性判断（「快结束了」）必须让位于硬证据。
      // 实测：高途 212 个在招校招岗、作业帮 53 个，卡面徽章写「🟢 招聘中」，
      // 同一张卡的时间线却写「往年这时多已近尾声」—— 推测在视觉上压过了事实，正是用户说的「标签矛盾」。
      // `windowStatus` 早就立过同一条规矩（有真实校招岗就不能判「待接入」），这里补齐。
      // 自有岗位库是第一手事实，外部聚合的月份窗口是推测；打架时宁可不说，也不说错。
      const hasLiveCampusJobs = (facts.campusJobCount ?? 0) > 0;
      // 措辞也改了：原文「往年这时多已近尾声」在数据其实是本届时同样自相矛盾，
      // 统一改成自陈推测的「推测已近尾声」，依据强弱交给 basis 那层去表达。
      phaseLabel = hasLiveCampusJobs ? null : "推测已近尾声";
    }
  }

  // basis：本届数据不许说「据往年」。官方源 > 公开聚合 > 往届规律。
  const currentYear = currentGradClass(now);
  const isCurrentCohort = batches.some((o) => {
    const y = gradYear(o.grad_class);
    return y !== null && y >= currentYear;
  });
  const hasOfficial = batches.some((o) => o.source_kind === "official_site");
  const basis: CampusTimeline["basis"] = !isCurrentCohort
    ? "historical"
    : hasOfficial
      ? "official"
      : "public";

  return { gradClass: batches[0].grad_class, season, batchBits, phaseLabel, basis };
}

// ============================================================
// P3 —— 今年精确日期展示 + 批次时间差 + 快路① deadline 清洗（均为纯函数）
// ============================================================

const BATCH_ORDER_P3: Record<string, number> = { 提前批: 0, 正式批: 1, 补录: 2, 实习转正: 3 };

// 取 verified + 未过期的当季观测（当季优先，同 campusTimelineSummary 的季判定口径）。
function _usableRows(observations: RecruitmentObservation[], now: Date) {
  const today = ymd(now);
  const m = now.getMonth() + 1;
  const preferred: CycleSeason = m >= 5 && m <= 12 ? "秋招" : "春招";
  const rows = (observations || []).filter(
    (o) =>
      o &&
      (!o.verify_status || o.verify_status === "verified") &&
      (!o.valid_until || o.valid_until >= today),
  );
  const inPref = rows.filter((o) => o.season === preferred);
  return inPref.length > 0 ? inPref : rows;
}

// 今年精确日期展示 bit（据官方公告的确切网申/截止日期）。每批次取一条，按批次序排。
export function campusPreciseDates(
  observations: RecruitmentObservation[],
  now: Date = new Date(),
): { label: string; batch: string }[] {
  const rows = _usableRows(observations, now).filter(
    (o) => o.time_expr_type === "精确日期" || o.time_expr_type === "日期范围",
  );
  const byBatch = new Map<string, RecruitmentObservation>();
  for (const o of rows) {
    if (!byBatch.has(o.batch)) byBatch.set(o.batch, o);
  }
  return Array.from(byBatch.values())
    .sort((a, b) => (BATCH_ORDER_P3[a.batch] ?? 9) - (BATCH_ORDER_P3[b.batch] ?? 9))
    .map((o) => ({ label: `${o.batch}${o.value_text}`, batch: o.batch }));
}

// 提前批 vs 正式批 时间差（cycle 级，仅时间不碰 HC/难度）。两批「开放」都有 month_start 才算。
export function campusBatchTimingGap(
  observations: RecruitmentObservation[],
  now: Date = new Date(),
): string | null {
  const rows = _usableRows(observations, now).filter(
    (o) => o.event === "开放" && o.month_start != null,
  );
  const early = rows.find((o) => o.batch === "提前批");
  const main = rows.find((o) => o.batch === "正式批");
  if (!early || !main || early.month_start == null || main.month_start == null) return null;
  const weeks = Math.round((main.month_start - early.month_start) * 4.3);
  if (weeks <= 0) return null;
  return `提前批比正式批约早 ${weeks} 周`;
}

// 快路①：清洗 text deadline，仅接受近未来真实日期（滤「长期有效」/占位/远未来/过去）。
export function cleanCampusDeadlineMs(
  deadlineText: string | null,
  now: Date = new Date(),
): number | null {
  if (!deadlineText || !/^\d{4}-\d{2}-\d{2}$/.test(deadlineText.trim())) return null;
  const t = Date.parse(deadlineText.trim() + "T00:00:00Z");
  if (Number.isNaN(t)) return null;
  const nowMs = now.getTime();
  const maxMs = nowMs + 550 * 24 * 3600 * 1000;
  if (t < nowMs || t > maxMs) return null;
  return t;
}

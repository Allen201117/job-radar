// ============================================================
// ③ 个性化职业路径 — 确定性引擎（纯函数，无 LLM）
// 把用户画像（目标公司/岗位/阶段）与洞察层四维做规则匹配，
// 输出「时机 × 方向 × 路径 × 文化/温馨提示」。输出为结构化，未来可挂 LLM 叙事层（只润色、不新增事实）。
// ============================================================

import type {
  CareerCompanyRec,
  CareerNote,
  CareerPathReport,
  CareerTimingStatus,
  InsightDimension,
  InsightItemView,
} from "./types";

export interface CareerCompanyInput {
  company: string;
  display_name: string | null;
  job_count: number;
  dimensions: Record<InsightDimension, InsightItemView[]>;
}

export interface ParsedWindow {
  months: Set<number>;
  rolling: boolean; // 全年滚动
  negative: boolean; // 该窗口是「HC 偏紧/非招聘」语义
  parseable: boolean;
}

// 「HC 偏紧/淡季/非招聘」语义 → 命中当月反而代表不利窗口（如微软 5–7 月）
const NEGATIVE_WINDOW =
  /偏紧|非招聘|淡季|no\s*headcount|hc\s*少|hc\s*偏紧|冻结|hiring\s*freeze/i;
const ROLLING_WINDOW = /全年|滚动|rolling|year[\s-]*round/i;

export function parseRecruitingMonths(timeWindow: string | null | undefined): ParsedWindow {
  const text = String(timeWindow || "");
  const rolling = ROLLING_WINDOW.test(text);
  const negative = NEGATIVE_WINDOW.test(text);
  const months = new Set<number>();

  // 统一分隔符（中英破折号/波浪号/到/至 → '-'）
  const norm = text.replace(/[–—－~〜]/g, "-").replace(/[到至]/g, "-");

  // 区间：8-10 月 / 5-7月
  const rangeRe = /(\d{1,2})\s*-\s*(\d{1,2})\s*月/g;
  let m: RegExpExecArray | null;
  while ((m = rangeRe.exec(norm)) !== null) {
    const a = Number(m[1]);
    const b = Number(m[2]);
    if (a >= 1 && a <= 12 && b >= 1 && b <= 12) {
      const lo = Math.min(a, b);
      const hi = Math.max(a, b);
      for (let i = lo; i <= hi; i++) months.add(i);
    }
  }

  // 去掉区间后扫单月：3-4 月 已处理，剩下 "X 月"
  const singlesText = norm.replace(rangeRe, " ");
  const singleRe = /(\d{1,2})\s*月/g;
  while ((m = singleRe.exec(singlesText)) !== null) {
    const n = Number(m[1]);
    if (n >= 1 && n <= 12) months.add(n);
  }

  return { months, rolling, negative, parseable: rolling || months.size > 0 };
}

const STATUS_LABEL: Record<CareerTimingStatus["status"], string> = {
  open: "招聘窗口期",
  rolling: "全年滚动",
  closed: "可能非窗口期",
  unknown: "时机未知",
};

// 多条 timing 洞察综合判定当前窗口状态
export function timingStatus(
  timingItems: InsightItemView[],
  now: Date = new Date(),
): CareerTimingStatus {
  const month = now.getMonth() + 1;
  let best: { rank: number; status: CareerTimingStatus["status"]; detail: string | null } = {
    rank: -1,
    status: "unknown",
    detail: null,
  };
  // 优先级：open(3) > rolling(2) > closed(1) > unknown(0)
  const RANK: Record<CareerTimingStatus["status"], number> = {
    open: 3,
    rolling: 2,
    closed: 1,
    unknown: 0,
  };

  for (const item of timingItems || []) {
    const w = parseRecruitingMonths(item.time_window);
    let status: CareerTimingStatus["status"] = "unknown";
    if (w.months.size > 0) {
      const inRange = w.months.has(month);
      if (w.negative) status = inRange ? "closed" : "unknown";
      else status = inRange ? "open" : "closed";
    } else if (w.rolling) {
      status = "rolling";
    } else {
      status = "unknown";
    }
    if (RANK[status] > best.rank) {
      best = { rank: RANK[status], status, detail: item.time_window };
    }
  }

  return { status: best.status, label: STATUS_LABEL[best.status], detail: best.detail };
}

function noteFrom(items: InsightItemView[]): string | null {
  const it = (items || [])[0];
  if (!it) return null;
  if (it.title && it.title.trim()) return it.title.trim();
  const c = (it.content || "").trim();
  return c ? (c.length > 48 ? c.slice(0, 48) + "…" : c) : null;
}

const TIMING_WEIGHT: Record<CareerTimingStatus["status"], number> = {
  open: 3,
  rolling: 2,
  unknown: 1,
  closed: 0,
};

export function buildCareerPath(
  profile:
    | { target_roles?: string[] | null; seniority?: string | null; target_locations?: string[] | null }
    | null,
  companies: CareerCompanyInput[],
  isFallback: boolean,
  now: Date = new Date(),
): CareerPathReport {
  const targetRoles = (profile?.target_roles || []).filter(Boolean);
  const seniority = profile?.seniority || null;
  const targetLocations = (profile?.target_locations || []).filter(Boolean);
  const hasProfile = Boolean(targetRoles.length || seniority || targetLocations.length);

  const recommendations: CareerCompanyRec[] = (companies || []).map((c) => {
    const timing = timingStatus(c.dimensions?.timing || [], now);
    const comp_note = noteFrom(c.dimensions?.compensation_intensity || []);
    const caution_note = noteFrom(c.dimensions?.culture || []);
    const reasons: string[] = [timing.label];
    if (c.job_count > 0) reasons.push(`${c.job_count} 个在招岗位`);
    if (caution_note) reasons.push("有温馨提示");
    return {
      company: c.company,
      display_name: c.display_name,
      timing,
      job_count: c.job_count || 0,
      comp_note,
      caution_note,
      reasons,
    };
  });

  // 排序：时机权重优先，其次在招岗位数
  recommendations.sort((a, b) => {
    const tw = TIMING_WEIGHT[b.timing.status] - TIMING_WEIGHT[a.timing.status];
    if (tw !== 0) return tw;
    return b.job_count - a.job_count;
  });

  const path_notes: CareerNote[] = (companies || []).flatMap((c) =>
    (c.dimensions?.path || []).map((it) => ({
      company: c.display_name || c.company,
      title: it.title,
      content: it.content,
    })),
  );

  const cautions: CareerNote[] = (companies || []).flatMap((c) =>
    (c.dimensions?.culture || []).map((it) => ({
      company: c.display_name || c.company,
      title: it.title,
      content: it.content,
    })),
  );

  let failure_reason: CareerPathReport["failure_reason"] = null;
  if (recommendations.length === 0) {
    failure_reason = hasProfile ? "insight_unverified" : "no_profile";
  }

  return {
    has_profile: hasProfile,
    profile_summary: {
      target_roles: targetRoles,
      seniority,
      target_locations: targetLocations,
    },
    is_recommended_fallback: isFallback,
    recommendations,
    path_notes,
    cautions,
    failure_reason,
  };
}

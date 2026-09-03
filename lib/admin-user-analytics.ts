// ============================================================
// 管理员看板「用户行为」模块的数据契约与派生结论。
//
// 分工：SQL（migration 204 admin_user_analytics）只负责**取数与去标识**，
// 「这组数字意味着什么」一律在这里用纯函数算，便于单测、也便于口径改动时一处生效。
//
// 三条口径不变量：
//  1) 读不到数据 → 返回 null，绝不返回 0。0 和「读失败」在看板上是完全不同的结论。
//  2) 样本不足不出结论：低于 MIN_SAMPLE 的比率只展示原始分子分母，不展示百分比、不上色。
//  3) 新埋点（页面浏览 / 搜索结果）上线前没有历史数据，要明说「正在积累」，不显示 0%。
// ============================================================

import type { BandTone } from "@/lib/admin-health";

export type FunnelStep = { key: string; label: string; users: number };

export type UserAnalytics = {
  generatedAt: string | null;
  windowDays: number;
  includeStaff: boolean;
  excludedUsers: number;
  totals: { registered: number; activated: number; todayActive: number; weekActive: number };
  funnel: FunnelStep[];
  sideMetrics: { resumeUploaded: number; onboardingBlocked: number; saved: number };
  retention: {
    d7Cohort: number; d7Returned: number;
    d30Cohort: number; d30Returned: number;
    everCohort: number; everReturned: number;
  };
  activeDays: { one: number; twoToSix: number; sevenPlus: number };
  dailyActive: Array<{ date: string; users: number; events: number }>;
  search: {
    searches: number;
    zeroSearches: number;
    topKeywords: Array<{ value: string; count: number; zero: number }>;
    topCities: Array<{ value: string; count: number }>;
    topFunctions: Array<{ value: string; count: number }>;
  };
  recommendation: {
    feedOpens: number; cardClicks: number; officialOpens: number; saves: number; applies: number;
  };
  pages: Array<{ path: string; views: number; users: number }>;
  users: Array<{
    uid: string;
    signupDate: string;
    activeDays: number;
    lastActive: string | null;
    events: number;
    industries: string[];
    stage: string;
    step: number;
  }>;
};

// 比率低于这个样本量就不给百分比——70 人体量下，5 个人的分母算出来的「40%」没有意义。
export const MIN_SAMPLE = 10;

function num(value: unknown, fallback = 0): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function arr<T>(value: unknown, map: (item: any) => T): T[] {
  return Array.isArray(value) ? value.map(map) : [];
}

// 把 SQL 返回的 jsonb 收敛成强类型。任何缺字段都退化成 0 / 空数组，绝不抛。
export function normalizeUserAnalytics(raw: unknown): UserAnalytics | null {
  if (!raw || typeof raw !== "object") return null;
  const d = raw as Record<string, any>;
  const totals = d.totals || {};
  const ret = d.retention || {};
  const hist = d.active_days_hist || {};
  const side = d.side_metrics || {};
  const search = d.search || {};
  const rec = d.recommendation || {};
  return {
    generatedAt: str(d.generated_at) || null,
    windowDays: num(d.window_days, 30),
    includeStaff: Boolean(d.include_staff),
    excludedUsers: num(d.excluded_users),
    totals: {
      registered: num(totals.registered),
      activated: num(totals.activated),
      todayActive: num(totals.today_active),
      weekActive: num(totals.week_active),
    },
    funnel: arr(d.funnel, (s) => ({ key: str(s?.key), label: str(s?.label), users: num(s?.users) })),
    sideMetrics: {
      resumeUploaded: num(side.resume_uploaded),
      onboardingBlocked: num(side.onboarding_blocked),
      saved: num(side.saved),
    },
    retention: {
      d7Cohort: num(ret.d7_cohort), d7Returned: num(ret.d7_returned),
      d30Cohort: num(ret.d30_cohort), d30Returned: num(ret.d30_returned),
      everCohort: num(ret.ever_cohort), everReturned: num(ret.ever_returned),
    },
    activeDays: { one: num(hist.one), twoToSix: num(hist.two_to_six), sevenPlus: num(hist.seven_plus) },
    dailyActive: arr(d.daily_active, (p) => ({ date: str(p?.date), users: num(p?.users), events: num(p?.events) })),
    search: {
      searches: num(search.searches),
      zeroSearches: num(search.zero_searches),
      topKeywords: arr(search.top_keywords, (k) => ({ value: str(k?.value), count: num(k?.count), zero: num(k?.zero) })),
      topCities: arr(search.top_cities, (k) => ({ value: str(k?.value), count: num(k?.count) })),
      topFunctions: arr(search.top_functions, (k) => ({ value: str(k?.value), count: num(k?.count) })),
    },
    recommendation: {
      feedOpens: num(rec.feed_opens), cardClicks: num(rec.card_clicks),
      officialOpens: num(rec.official_opens), saves: num(rec.saves), applies: num(rec.applies),
    },
    pages: arr(d.pages, (p) => ({ path: str(p?.path), views: num(p?.views), users: num(p?.users) })),
    users: arr(d.users, (u) => ({
      uid: str(u?.uid),
      signupDate: str(u?.signup_date),
      activeDays: num(u?.active_days),
      lastActive: str(u?.last_active) || null,
      events: num(u?.events),
      industries: arr(u?.industries, (x) => str(x)).filter(Boolean),
      stage: str(u?.stage),
      step: num(u?.step, 1),
    })),
  };
}

// 比率：样本不足返回 null（调用方据此显示「样本还不够」而不是一个假百分比）。
export function rate(numerator: number, denominator: number): number | null {
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator)) return null;
  if (denominator < MIN_SAMPLE) return null;
  return Math.max(0, Math.min(1, numerator / denominator));
}

export function formatPct(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

// 漏斗里最大的那道坎。返回 null = 还没有可判断的流失（人太少或没有下降）。
export function biggestDrop(funnel: FunnelStep[]): { from: FunnelStep; to: FunnelStep; lost: number; keepRate: number } | null {
  let worst: { from: FunnelStep; to: FunnelStep; lost: number; keepRate: number } | null = null;
  for (let i = 1; i < funnel.length; i += 1) {
    const from = funnel[i - 1];
    const to = funnel[i];
    const lost = from.users - to.users;
    if (lost <= 0 || from.users <= 0) continue;
    const keepRate = to.users / from.users;
    if (!worst || lost > worst.lost) worst = { from, to, lost, keepRate };
  }
  return worst;
}

// 看板顶部那句话。必须是**结论**不是数字复述，读完就知道下一步该动哪儿。
export function headlineSentence(a: UserAnalytics | null): string {
  if (!a) return "用户行为数据暂时读不出来，今天不下结论。";
  const { registered, activated } = a.totals;
  const onlyOneDay = a.activeDays.one;
  const drop = biggestDrop(a.funnel);
  const parts = [`${registered} 人注册，${activated} 人真的动过手`];
  if (onlyOneDay > 0) parts.push(`其中 ${onlyOneDay} 人只来过一天就没再回来`);
  if (drop) parts.push(`最大的坎在「${drop.from.label} → ${drop.to.label}」，掉了 ${drop.lost} 人`);
  return `${parts.join("，")}。`;
}

// 留存的红黄绿。内测早期不用行业基准苛求自己，但也不能把 10% 涂成绿色。
export function retentionTone(value: number | null): BandTone {
  if (value == null) return "muted";
  if (value >= 0.4) return "success";
  if (value >= 0.2) return "warning";
  return "danger";
}

// 「搜完 0 条」的比例：越低越好，高了说明岗位库对用户想搜的东西没货。
export function zeroResultTone(value: number | null): BandTone {
  if (value == null) return "muted";
  if (value <= 0.1) return "success";
  if (value <= 0.25) return "warning";
  return "danger";
}

// 新埋点上线前，对应章节没有历史数据。必须明说「正在积累」，
// 显示 0% 会让人以为「没人搜」而不是「还没开始记」。
export function pendingBlocks(a: UserAnalytics | null): string[] {
  if (!a) return [];
  const pending: string[] = [];
  if (a.search.searches === 0) pending.push("搜索行为");
  if (a.pages.length === 0) pending.push("页面浏览");
  return pending;
}

export const FUNNEL_STEP_LABELS: Record<number, string> = {
  1: "只注册",
  2: "打开过产品",
  3: "设了求职目标",
  4: "看到岗位",
  5: "点开官网",
  6: "标记投递",
};

type RpcClient = {
  rpc: (fn: string, args?: Record<string, unknown>) => PromiseLike<{ data: unknown; error: { message?: string } | null }>;
};

// 读失败一律返回 null（看板据此显示「读取失败」），绝不用 0 冒充。
export async function getUserAnalytics(
  supabase: RpcClient,
  options: { days?: number; includeStaff?: boolean } = {},
): Promise<UserAnalytics | null> {
  try {
    const { data, error } = await supabase.rpc("admin_user_analytics", {
      p_days: options.days ?? 30,
      p_include_staff: options.includeStaff ?? false,
    });
    if (error) {
      console.error("[admin-user-analytics] rpc failed:", error.message || error);
      return null;
    }
    return normalizeUserAnalytics(data);
  } catch (error) {
    console.error("[admin-user-analytics] rpc failed:", error);
    return null;
  }
}

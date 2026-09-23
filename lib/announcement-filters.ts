// 公告制招聘（/programs）筛选的纯函数层：判某条公告是否命中筛选 + 算各维度的可选值与计数。
// 无 DOM、无网络 → 可单测。UI 只负责把状态喂进来、把结果画出去。
//
// ⚠️ 分面计数刻意**排除该维度自身**（选了「北京市」之后，地区那一栏仍按其余条件给出全部省份的计数），
//   否则用户选完一个地区就再也看不到别的地区有多少 —— 换地区要先清空，是最常见的筛选器手感问题。
import type { AnnouncementAudience, AnnouncementCard } from "./announcement-postings";

export type AudienceFilter = "all" | "fresh_grad" | "experienced";
export type SortKey = "newest" | "closing";

export interface AnnouncementFilters {
  region: string | null;
  employerType: string | null;
  audience: AudienceFilter;
  /** 只看 N 天内截止的（null = 不限）。 */
  closingWithinDays: number | null;
  q: string;
}

export const EMPTY_FILTERS: AnnouncementFilters = {
  region: null,
  employerType: null,
  audience: "all",
  closingWithinDays: null,
  q: "",
};

/** 「即将截止」的天数阈值。7 天 = 一周内要动手的，正是用户最需要被提醒的那批。 */
export const CLOSING_SOON_DAYS = 7;

export interface Facet {
  value: string;
  count: number;
}

/** audience 为 both 时同时算进应届与社会；unknown 只在「全部」里出现（不假装知道）。 */
function audienceMatches(a: AnnouncementAudience, want: AudienceFilter): boolean {
  if (want === "all") return true;
  if (a === "both") return true;
  return a === want;
}

/** 距报名截止还有几天；截止日未知返回 null。今天截止 = 0。 */
export function daysUntilDeadline(deadline: string | null, today: string): number | null {
  if (!deadline) return null;
  const ms = Date.parse(`${deadline}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`);
  if (Number.isNaN(ms)) return null;
  return Math.round(ms / 86_400_000);
}

export function matchesFilters(
  p: AnnouncementCard,
  f: AnnouncementFilters,
  today: string,
): boolean {
  if (f.region && p.region !== f.region) return false;
  if (f.employerType && p.employerType !== f.employerType) return false;
  if (!audienceMatches(p.audience, f.audience)) return false;
  if (f.closingWithinDays !== null) {
    const d = daysUntilDeadline(p.deadline, today);
    // 截止日未知的不算「即将截止」—— 不知道就别催人，比猜一个日期诚实。
    if (d === null || d < 0 || d > f.closingWithinDays) return false;
  }
  const q = f.q.trim().toLowerCase();
  if (q) {
    const hay = `${p.title} ${p.region ?? ""} ${p.employerType ?? ""}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

/** 某一维度的可选值 + 计数（算计数时忽略该维度自身的当前选择，见文件头注释）。 */
function facetsFor(
  postings: readonly AnnouncementCard[],
  f: AnnouncementFilters,
  today: string,
  dimension: "region" | "employerType",
): Facet[] {
  const relaxed = { ...f, [dimension]: null } as AnnouncementFilters;
  const counts = new Map<string, number>();
  for (const p of postings) {
    if (!matchesFilters(p, relaxed, today)) continue;
    const v = p[dimension];
    if (!v) continue;
    counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value, "zh-Hans-CN"));
}

export interface AnnouncementFacets {
  regions: Facet[];
  employerTypes: Facet[];
  /** 三档受众各自的条数（同样忽略受众维度自身的选择）。 */
  audience: Record<AudienceFilter, number>;
  closingSoon: number;
}

export function buildFacets(
  postings: readonly AnnouncementCard[],
  f: AnnouncementFilters,
  today: string,
): AnnouncementFacets {
  const withoutAudience = { ...f, audience: "all" as const };
  const audiencePool = postings.filter((p) => matchesFilters(p, withoutAudience, today));
  const withoutClosing = { ...f, closingWithinDays: null };
  const closingPool = postings.filter((p) => matchesFilters(p, withoutClosing, today));
  return {
    regions: facetsFor(postings, f, today, "region"),
    employerTypes: facetsFor(postings, f, today, "employerType"),
    audience: {
      all: audiencePool.length,
      fresh_grad: audiencePool.filter((p) => audienceMatches(p.audience, "fresh_grad")).length,
      experienced: audiencePool.filter((p) => audienceMatches(p.audience, "experienced")).length,
    },
    closingSoon: closingPool.filter((p) => {
      const d = daysUntilDeadline(p.deadline, today);
      return d !== null && d >= 0 && d <= CLOSING_SOON_DAYS;
    }).length,
  };
}

/** 已选条件数（给「清空筛选」按钮上的角标用）。 */
export function activeFilterCount(f: AnnouncementFilters): number {
  return (
    (f.region ? 1 : 0) +
    (f.employerType ? 1 : 0) +
    (f.audience !== "all" ? 1 : 0) +
    (f.closingWithinDays !== null ? 1 : 0) +
    (f.q.trim() ? 1 : 0)
  );
}

export function sortPostings<T extends AnnouncementCard>(
  postings: readonly T[],
  sort: SortKey,
  today: string,
): T[] {
  const out = [...postings];
  if (sort === "closing") {
    // 最快截止在前；截止日未知的一律沉底（不知道就不该插队催人）。
    out.sort((a, b) => {
      const da = daysUntilDeadline(a.deadline, today);
      const db = daysUntilDeadline(b.deadline, today);
      if (da === null && db === null) return 0;
      if (da === null) return 1;
      if (db === null) return -1;
      return da - db;
    });
    return out;
  }
  out.sort((a, b) => (b.publishedAt ?? "").localeCompare(a.publishedAt ?? ""));
  return out;
}

/** 列表一页多少条：服务端首屏只渲染这么多，「加载更多」每次再加这么多。 */
export const ANNOUNCEMENT_PAGE_SIZE = 40;

/** 首屏（无筛选、按最新发布）要画的一切——服务端算好下发，浏览器不必先拿到全量才能画首屏。 */
export interface InitialAnnouncementView {
  /** 首屏那一页（与客户端「无筛选 + 最新发布」时 `visible.slice(0, 页大小)` 逐条相同）。 */
  postings: AnnouncementCard[];
  /** 无筛选时的分面计数（同一个 buildFacets、同一份全量，所以与全量到货后客户端自己算的一致）。 */
  facets: AnnouncementFacets;
  /** 全量条数。 */
  total: number;
  /** 截止日未知的条数（「N 天内截止」的说明文案用）。 */
  unknownDeadlineCount: number;
}

/**
 * ⚠️ 首屏数字与全量到货后的数字必须是**同一套函数**算出来的，否则会出现「首屏写 474 条、一点筛选变 471」。
 * 所以这里不另写计数，只把客户端在无筛选状态下会做的事原样在服务端做一遍（契约测试钉着逐项相等）。
 */
export function initialAnnouncementView(
  postings: readonly AnnouncementCard[],
  today: string,
  pageSize: number = ANNOUNCEMENT_PAGE_SIZE,
): InitialAnnouncementView {
  const visible = sortPostings(
    postings.filter((p) => matchesFilters(p, EMPTY_FILTERS, today)),
    "newest",
    today,
  );
  return {
    postings: visible.slice(0, pageSize),
    facets: buildFacets(postings, EMPTY_FILTERS, today),
    total: visible.length,
    unknownDeadlineCount: postings.filter((p) => !p.deadline).length,
  };
}

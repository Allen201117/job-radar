// 公告制招聘（/programs）筛选的纯函数层：判某条公告是否命中筛选 + 算各维度的可选值与计数。
// 无 DOM、无网络 → 可单测。UI 只负责把状态喂进来、把结果画出去。
//
// ⚠️ 分面计数刻意**排除该维度自身**（选了「北京市」之后，地区那一栏仍按其余条件给出全部省份的计数），
//   否则用户选完一个地区就再也看不到别的地区有多少 —— 换地区要先清空，是最常见的筛选器手感问题。
import { isRollingDeadline, type AnnouncementAudience, type AnnouncementCard } from "./announcement-postings";
import { formatDateLabel } from "./relative-time";

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

/**
 * 地区判不出来的公告在筛选器里的那一项（同时是卡片上的文案）。
 * 没有这一项时，这批公告按地区怎么筛都筛不到（2026-10-10 线上 455 张里 87 张），只能靠不筛地区才看得见。
 */
export const UNKNOWN_REGION = "地区未标注";

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

/** 卡片上那条报名时间提示：文案 + 紧迫度色。 */
export function deadlineChip(
  posting: Pick<AnnouncementCard, "deadline" | "deadlineText">,
  today: string,
): { tone: "rose" | "amber" | "neutral"; text: string } {
  const left = daysUntilDeadline(posting.deadline, today);
  const date = formatDateLabel(posting.deadline);
  // 招满即止：对方登记的结束日只是上限。写成「报名截止 12/31」等于告诉人不急，实际是越早投越好。
  if (isRollingDeadline(posting.deadlineText)) {
    if (left === null) return { tone: "amber", text: "招满即止，尽早报名" };
    if (left <= 0) return { tone: "rose", text: `招满即止 · 最晚今天 ${date}` };
    if (left <= CLOSING_SOON_DAYS) return { tone: "rose", text: `招满即止 · 最晚还剩 ${left} 天（${date}）` };
    return { tone: "amber", text: `招满即止，尽早报名 · 最晚 ${date}` };
  }
  if (left === null) {
    return posting.deadlineText
      ? { tone: "neutral", text: `报名时间：${posting.deadlineText}` }
      : { tone: "neutral", text: "报名时间以公告为准" };
  }
  if (left <= 0) return { tone: "rose", text: `今天 ${date} 截止报名` };
  if (left <= CLOSING_SOON_DAYS) return { tone: "rose", text: `还剩 ${left} 天 · ${date} 截止` };
  return { tone: "amber", text: `报名截止 ${date}` };
}

export function matchesFilters(
  p: AnnouncementCard,
  f: AnnouncementFilters,
  today: string,
): boolean {
  if (f.region && (p.region || UNKNOWN_REGION) !== f.region) return false;
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
  let unknown = 0;
  for (const p of postings) {
    if (!matchesFilters(p, relaxed, today)) continue;
    const v = p[dimension];
    if (!v) {
      unknown += 1;
      continue;
    }
    counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  const facets = [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value, "zh-Hans-CN"));
  // 地区判不出的单列一项、固定排最后（它不是一个地方，不该按数量挤到前排）。
  // 这样各项计数之和 = 当前条件下的公告总数，对得上账。单位类型不加：那一维为空的没有对应的卡片文案。
  if (dimension === "region" && unknown > 0) facets.push({ value: UNKNOWN_REGION, count: unknown });
  return facets;
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
    // 天数每条只算一次：量上千之后，在比较函数里现算是每次筛选多跑几万次日期解析。
    const left = new Map(out.map((p) => [p, daysUntilDeadline(p.deadline, today)]));
    out.sort((a, b) => {
      const da = left.get(a) ?? null;
      const db = left.get(b) ?? null;
      if (da === null && db === null) return 0;
      if (da === null) return 1;
      if (db === null) return -1;
      return da - db;
    });
    return out;
  }
  // 发布日是 ISO 日期串，直接比字符就是比日期；不用 localeCompare（每次比较都要走一遍排序规则，上千条时白费）。
  out.sort((a, b) => {
    const pa = a.publishedAt ?? "";
    const pb = b.publishedAt ?? "";
    return pa === pb ? 0 : pa < pb ? 1 : -1;
  });
  return out;
}

/** 列表一页多少条：服务端首屏只渲染这么多，「加载更多」每次再加这么多。 */
export const ANNOUNCEMENT_PAGE_SIZE = 40;

/** 一次查询：筛选 + 排序 + 取哪一段。 */
export interface AnnouncementQuery {
  filters: AnnouncementFilters;
  sort: SortKey;
  offset: number;
  limit: number;
  /**
   * 翻页游标：上一页最后一张卡的入口链接。给了就从它后面接着取，找不到它（那条刚下架）才退回 offset。
   * 只用 offset 的话，两次请求之间前面有公告下架（每天 0 点过截止日的会下掉一批），后面的就整体前移、被跳过去。
   */
  after: string | null;
}

/**
 * 一次查询的结果。首屏（随页面下发）和之后每次筛选 / 翻页（/api/programs/postings）是**同一个函数**算的、
 * 同一个形状——否则会出现「首屏写 474 条、一点筛选变 471」。
 */
export interface AnnouncementResult {
  /** 当前筛选 + 排序下的第 [offset, offset + limit) 条。 */
  postings: AnnouncementCard[];
  /** 当前筛选下一共几条。 */
  total: number;
  /** 不筛选时一共几条。 */
  allTotal: number;
  /** 当前筛选下的分面计数（各维度忽略自身的选择，见文件头）。 */
  facets: AnnouncementFacets;
  /** 截止日未知的条数（「N 天内截止」的说明文案用）。 */
  unknownDeadlineCount: number;
}

/** 首屏那一份的类型名，留给页面与旧引用。 */
export type InitialAnnouncementView = AnnouncementResult;

export function queryAnnouncements(
  postings: readonly AnnouncementCard[],
  query: AnnouncementQuery,
  today: string,
): AnnouncementResult {
  const visible = sortPostings(
    postings.filter((p) => matchesFilters(p, query.filters, today)),
    query.sort,
    today,
  );
  const cursor = query.after ? visible.findIndex((p) => p.sourceUrl === query.after) : -1;
  const start = cursor >= 0 ? cursor + 1 : query.offset;
  return {
    postings: visible.slice(start, start + query.limit),
    total: visible.length,
    allTotal: postings.length,
    facets: buildFacets(postings, query.filters, today),
    unknownDeadlineCount: postings.filter((p) => !p.deadline).length,
  };
}

/** 首屏：无筛选、最新发布的第一页。 */
export function initialAnnouncementView(
  postings: readonly AnnouncementCard[],
  today: string,
  pageSize: number = ANNOUNCEMENT_PAGE_SIZE,
): AnnouncementResult {
  return queryAnnouncements(
    postings,
    { filters: EMPTY_FILTERS, sort: "newest", offset: 0, limit: pageSize, after: null },
    today,
  );
}

/** 单次最多要多少条：挡住手写 URL 把全量一次拖走。 */
const MAX_QUERY_LIMIT = 200;
/** 搜索词最长多少字：再长也只是白扫一遍。 */
const MAX_QUERY_TEXT = 80;

/** 查询 → 查询串（浏览器发请求用）。默认值不写进去，所以「无筛选 + 最新发布」的串是固定的。 */
export function announcementQueryParams(query: AnnouncementQuery): URLSearchParams {
  const params = new URLSearchParams();
  const { filters } = query;
  if (filters.region) params.set("region", filters.region);
  if (filters.employerType) params.set("type", filters.employerType);
  if (filters.audience !== "all") params.set("audience", filters.audience);
  if (filters.closingWithinDays !== null) params.set("closing", String(filters.closingWithinDays));
  if (filters.q.trim()) params.set("q", filters.q.trim().slice(0, MAX_QUERY_TEXT));
  if (query.sort !== "newest") params.set("sort", query.sort);
  if (query.offset > 0) params.set("offset", String(query.offset));
  if (query.after) params.set("after", query.after);
  params.set("limit", String(query.limit));
  return params;
}

/** 查询串 → 查询（接口用）。任何认不出 / 越界的取值都回到默认，不报错——接口不该因为一个怪参数整个挂掉。 */
export function parseAnnouncementQuery(params: URLSearchParams): AnnouncementQuery {
  const int = (key: string, fallback: number, min: number, max: number): number => {
    const n = Number.parseInt(params.get(key) ?? "", 10);
    return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
  };
  const audience = params.get("audience");
  return {
    filters: {
      region: params.get("region") || null,
      employerType: params.get("type") || null,
      audience: audience === "fresh_grad" || audience === "experienced" ? audience : "all",
      closingWithinDays: params.has("closing") ? int("closing", CLOSING_SOON_DAYS, 0, 365) : null,
      q: (params.get("q") ?? "").slice(0, MAX_QUERY_TEXT),
    },
    sort: params.get("sort") === "closing" ? "closing" : "newest",
    offset: int("offset", 0, 0, 1_000_000),
    limit: int("limit", ANNOUNCEMENT_PAGE_SIZE, 1, MAX_QUERY_LIMIT),
    after: params.get("after") || null,
  };
}

// 公告制招聘：官方招聘公告（announcement_postings）读侧纯函数（无网络、无 DB）。
// 与 apply-programs.ts 并列：apply_programs 是手工核实的边缘条目，本表是自动抓取的官方公告（量大、带时效）。
// 两者在 /programs 的「招聘公告」区统一展示。
//
// ⚠️ fail-safe：service_role 读绕过 RLS，所以「已过报名截止日 / 非 active」的过滤必须在这里再做一遍，
//   不能只依赖 DB —— 与 apply-programs.toApplyProgram 同一道理（宁可读侧再判一次，也不放死链/过期件出去）。

import { todayInDisplayZone } from "./relative-time";

export type AnnouncementAudience = "fresh_grad" | "experienced" | "both" | "unknown";

export interface AnnouncementPosting {
  id: string;
  sourcePortal: string;
  sourceUrl: string;
  title: string;
  region: string | null;
  employerType: string | null;
  audience: AnnouncementAudience;
  publishedAt: string | null;
  deadline: string | null; // ISO date；null = 截止日未知（靠 TTL 治理）
  deadlineText: string | null;
  /** ok = 本页自己收报名；index_page = 官方汇总索引页，报名入口在别处（卡片要标注「需再跳转」）。 */
  verdict: "ok" | "index_page";
  /** 标题未写清具体雇主；公告仍可能可投，点开前需确认。 */
  employerUnclear: boolean;
  /** 列表里有同名公告（如天津人社每周一期的「部分事业单位公开招聘信息」）时，用发布日期区分，否则 null。 */
  sameTitleHint: string | null;
}

/**
 * 交给浏览器的公告形状：卡片与筛选器真正读的字段。`id` / `sourcePortal` 前端一处都不读
 * （卡片 key 用 sourceUrl），每条白带 ~80 字节，400+ 条全量下发时就是几十 KB。
 */
export type AnnouncementCard = Omit<AnnouncementPosting, "id" | "sourcePortal">;

export function toAnnouncementCard(p: AnnouncementPosting): AnnouncementCard {
  // 显式挑字段而不是解构剔除：将来给 AnnouncementPosting 加列，不会悄悄跟着下发到浏览器。
  return {
    sourceUrl: p.sourceUrl,
    title: p.title,
    region: p.region,
    employerType: p.employerType,
    audience: p.audience,
    publishedAt: p.publishedAt,
    deadline: p.deadline,
    deadlineText: p.deadlineText,
    verdict: p.verdict,
    employerUnclear: p.employerUnclear,
    sameTitleHint: p.sameTitleHint,
  };
}

/** 受众徽章文案（应届/社会分面）。unknown 不出徽章。 */
export const AUDIENCE_LABEL: Record<AnnouncementAudience, string> = {
  fresh_grad: "应届",
  experienced: "社会",
  both: "应届/社会",
  unknown: "",
};

function isAudience(v: unknown): v is AnnouncementAudience {
  return v === "fresh_grad" || v === "experienced" || v === "both" || v === "unknown";
}

const UNCLEAR_EMPLOYER = /某(?:国有企业|国企|单位|公司|机构)/;

/** 卡片消费此读侧质量字段，避免把正则散落在 JSX。 */
export function hasUnclearAnnouncementEmployer(title: string): boolean {
  return UNCLEAR_EMPLOYER.test(title || "");
}

const CJK = /[\u4e00-\u9fff]/;
const PLACE_SUFFIX = "市区县州盟旗省";

/** 与国聘的地名安全门同义：不靠裸子串把「五大连池」错识别为「大连」。 */
export function titleMentionsPlace(title: string, name: string): boolean {
  let start = title.indexOf(name);
  while (start >= 0) {
    const before = start > 0 ? title[start - 1] : "";
    const after = start + name.length < title.length ? title[start + name.length] : "";
    const atWordStart = !before || !CJK.test(before);
    const endsCleanly = !after || PLACE_SUFFIX.includes(after) || !CJK.test(after);
    if (atWordStart || endsCleanly) return true;
    start = title.indexOf(name, start + name.length);
  }
  return false;
}

// 只补标题自己明确写出的省/市；识别不到就诚实展示「地区未标注」。
const TITLE_REGIONS: Array<[string, string]> = [
  ["北京市", "北京市"], ["北京", "北京市"], ["天津市", "天津市"], ["天津", "天津市"],
  ["上海市", "上海市"], ["上海", "上海市"], ["重庆市", "重庆市"], ["重庆", "重庆市"],
  ["河北", "河北省"], ["山西", "山西省"], ["辽宁", "辽宁省"], ["吉林", "吉林省"],
  ["黑龙江", "黑龙江省"], ["江苏", "江苏省"], ["浙江", "浙江省"], ["安徽", "安徽省"],
  ["福建", "福建省"], ["江西", "江西省"], ["山东", "山东省"], ["河南", "河南省"],
  ["湖北", "湖北省"], ["湖南", "湖南省"], ["广东", "广东省"], ["海南", "海南省"],
  ["四川", "四川省"], ["贵州", "贵州省"], ["云南", "云南省"], ["陕西", "陕西省"],
  ["甘肃", "甘肃省"], ["青海", "青海省"], ["大连", "大连市"], ["杭州", "杭州市"], ["广州", "广州市"],
  ["深圳", "深圳市"], ["南京", "南京市"], ["武汉", "武汉市"], ["成都", "成都市"],
  ["西安", "西安市"], ["郑州", "郑州市"], ["长沙", "长沙市"],
];

export function inferAnnouncementRegion(title: string): string | null {
  for (const [name, region] of TITLE_REGIONS) {
    if (titleMentionsPlace(title || "", name)) return region;
  }
  return null;
}

/** DB 行 → 展示模型。只放行 active + 未过报名截止日 + 入口是 http(s) 的官方公告。 */
export function toAnnouncementPosting(
  row: Record<string, unknown> | null | undefined,
): AnnouncementPosting | null {
  if (!row) return null;
  const title = String(row.title ?? "").trim();
  const sourceUrl = String(row.source_url ?? row.sourceUrl ?? "").trim();
  const status = String(row.status ?? "active");
  const deadline = (row.deadline as string) ?? null;

  if (!title || !sourceUrl) return null;
  if (status !== "active") return null;
  if (!/^https?:\/\//i.test(sourceUrl)) return null;
  // 过报名截止日的不展示（deadline 为空 = 未知，仍展示，靠 TTL 过期治理下架）。
  if (deadline && deadline < todayInDisplayZone()) return null;

  const audienceRaw = row.audience;
  return {
    id: row.id ? String(row.id) : "",
    sourcePortal: String(row.source_portal ?? row.sourcePortal ?? ""),
    sourceUrl,
    title,
    region: (row.region as string) ?? null,
    employerType: (row.employer_type ?? row.employerType ?? null) as string | null,
    audience: isAudience(audienceRaw) ? audienceRaw : "unknown",
    publishedAt: (row.published_at ?? row.publishedAt ?? null) as string | null,
    deadline,
    deadlineText: (row.deadline_text ?? row.deadlineText ?? null) as string | null,
    verdict: row.verdict === "index_page" ? "index_page" : "ok",
    employerUnclear: hasUnclearAnnouncementEmployer(title),
    sameTitleHint: null,
  };
}

/** 标题归一：去空白与常见标点，只用于「是不是同一份公告」的判定，不改展示文字。 */
function normalizeTitle(title: string): string {
  return (title || "").replace(/[\s·•（）()【】\[\]「」“”"'、，,。.:：;；!！?？-]/g, "").toLowerCase();
}

function isWeixinArticle(url: string): boolean {
  try {
    return new URL(url).hostname.toLowerCase().endsWith("mp.weixin.qq.com");
  } catch {
    return false;
  }
}

function dateHint(publishedAt: string | null): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(publishedAt || "");
  return m ? `${Number(m[2])}月${Number(m[3])}日发布` : null;
}

/**
 * 同一份公告被两路收录（2026-09-23 线上实测：「安徽省水电有限责任公司 2026 年度第二次公开招聘公告」
 * 一条来自公司官网、一条来自国聘给的公众号文章链接，同一天发布）→ 只留一条，官网链接优先。
 * 判定键 = 归一标题 + 发布日：同名但不同日发布的是**不同批次**（天津人社每周一期的
 * 「天津市部分事业单位公开招聘信息」，线上 8 期链接各不相同），不能合并——只给它们标上发布日期区分。
 */
export function toAnnouncementPostings(rows: unknown): AnnouncementPosting[] {
  if (!Array.isArray(rows)) return [];
  const kept = new Map<string, { posting: AnnouncementPosting; index: number }>();
  for (const [index, raw] of rows.entries()) {
    const posting = toAnnouncementPosting(raw as Record<string, unknown>);
    if (!posting) continue;
    const key = `${normalizeTitle(posting.title)}|${posting.publishedAt ?? ""}`;
    const previous = kept.get(key);
    // 同一份公告：官网链接压过公众号转载；都一样时保留先出现的（上游已按发布日倒序）。
    if (!previous || (isWeixinArticle(previous.posting.sourceUrl) && !isWeixinArticle(posting.sourceUrl))) {
      kept.set(key, { posting, index: previous ? previous.index : index });
    }
  }
  const postings = [...kept.values()].sort((a, b) => a.index - b.index).map(({ posting }) => posting);
  const titleCounts = new Map<string, number>();
  for (const p of postings) titleCounts.set(normalizeTitle(p.title), (titleCounts.get(normalizeTitle(p.title)) ?? 0) + 1);
  return postings.map((p) =>
    (titleCounts.get(normalizeTitle(p.title)) ?? 0) > 1 ? { ...p, sameTitleHint: dateHint(p.publishedAt) } : p,
  );
}

// 公告制招聘：官方招聘公告（announcement_postings）读侧纯函数（无网络、无 DB）。
// 与 apply-programs.ts 并列：apply_programs 是手工核实的边缘条目，本表是自动抓取的官方公告（量大、带时效）。
// 两者在 /programs 的「招聘公告」区统一展示。
//
// ⚠️ fail-safe：service_role 读绕过 RLS，所以「已过报名截止日 / 非 active」的过滤必须在这里再做一遍，
//   不能只依赖 DB —— 与 apply-programs.toApplyProgram 同一道理（宁可读侧再判一次，也不放死链/过期件出去）。

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

/** 今天（本地 ISO date）——报名截止日比较用。 */
function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
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
  if (deadline && deadline < todayISO()) return null;

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
  };
}

export function toAnnouncementPostings(rows: unknown): AnnouncementPosting[] {
  if (!Array.isArray(rows)) return [];
  return rows
    .map((r) => toAnnouncementPosting(r as Record<string, unknown>))
    .filter((p): p is AnnouncementPosting => p !== null);
}

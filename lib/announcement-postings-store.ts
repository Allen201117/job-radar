// 公告制招聘：官方招聘公告（announcement_postings）取数层。镜像 apply-programs-store.ts。
// 表由 CI 抓取管道每日刷新，跨实例缓存 10 分钟。
import { requestSafeCache } from "@/lib/request-safe-cache";
import { createServiceClient } from "./supabaseService";
import { PAGE_SIZE } from "./supabase-paginate";
import { toAnnouncementPostings, type AnnouncementPosting } from "./announcement-postings";

const TTL_SECONDS = 600;
// 最多取多少页（每页 PAGE_SIZE = 1000 行，PostgREST 单次的上限）。⚠️ 撞上限是截断：页面不报错，
// 只是最早发布的那批公告看不见了，而这页的价值全在「把还能报的都摆出来」。
//
// 为什么**按页缓存**而不是整表缓存成一条：Next 数据缓存单条约 2MB 上限，超了缓存写不进去（每个请求都重新取
// 一遍，且不报错）。实测每行约 472~545 字节，整表一条撑不过 3,000 多行；而 2026-10-10 国聘改成取全部在报名期的
// 公告后，在展示的从 455 行涨到 1,500 行并会随天数累积。一页一条（约 0.5MB）就没有这个悬崖，
// 上限只剩下面这个页数——它是防失控的保险，不是容量设计；体检项 exp.programs_announcements_near_read_cap 盯着。
const MAX_PAGES = 10;

const COLUMNS =
  "id, source_portal, source_url, title, region, employer_type, audience, " +
  "published_at, deadline, deadline_text, status, verdict";

type Row = Record<string, unknown>;

const getCachedPage = requestSafeCache(
  async (_bucket: number, index: number): Promise<Row[]> => {
    const { data, error } = await createServiceClient()
      .from("announcement_postings")
      .select(COLUMNS)
      .eq("status", "active")
      .order("published_at", { ascending: false, nullsFirst: false })
      // 同一天发布的有上百条：不拿唯一列收尾，翻页边界落在并列块里时会重复 / 漏行。
      .order("id", { ascending: true })
      .range(index * PAGE_SIZE, (index + 1) * PAGE_SIZE - 1);
    // 抛出去而不是返回空：抛错的调用不会被缓存，下一个请求还会再试；返回空会把「没取到」缓存 10 分钟。
    if (error) throw new Error(error.message);
    return (data ?? []) as unknown as Row[];
  },
  ["announcement-postings-page-v1"],
  { revalidate: TTL_SECONDS * 2 },
);

/**
 * ⚠️ 缓存键带时间桶，不只靠后台 revalidate ——
 * 同 apply-programs-store / insight-library-store 已立过的碑：只靠 revalidate 会发「更早时刻的整表快照」
 * 且不报错，而这页价值全在「最新、未过期」，缓存陈旧正打在要害上（过期公告继续展示）。
 * 时间桶让每 10 分钟成为不同缓存条目：窗口内首个请求同步取一次，其余命中。
 */
export async function getAnnouncementPostings(): Promise<AnnouncementPosting[]> {
  const bucket = Math.floor(Date.now() / (TTL_SECONDS * 1000));
  const rows: Row[] = [];
  for (let index = 0; index < MAX_PAGES; index += 1) {
    let page: Row[];
    try {
      page = await getCachedPage(bucket, index);
    } catch (e) {
      // 不吞错：入口页空着比报错更难查。第一页就失败 → 空，页面走空状态；
      // 后面的页失败 → 用已取到的（最新发布的那几页），别让整块公告区凭空消失。
      console.error(
        `[announcement-postings] 第 ${index + 1} 页取数失败（已取到 ${rows.length} 行）:`,
        e instanceof Error ? e.message : e,
      );
      break;
    }
    rows.push(...page);
    if (page.length < PAGE_SIZE) break;
    if (index === MAX_PAGES - 1) {
      console.error(
        `[announcement-postings] 在展示的公告已达读取上限 ${MAX_PAGES * PAGE_SIZE} 行，更早发布的被截掉了`,
      );
    }
  }
  // 各页可能不是同一时刻取的：同一行跨页出现两次时，下面按「标题 + 发布日」合并会把它并掉。
  // service_role 绕过 RLS → 过期/非 active 的过滤也在 toAnnouncementPostings 里再做一遍（fail-safe）。
  return toAnnouncementPostings(rows);
}

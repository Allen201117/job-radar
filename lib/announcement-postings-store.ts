// 公告制招聘：官方招聘公告（announcement_postings）取数层。镜像 apply-programs-store.ts。
// 表由 CI 抓取管道每日刷新，跨实例缓存 10 分钟。
import { requestSafeCache } from "@/lib/request-safe-cache";
import { createServiceClient } from "./supabaseService";
import { fetchAllPages } from "./supabase-paginate";
import { toAnnouncementPostings, type AnnouncementPosting } from "./announcement-postings";

const TTL_SECONDS = 600;
// 一共最多取多少条。⚠️ 撞上限是截断：页面不报错，只是最早发布的那批公告看不见了，
// 而这页的价值全在「把还能报的都摆出来」。
// 2026-10-10：国聘改为按「状态 × 分类」取在报名期的公告后，在展示的从 455 条涨到约 1,500 条，
// 原来的 `.limit(600)` 当天就会截掉一大半（而且 PostgREST 单次最多回 1000 行，光抬数没用，必须分页取）。
// 3000 不是随便定的：实测每条在缓存里约 472~545 字节（后者含缓存序列化的转义），3000 条 ≈ 1.4~1.6MB；
// Next 数据缓存单条约 2MB 上限，超了缓存写不进去（每个请求都重新取一遍，且不报错）。
// 真到 3000 还不够时，该做的是把筛选 / 翻页挪到服务端，不是继续抬这个数。
// 体检项 exp.programs_announcements_near_read_cap 盯着在展示的条数，快到上限会提前报。
const MAX_ROWS = 3000;

const COLUMNS =
  "id, source_portal, source_url, title, region, employer_type, audience, " +
  "published_at, deadline, deadline_text, status, verdict";

type Row = Record<string, unknown>;

const getCached = requestSafeCache(
  async (_bucket: number): Promise<AnnouncementPosting[]> => {
    const supabase = createServiceClient();
    // 已经取到的页另留一份：后面的页出错时先把前面的放出去，别让整块公告区凭空消失。
    const fetched: Row[] = [];
    try {
      await fetchAllPages<Row>(async (from, to) => {
        if (from >= MAX_ROWS) return { data: [], error: null };
        const { data, error } = await supabase
          .from("announcement_postings")
          .select(COLUMNS)
          .eq("status", "active")
          .order("published_at", { ascending: false, nullsFirst: false })
          // 同一天发布的有上百条：不拿唯一列收尾，翻页边界落在并列块里时会重复 / 漏行。
          .order("id", { ascending: true })
          .range(from, Math.min(to, MAX_ROWS - 1));
        const rows = (data ?? []) as unknown as Row[];
        if (!error) fetched.push(...rows);
        return { data: rows, error };
      });
    } catch (e) {
      // 不吞错：入口页空着比报错更难查。第一页就失败 → 空数组，页面走空状态；
      // 后面的页失败 → 用已取到的（最新发布的那几页）。
      console.error(
        `[announcement-postings] 取数失败（已取到 ${fetched.length} 行）:`,
        e instanceof Error ? e.message : e,
      );
    }
    if (fetched.length >= MAX_ROWS) {
      console.error(
        `[announcement-postings] 在展示的公告已达读取上限 ${MAX_ROWS} 条，更早发布的可能被截掉了——该把筛选挪到服务端了`,
      );
    }
    // service_role 绕过 RLS → 过期/非 active 的过滤在 toAnnouncementPostings 里再做一遍（fail-safe）。
    return toAnnouncementPostings(fetched);
  },
  ["announcement-postings-v3"],
  { revalidate: TTL_SECONDS * 2 },
);

/**
 * ⚠️ 缓存键带时间桶，不只靠后台 revalidate ——
 * 同 apply-programs-store / insight-library-store 已立过的碑：只靠 revalidate 会发「更早时刻的整表快照」
 * 且不报错，而这页价值全在「最新、未过期」，缓存陈旧正打在要害上（过期公告继续展示）。
 * 时间桶让每 10 分钟成为不同缓存条目：窗口内首个请求同步取一次，其余命中。
 */
export async function getAnnouncementPostings(): Promise<AnnouncementPosting[]> {
  return getCached(Math.floor(Date.now() / (TTL_SECONDS * 1000)));
}

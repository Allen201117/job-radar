// 公告制招聘：官方招聘公告（announcement_postings）取数层。镜像 apply-programs-store.ts。
// 表由 CI 抓取管道每日刷新，跨实例缓存 10 分钟。
import { unstable_cache } from "next/cache";
import { createServiceClient } from "./supabaseService";
import { toAnnouncementPostings, type AnnouncementPosting } from "./announcement-postings";

const TTL_SECONDS = 600;
// 首屏最多展示的公告数（够多、又不至于把页面拉爆；扩省后再评估分页/分面）。
const MAX_ROWS = 300;

const getCached = unstable_cache(
  async (_bucket: number): Promise<AnnouncementPosting[]> => {
    const supabase = createServiceClient();
    const { data, error } = await supabase
      .from("announcement_postings")
      .select(
        "id, source_portal, source_url, title, region, employer_type, audience, " +
        "published_at, deadline, deadline_text, status, verdict",
      )
      .eq("status", "active")
      .order("published_at", { ascending: false, nullsFirst: false })
      .limit(MAX_ROWS);
    if (error) {
      // 不吞错：入口页空着比报错更难查。记录后返回空，页面走空状态。
      console.error("[announcement-postings] 取数失败:", error.message);
      return [];
    }
    // service_role 绕过 RLS → 过期/非 active 的过滤在 toAnnouncementPostings 里再做一遍（fail-safe）。
    return toAnnouncementPostings(data);
  },
  ["announcement-postings-v2"],
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

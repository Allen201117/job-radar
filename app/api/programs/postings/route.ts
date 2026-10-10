import { NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { getAnnouncementPostings } from "@/lib/announcement-postings-store";
import { toAnnouncementCard } from "@/lib/announcement-postings";
import { parseAnnouncementQuery, queryAnnouncements } from "@/lib/announcement-filters";
import { todayInDisplayZone } from "@/lib/relative-time";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * /programs 招聘公告的筛选 / 排序 / 翻页：按查询串返回**一页** + 当前条件下的分面计数。
 *
 * 沿革：2026-09-23 之前全量整块塞进页面 props（占 HTML 的 252KB / 572KB）→ 挪成挂载后从这里取全量、在浏览器里筛；
 * 2026-10-10 国聘那一路改成取全部在报名期的公告后，在展示的从 455 条涨到 1,500 条，全量那一份已有 570KB 且会继续涨
 * → 筛选挪到这里做，浏览器每次只拿一页。算法就是页面首屏用的那一个 queryAnnouncements，数字不会两套。
 *
 * 取数走与页面**同一个**跨实例缓存（getAnnouncementPostings，10 分钟时间桶），不新增任何未缓存的查询。
 * 与页面同一道门：要登录（页面本身要登录，这里不另开一个匿名出口）。
 */
export async function GET(request: Request) {
  const auth = await requireUser();
  if (auth.error) return auth.error;

  const query = parseAnnouncementQuery(new URL(request.url).searchParams);
  const postings = await getAnnouncementPostings();
  return NextResponse.json(
    { ok: true, ...queryAnnouncements(postings.map(toAnnouncementCard), query, todayInDisplayZone()) },
    // 浏览器不缓存：页面首屏每次都按服务端当前缓存桶现算，这里若让浏览器留一份旧的，
    // 就会出现「首屏是新的、筛一下反而变旧」的数字跳变。服务端那层缓存已经让它足够快。
    { headers: { "Cache-Control": "private, no-store" } },
  );
}

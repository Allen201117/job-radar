import { NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { getAnnouncementPostings } from "@/lib/announcement-postings-store";
import { toAnnouncementCard } from "@/lib/announcement-postings";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * /programs 招聘公告的**全量**列表（筛选、排序、加载更多都在浏览器里对它做）。
 *
 * 存在的意义：页面首屏只下发第一页 + 服务端算好的分面计数；全量 400+ 条原先整块塞进页面 props，
 * 2026-09-23 线上实测占 HTML 的 252KB / 572KB，而用户首屏只看得见 40 张卡。挪到这里在页面挂载后取，
 * 首屏 HTML 与水合都不再背它。
 *
 * 取数走与页面**同一个**跨实例缓存（getAnnouncementPostings，10 分钟时间桶），不新增任何未缓存的查询。
 * 与页面同一道门：要登录（页面本身要登录，这里不另开一个匿名出口）。
 */
export async function GET() {
  const auth = await requireUser();
  if (auth.error) return auth.error;

  const postings = await getAnnouncementPostings();
  return NextResponse.json(
    { ok: true, postings: postings.map(toAnnouncementCard) },
    // 浏览器不缓存：页面首屏每次都按服务端当前缓存桶现算，这里若让浏览器留一份旧的，
    // 就会出现「首屏是新的、全量到货后反而变旧」的数字跳变。服务端那层缓存已经让它足够快。
    { headers: { "Cache-Control": "private, no-store" } },
  );
}

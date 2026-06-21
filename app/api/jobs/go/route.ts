// 点击时校验门：用户从看板点岗位 → 先到这里，服务端按 jd_url 实时探一下死活，再决定跳转或拦下。
// 净效果：对能探的源（wt/hotjob/workday），用户**永远点不到已下线/404 的岗**；其余情况体验与直跳一致、绝不更差。
//   · 已知死岗（库里已 expired/removed）→ 直接「已关闭」提示页，省一次探测。
//   · 24h 内后台刚探活过 → 直接放行（无感）。
//   · 不支持探活的源（北森/Moka 等 SPA）或探测超时/拿不准 → 直接放行（交后台浏览器审计），绝不卡用户。
//   · 实时探到撤岗 → 标记下架 + 「已关闭」提示页；探到在招 → 盖探活戳后放行。
// 安全：探测的目标 URL 取自库里已存的 jd_url（非用户传入）→ 无 SSRF；门仅认证用户可用（从认证看板打开）。
import { NextRequest, NextResponse } from "next/server";
import { hasSessionCookie } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import { jobsStoreEnabled, jobsByIds } from "@/lib/jobs-store/read";
import { markJobExpiredById, touchJobCheckedById } from "@/lib/jobs-store/write";
import liveness from "@/lib/liveness-client";

export const dynamic = "force-dynamic"; // 探活+跳转，绝不缓存

const { checkLiveness, livenessSupported } = liveness as {
  checkLiveness: (
    adapter: string,
    input: { jd_url: string; source_url?: string | null },
  ) => Promise<"alive" | "dead" | "unknown">;
  livenessSupported: (adapter: string) => boolean;
};

const FRESH_MS = 24 * 60 * 60 * 1000; // 后台 24h 内探活过 → 跳过实时探测，直接放行

function toJob(request: NextRequest, jdUrl: string) {
  // jd_url 入库前已过质量门（http 200 + 绝对链接）；防御性兜底：异常则回看板。
  if (typeof jdUrl === "string" && /^https?:\/\//i.test(jdUrl)) {
    return NextResponse.redirect(jdUrl, 302);
  }
  return NextResponse.redirect(new URL("/jobs", request.url), 302);
}

function closedPage(request: NextRequest) {
  const board = new URL("/jobs", request.url).toString();
  const html = `<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>岗位已关闭</title>
<style>html,body{margin:0;height:100%}body{display:flex;align-items:center;justify-content:center;
background:#f3ecdf;color:#1a1714;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
.card{max-width:420px;margin:24px;padding:32px;background:#fbf6ec;border:1px solid #e6dcc8;border-radius:20px;
box-shadow:0 8px 30px rgba(26,23,20,.08);text-align:center}
h1{margin:0 0 8px;font-size:20px}p{margin:0 0 22px;color:#6b6258}
a{display:inline-block;padding:11px 22px;border-radius:999px;background:#1a1714;color:#f7f1e6;
text-decoration:none;font-weight:600}</style></head>
<body><div class="card"><h1>这个岗位刚刚关闭了</h1>
<p>招聘方已撤下这个职位，我们已为你从看板移除，省得你白点。换一个看看吧。</p>
<a href="${board}">返回岗位库</a></div></body></html>`;
  return new NextResponse(html, {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
  });
}

export async function GET(request: NextRequest) {
  const id = request.nextUrl.searchParams.get("id") || "";
  if (!id) return NextResponse.redirect(new URL("/jobs", request.url), 302);
  // 廉价登录态判断（不联网）——门只跳转/标 expired，不碰用户数据，省掉 getUser() ~0.3s 往返。
  const loggedIn = hasSessionCookie(request);

  const useStore = jobsStoreEnabled();
  const service = createServiceClient();

  // 1. 取岗位（跨状态：要能识别已下架的）
  let job: any = null;
  if (useStore) {
    try {
      job = (await jobsByIds([id], false))[0] || null;
    } catch {
      job = null; // 香港库异常 → Supabase 兜底
    }
  }
  if (!job) {
    const { data } = await service
      .from("jobs")
      .select("id, jd_url, status, source_id, enrich_checked_at")
      .eq("id", id)
      .maybeSingle();
    job = data || null;
  }
  if (!job || !job.jd_url) return NextResponse.redirect(new URL("/jobs", request.url), 302);

  // 2. 已知死岗 → 直接关闭提示页（省一次探测）
  if (job.status !== "active") return closedPage(request);

  // 3. 后台最近探活过 → 直接放行（无感）
  const checkedAt = job.enrich_checked_at ? Date.parse(job.enrich_checked_at) : NaN;
  if (Number.isFinite(checkedAt) && Date.now() - checkedAt < FRESH_MS) {
    return toJob(request, job.jd_url);
  }

  // 匿名请求（无会话 cookie）：只跳转、不花一次探测（防滥用 + 省时）；已知死岗/最近探活的上面已处理。
  if (!loggedIn) return toJob(request, job.jd_url);

  // 4. 取源 adapter + source_url（sources 永远在 Supabase）
  const { data: src } = await service
    .from("sources")
    .select("adapter_name, source_url")
    .eq("id", job.source_id)
    .maybeSingle();
  const adapter = (src?.adapter_name as string) || "";
  if (!src || !livenessSupported(adapter)) {
    return toJob(request, job.jd_url); // SPA/不支持探活 → 放行，交后台浏览器审计
  }

  // 5. 实时探活（封顶 3s，拿不准放行）
  const verdict = await checkLiveness(adapter, { jd_url: job.jd_url, source_url: src.source_url });

  if (verdict === "dead") {
    try {
      if (useStore) await markJobExpiredById(id);
      else
        await service
          .from("jobs")
          .update({ status: "expired", enrich_checked_at: new Date().toISOString() })
          .eq("id", id)
          .eq("status", "active");
    } catch {
      // 写库失败不影响给用户正确提示
    }
    return closedPage(request);
  }
  if (verdict === "alive") {
    try {
      if (useStore) await touchJobCheckedById(id);
      else await service.from("jobs").update({ enrich_checked_at: new Date().toISOString() }).eq("id", id);
    } catch {
      // 盖探活戳失败无所谓，后台会兜
    }
  }
  return toJob(request, job.jd_url); // alive / unknown 都放行
}

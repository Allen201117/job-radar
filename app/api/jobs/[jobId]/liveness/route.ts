// 单岗点击核验（01 spec §4.4）：用户点「打开官网」时前端 race 它（封顶 2.5s）。**默认放行、判死只提示**。
// 与批量展示核验（/api/jobs/liveness-check）区别：单岗、返回三态 alive|dead|unknown，供点击用。
// 副作用：判死 → markJobExpiredById(+confirmed_closed_at)；判活 → touchJobCheckedById；
//   顺带打 job_liveness_at_click 事件（仅可探源 best-effort）。失败/超时/不可探源 → unknown（绝不因探不动判死）。
import { NextRequest, NextResponse } from "next/server";
import { hasSessionCookie } from "@/lib/apiAuth";
import { getRequestUser } from "@/lib/auth";
import { createServiceClient } from "@/lib/supabaseService";
import { jobsStoreEnabled, jobsByIds } from "@/lib/jobs-store/read";
import { markJobExpiredById, touchJobCheckedById } from "@/lib/jobs-store/write";
import { trackServerEvent } from "@/lib/track";
import { isUuid } from "@/lib/opportunities/action-input";
import liveness from "@/lib/liveness-client";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const { checkLiveness, livenessSupported } = liveness as {
  checkLiveness: (
    adapter: string,
    input: { jd_url: string; source_url?: string | null },
  ) => Promise<"alive" | "dead" | "unknown">;
  livenessSupported: (adapter: string) => boolean;
};

const CAP_MS = 2500; // 封顶 2.5s：探不动就放行，绝不卡点击路径（历史教训：点击门同步长等已废）。

function raceTimeout<T>(p: Promise<T>, ms: number, fallback: T): Promise<T> {
  return Promise.race([p, new Promise<T>((resolve) => setTimeout(() => resolve(fallback), ms))]);
}

export async function POST(request: NextRequest, { params }: { params: { jobId: string } }) {
  const jobId = params.jobId;
  if (!isUuid(jobId)) return NextResponse.json({ ok: true, result: "unknown" });
  // 廉价登录态（不联网）；匿名不探不写。
  if (!hasSessionCookie(request)) return NextResponse.json({ ok: true, result: "unknown" });

  const useStore = jobsStoreEnabled();
  const service = createServiceClient();

  // 取该岗（只关心 active）
  let job: any = null;
  if (useStore) {
    try {
      const rows = await jobsByIds([jobId], true);
      job = (rows || [])[0] || null;
    } catch {
      job = null;
    }
  }
  if (!job) {
    const res = await service
      .from("jobs")
      .select("id, jd_url, source_id, status")
      .eq("id", jobId)
      .maybeSingle();
    job = res.data || null;
  }
  if (!job || job.status !== "active" || !job.jd_url) {
    return NextResponse.json({ ok: true, result: "unknown" });
  }

  // 源映射（adapter + source_url 在 Supabase）
  const { data: src } = await service
    .from("sources")
    .select("adapter_name, source_url")
    .eq("id", job.source_id)
    .maybeSingle();
  const adapter = src?.adapter_name || "";
  if (!src || !livenessSupported(adapter)) {
    return NextResponse.json({ ok: true, result: "unknown" });
  }

  // 探活（封顶 2.5s）：探不动/超时 → unknown，绝不判死。
  const result = await raceTimeout(
    checkLiveness(adapter, { jd_url: job.jd_url, source_url: src.source_url }),
    CAP_MS,
    "unknown" as const,
  );

  if (result === "dead") {
    try {
      if (useStore) await markJobExpiredById(jobId);
      else
        await service
          .from("jobs")
          .update({ status: "expired", enrich_checked_at: new Date().toISOString() })
          .eq("id", jobId)
          .eq("status", "active");
    } catch {
      /* 写库失败：后台 sweep 兜底 */
    }
  } else if (result === "alive") {
    try {
      if (useStore) await touchJobCheckedById(jobId);
      else await service.from("jobs").update({ enrich_checked_at: new Date().toISOString() }).eq("id", jobId);
    } catch {
      /* 盖戳失败无所谓 */
    }
  }

  // 顺带打 job_liveness_at_click（点击有效率指标分母，仅可探源 best-effort）。
  try {
    const user = await getRequestUser();
    if (user) await trackServerEvent(service as any, user.id, "job_liveness_at_click", { job_id: jobId, adapter, result });
  } catch {
    /* 埋点失败不影响放行 */
  }

  return NextResponse.json({ ok: true, result });
}

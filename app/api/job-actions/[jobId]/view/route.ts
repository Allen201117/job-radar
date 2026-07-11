// 浏览埋点（§8.1）：upsert viewed，不改主动作。最佳努力——打开官网不被它失败阻塞（客户端 fire-and-forget）。
import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { isUuid } from "@/lib/opportunities/action-input";

export const runtime = "nodejs";

export async function POST(_request: NextRequest, { params }: { params: Promise<{ jobId: string }> }) {
  const auth = await requireUser();
  if (auth.error) return auth.error;

  const { jobId } = await params;
  if (!isUuid(jobId)) {
    return NextResponse.json({ ok: false, error: "invalid_job_id" }, { status: 400 });
  }

  const { error } = await auth.supabase
    .from("job_actions")
    .upsert(
      { user_id: auth.user.id, job_id: jobId, action: "viewed" },
      { onConflict: "user_id,job_id,action" },
    );
  if (error) console.warn("[job-actions/view] upsert failed:", error.message);

  return new NextResponse(null, { status: 204 });
}

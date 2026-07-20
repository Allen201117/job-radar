import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import { sanitizePayload } from "@/lib/track";

export const runtime = "nodejs";

const VALID_REASONS = new Set(["not_campus", "dead_link", "closed"]);

// 校招专区用户纠错入口：登录用户对某个岗位提反馈（这不是校招/链接失效/已结束）。
// 复用 events 表落库（event=campus_job_dispute），不新建表；service-role 写，绕 RLS。
// 后续人工/运营看板从 events 表按 event 分组读出这批记录做复核队列，本期不做展示。
export async function POST(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;
  const { user } = auth;

  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }

  const jobId = String(body?.job_id || "").trim();
  const reason = String(body?.reason || "").trim();
  if (!jobId) {
    return NextResponse.json({ ok: false, error: "missing_job_id" }, { status: 400 });
  }
  if (!VALID_REASONS.has(reason)) {
    return NextResponse.json({ ok: false, error: "invalid_reason" }, { status: 400 });
  }

  const service = createServiceClient();
  const { error } = await service.from("events").insert({
    user_id: user.id,
    event: "campus_job_dispute",
    payload: sanitizePayload({ job_id: jobId, reason }),
  });
  if (error) {
    console.error("[campus-zone] 纠错写入失败", error.message);
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true });
}

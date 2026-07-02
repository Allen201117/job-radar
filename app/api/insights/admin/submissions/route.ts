import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";

export const runtime = "nodejs";

const STATUSES = ["pending", "approved", "rejected", "retired"] as const;
const REVIEW_STATUSES = ["approved", "rejected", "retired"] as const;

function allowedStatus(value: unknown): value is (typeof STATUSES)[number] {
  return STATUSES.includes(value as (typeof STATUSES)[number]);
}

function allowedReviewStatus(value: unknown): value is (typeof REVIEW_STATUSES)[number] {
  return REVIEW_STATUSES.includes(value as (typeof REVIEW_STATUSES)[number]);
}

export async function GET(request: NextRequest) {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;

  const requested = request.nextUrl.searchParams.get("status") || "pending";
  const status = allowedStatus(requested) ? requested : "pending";
  const service = createServiceClient();
  const { data, error } = await service
    .from("insight_submissions")
    .select(
      "id,company,company_id,user_id,dimension,topic,rating,content,payload,status,moderation,employment_verified,created_at,updated_at",
    )
    .eq("status", status)
    .order("created_at", { ascending: false });

  if (error) {
    console.error("[insights-admin-submissions] 读取失败", error.message);
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true, submissions: data || [] });
}

export async function PATCH(request: NextRequest) {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }

  const id = String(body.id || "").trim();
  if (!id || !allowedReviewStatus(body.status)) {
    return NextResponse.json({ ok: false, error: "invalid_input" }, { status: 400 });
  }

  const moderation = {
    reviewer_id: guard.user.id,
    reason: body.reason ? String(body.reason).trim().slice(0, 500) : null,
    reviewed_at: new Date().toISOString(),
  };
  const service = createServiceClient();
  const { data, error } = await service
    .from("insight_submissions")
    .update({
      status: body.status,
      moderation,
      updated_at: new Date().toISOString(),
    })
    .eq("id", id)
    .select("id,status")
    .single();

  if (error) {
    console.error("[insights-admin-submissions] 更新失败", error.message);
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true, submission: data });
}

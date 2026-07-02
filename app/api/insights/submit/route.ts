import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { findCompanyProfile } from "@/lib/insight-match";
import {
  validateSubmission,
  type NormalizedInsightSubmission,
} from "@/lib/insight-submission";
import { createServiceClient } from "@/lib/supabaseService";
import type { CompanyProfile } from "@/lib/types";

export const runtime = "nodejs";

function buildInsertRow(
  submission: NormalizedInsightSubmission,
  userId: string,
  profile: CompanyProfile | null,
) {
  return {
    company: profile?.company || submission.company,
    company_id: profile?.id || null,
    user_id: userId,
    dimension: submission.dimension,
    topic: submission.topic,
    rating: submission.rating,
    content: submission.content,
    payload: submission.payload,
    status: "pending",
  };
}

export async function POST(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }

  const validation = validateSubmission(body);
  if (!validation.ok) {
    return NextResponse.json(
      { ok: false, error: validation.error },
      { status: 422 },
    );
  }

  const service = createServiceClient();
  let profile: CompanyProfile | null = null;
  const { data: profiles, error: profileError } = await service
    .from("company_profiles")
    .select("*");
  if (profileError) {
    console.error("[insights-submit] 读取 company_profiles 失败", profileError.message);
  } else {
    profile = findCompanyProfile((profiles || []) as CompanyProfile[], validation.value.company);
  }

  const { data: inserted, error: insertError } = await service
    .from("insight_submissions")
    .insert(buildInsertRow(validation.value, auth.user.id, profile))
    .select("id,status")
    .single();

  if (insertError) {
    console.error("[insights-submit] 插入 insight_submissions 失败", insertError.message);
    return NextResponse.json({ ok: false, error: insertError.message }, { status: 500 });
  }

  return NextResponse.json({
    ok: true,
    submission_id: inserted?.id,
    status: inserted?.status || "pending",
    contributed: true,
  });
}

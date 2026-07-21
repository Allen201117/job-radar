import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import { validateCycleInput } from "@/lib/recruitment-cycle-validate";

export const runtime = "nodejs";

const VERIFY_STATUSES = ["draft", "verified", "rejected"];

export async function GET() {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;
  const service = createServiceClient();
  const [{ data: companies, error: cErr }, { data: cycles, error: yErr }] = await Promise.all([
    service.from("company_profiles").select("id, company, display_name").order("company"),
    service
      .from("recruitment_cycle_observations")
      .select("*, company_profiles!inner(company, display_name)")
      .order("updated_at", { ascending: false }),
  ]);
  if (cErr || yErr) {
    const message = cErr?.message || yErr?.message || "load_failed";
    console.error("[cycles-admin] 读取失败", message);
    return NextResponse.json({ ok: false, error: message }, { status: 500 });
  }
  return NextResponse.json({ ok: true, companies: companies || [], cycles: cycles || [] });
}

export async function POST(request: NextRequest) {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;
  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }
  const v = validateCycleInput(body);
  if (!v.ok) return NextResponse.json({ ok: false, error: v.error }, { status: 422 });

  const verifyStatus = VERIFY_STATUSES.includes(body.verify_status) ? body.verify_status : "draft";
  const service = createServiceClient();
  const { data, error } = await service
    .from("recruitment_cycle_observations")
    .insert({
      ...v.fields,
      verify_status: verifyStatus,
      valid_until: body.valid_until || null,
      superseded_by: body.superseded_by || null,
      created_by: guard.user?.email || "admin",
    })
    .select("id")
    .single();
  if (error) {
    console.error("[cycles-admin] 写入失败", error.message);
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true, id: data.id });
}

// 只改可变字段（immutable：事实字段一律不接受更新）
export async function PATCH(request: NextRequest) {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;
  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }
  const id = String(body.id || "").trim();
  if (!id) return NextResponse.json({ ok: false, error: "missing_id" }, { status: 400 });
  const patch: Record<string, any> = { updated_at: new Date().toISOString() };
  if (body.verify_status !== undefined) {
    if (!VERIFY_STATUSES.includes(body.verify_status))
      return NextResponse.json({ ok: false, error: "invalid_verify_status" }, { status: 400 });
    patch.verify_status = body.verify_status;
  }
  if (body.valid_until !== undefined) patch.valid_until = body.valid_until || null;
  if (body.superseded_by !== undefined) patch.superseded_by = body.superseded_by || null;

  const service = createServiceClient();
  const { error } = await service
    .from("recruitment_cycle_observations")
    .update(patch)
    .eq("id", id);
  if (error) {
    console.error("[cycles-admin] 更新失败", error.message);
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true, id });
}

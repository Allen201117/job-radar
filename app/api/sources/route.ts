import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { createServiceClient } from "@/lib/supabaseService";
import { validateSourceInput } from "@/lib/source-adapters";

export const runtime = "nodejs";

// admin 网页添加招聘源。002_rls 只给了 sources 的 admin UPDATE 策略、没有 INSERT，
// 浏览器 anon 直接 insert 会被 RLS 拦，所以必须走 service-role 写入。
export async function POST(request: NextRequest) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }
  const { data: profileRow } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", user.id)
    .maybeSingle();
  if (profileRow?.role !== "admin") {
    return NextResponse.json({ ok: false, error: "forbidden" }, { status: 403 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }

  const result = validateSourceInput(body as Record<string, unknown>);
  if (!result.ok || !result.value) {
    return NextResponse.json(
      { ok: false, error: "validation_failed", errors: result.errors },
      { status: 400 },
    );
  }

  const service = createServiceClient();
  const { data: row, error } = await service
    .from("sources")
    .insert(result.value)
    .select("*")
    .single();
  if (error) {
    console.error("[sources] 插入 sources 失败", error.message);
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }

  // 同步给该公司建 / 标记画像占位 → 入职业洞察 T2 富化队列（insight_checked_at=null，CI worker 会查 Wikidata 回填）。
  // best-effort：失败不阻断加源（洞察是增益层，不能拖累核心加源流程）。
  const companyName = (result.value as { company?: string }).company;
  if (companyName) {
    const { error: profErr } = await service
      .from("company_profiles")
      .upsert({ company: companyName, insight_checked_at: null }, { onConflict: "company" });
    if (profErr) console.error("[sources] 洞察入队失败(忽略)", profErr.message);
  }

  return NextResponse.json({ ok: true, source: row });
}

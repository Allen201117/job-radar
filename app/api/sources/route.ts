import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import { validateSourceInput } from "@/lib/source-adapters";
import { ensureCompanyProfile } from "@/lib/insight-profile-store";

export const runtime = "nodejs";

// admin 网页添加招聘源。002_rls 只给了 sources 的 admin UPDATE 策略、没有 INSERT，
// 浏览器 anon 直接 insert 会被 RLS 拦，所以必须走 service-role 写入。
export async function POST(request: NextRequest) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

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
  // 这家公司已有画像（新源名是它的别名）就只重新排队，不另建一个画像——见 lib/insight-profile-store。
  if (companyName) {
    try {
      await ensureCompanyProfile(service, companyName, { insight_checked_at: null });
    } catch (e) {
      console.error("[sources] 洞察入队失败(忽略)", (e as Error).message);
    }
  }

  return NextResponse.json({ ok: true, source: row });
}

// 主动作写入（§8.1）：值得投/不适合/已投递/取消。停止 JobCard 直接操作 Supabase。
// 岗位存在性用权威 jobs 库（香港，gated）校验；snapshot 由服务端从权威行生成（忽略客户端同名字段）。
// 写入走 set_job_primary_action RPC（auth.uid()，单事务：删旧主动作→视情况插新；viewed 不动）。
import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { jobsByIds, jobsStoreEnabled } from "@/lib/jobs-store/read";
import { parseActionInput } from "@/lib/opportunities/action-input";
import { isMissingFunction } from "@/lib/opportunities/schema-errors";

export const runtime = "nodejs";

type ServerSupabase = NonNullable<Awaited<ReturnType<typeof requireUser>>["supabase"]>;

// 权威岗位行（用于校验存在 + 生成 snapshot）：配了香港库走它，否则本地回退 Supabase。
async function fetchJobById(supabase: ServerSupabase, jobId: string) {
  if (jobsStoreEnabled()) {
    const rows = await jobsByIds([jobId], false);
    return rows[0] || null;
  }
  const { data } = await supabase
    .from("jobs")
    .select("id, company, title, location, jd_url")
    .eq("id", jobId)
    .maybeSingle();
  return data || null;
}

export async function PUT(request: NextRequest, { params }: { params: { jobId: string } }) {
  const auth = await requireUser();
  if (auth.error) return auth.error;

  const jobId = params.jobId;
  const body = await request.json().catch(() => ({}));
  const parsed = parseActionInput(jobId, body);
  if (!parsed.ok) {
    return NextResponse.json({ ok: false, error: parsed.error }, { status: 400 });
  }
  const { action, reasonCode, reasonText } = parsed.value;

  // 非空动作：岗位必须存在（权威库）；snapshot 只取白名单字段、服务端生成
  let snapshot: Record<string, unknown> = {};
  if (action !== null) {
    const job = await fetchJobById(auth.supabase, jobId);
    if (!job) {
      return NextResponse.json({ ok: false, error: "job_not_found" }, { status: 404 });
    }
    snapshot = {
      company: job.company ?? null,
      title: job.title ?? null,
      location: job.location ?? null,
      jd_url: job.jd_url ?? null,
    };
  }

  const { data, error } = await auth.supabase.rpc("set_job_primary_action", {
    p_job_id: jobId,
    p_action: action,
    p_reason_code: reasonCode,
    p_reason_text: reasonText,
    p_job_snapshot: snapshot,
  });
  if (error) {
    // 迁移 162 未应用（RPC/列不存在）→ 稳定 schema 码（§9），前端可诚实提示「功能暂不可用」
    const schemaMissing = isMissingFunction(error);
    return NextResponse.json(
      { ok: false, error: schemaMissing ? "action_schema_unavailable" : error.message },
      { status: schemaMissing ? 503 : 500 },
    );
  }
  return NextResponse.json({ ok: true, action: (data as string | null) ?? null });
}

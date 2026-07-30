import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { jobsByIds, jobsStoreEnabled } from "@/lib/jobs-store/read";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** 单次最多取多少岗：校招专区一次展开一家公司，够用；同时挡住构造大批 id 的滥用。 */
const MAX_IDS = 200;

/**
 * 按 id 批量取完整岗位行（按需加载用）。
 *
 * 存在的意义：校招专区原先把 30 家必投公司的**全部**校招岗（含 JD 正文）一次性序列化进页面
 * props，实测单页 16.3 MB，而岗位卡默认折叠、用户根本没看。现在页面只下发筛选/计数所需的
 * 轻量字段，用户展开某家公司时才用本接口把那批岗位的完整行取回来渲染 JobCard。
 */
export async function POST(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }
  const raw = (body as { ids?: unknown })?.ids;
  if (!Array.isArray(raw)) {
    return NextResponse.json({ ok: false, error: "ids_required" }, { status: 400 });
  }
  // 只收 uuid 形态的字符串：id 直接进 `= any($1::uuid[])`，非法值会让整条查询报错。
  const ids = Array.from(
    new Set(
      raw
        .filter((v): v is string => typeof v === "string")
        .map((v) => v.trim())
        .filter((v) =>
          /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v),
        ),
    ),
  ).slice(0, MAX_IDS);
  if (ids.length === 0) return NextResponse.json({ ok: true, jobs: [] });

  if (!jobsStoreEnabled()) {
    // 未配 JOBS_DATABASE_URL（本地 / 回滚）：不静默返空，让调用方知道这条路没通。
    return NextResponse.json({ ok: false, error: "jobs_store_disabled" }, { status: 503 });
  }

  try {
    const jobs = await jobsByIds(ids);
    return NextResponse.json({ ok: true, jobs });
  } catch (e: any) {
    console.error("[api/jobs/by-ids] 取岗失败:", e?.message);
    return NextResponse.json(
      { ok: false, error: e?.message || "fetch_failed" },
      { status: 500 },
    );
  }
}

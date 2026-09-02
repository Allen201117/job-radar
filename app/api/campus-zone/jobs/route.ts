import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { getUserCampusScope } from "@/lib/campus-user-industries";
import { getCampusCompanyJobs, jobsStoreEnabled } from "@/lib/jobs-store/read";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** 单次最多返回多少岗：校招专区一次展开一家公司，够用；同时挡住把整家大厂拉空。 */
const MAX_JOBS = 200;

/**
 * 校招专区「展开某家公司」按需取完整岗位行。
 *
 * 存在的意义：页面本身只下发聚合分面（(城市,学历,职能,届别) → 计数），一条岗位记录都不发——
 * 逐条下发实测单页 2.09 MB / 16,494 条，而岗位卡默认折叠、用户根本没看。
 *
 * 为什么按「公司 + 模式」取而不是按 id 取（取代原先的 /api/jobs/by-ids 调法）：
 *   1. 按 id 取就必须先把全部 16,494 个 id 下发到浏览器，光 uuid 就 0.59 MB，白白抵消收益；
 *   2. 原调法把 campus 与 intern 的 id 拼在一起再截前 200，大厂的实习桶会被校招桶挤没 ——
 *      实习模式下展开一家校招岗超过 200 的公司，展开区必然空白。按模式取从根上没有这个问题。
 *
 * 公司范围**服务端自己按登录用户的行业解析**，不信客户端传来的公司名，避免被拿来遍历全库。
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
  const pattern = String((body as { pattern?: unknown })?.pattern ?? "").trim();
  const mode = String((body as { mode?: unknown })?.mode ?? "").trim();
  if (!pattern) return NextResponse.json({ ok: false, error: "pattern_required" }, { status: 400 });
  if (mode !== "campus" && mode !== "intern") {
    return NextResponse.json({ ok: false, error: "invalid_mode" }, { status: 400 });
  }

  if (!jobsStoreEnabled()) {
    // 未配 JOBS_DATABASE_URL（本地 / 回滚）：不静默返空，让调用方知道这条路没通。
    return NextResponse.json({ ok: false, error: "jobs_store_disabled" }, { status: 503 });
  }

  const { companies } = await getUserCampusScope(auth.supabase, auth.user.id);
  if (!companies.some((c) => c.pattern === pattern)) {
    // 不在该用户行业的必投清单里 → 这不是他这块看板上的公司。
    return NextResponse.json({ ok: false, error: "company_out_of_scope" }, { status: 403 });
  }

  try {
    // 是否截断由调用方拿卡面总数（来自聚合分面，权威）与 jobs.length 比对得出——
    // 这里不再回一个 total：为了拿它就得把全公司的岗位正文都取回来数一遍，正是刚优化掉的那笔开销。
    const { jobs } = await getCampusCompanyJobs(companies, pattern, mode, MAX_JOBS);
    return NextResponse.json({ ok: true, jobs });
  } catch (e: any) {
    console.error("[api/campus-zone/jobs] 取岗失败:", e?.message);
    return NextResponse.json({ ok: false, error: e?.message || "fetch_failed" }, { status: 500 });
  }
}

import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { getUserCampusScope } from "@/lib/campus-user-industries";
import { getCampusCompanyJobs, jobsStoreEnabled } from "@/lib/jobs-store/read";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** 单页返回多少岗：抽屉「加载更多」按页翻，直到看完当前筛选下的**全部**岗位（Phase B，2026-09-15）。 */
const PAGE_SIZE = 200;

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
  const b = (body ?? {}) as Record<string, unknown>;
  const pattern = String(b.pattern ?? "").trim();
  const mode = String(b.mode ?? "").trim();
  if (!pattern) return NextResponse.json({ ok: false, error: "pattern_required" }, { status: 400 });
  if (mode !== "campus" && mode !== "intern") {
    return NextResponse.json({ ok: false, error: "invalid_mode" }, { status: 400 });
  }
  // 分页 + 服务端筛选（Phase B）：把当前筛选下推到库里，「加载更多」按页翻完全部符合条件的岗位。
  const offset = Math.max(0, Math.floor(Number(b.offset) || 0));
  const rawFilters = (b.filters ?? {}) as Record<string, unknown>;
  const gradClassNum = Number(rawFilters.gradClass);
  const filters = {
    city: String(rawFilters.city ?? "").trim(),
    education: String(rawFilters.education ?? "").trim(),
    jobFunction: String(rawFilters.jobFunction ?? "").trim(),
    gradClass: Number.isFinite(gradClassNum) && rawFilters.gradClass !== null && rawFilters.gradClass !== ""
      ? gradClassNum
      : null,
  };

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
    // total 现在是**精确**的：职能/招聘类型都物化成列后，全部候选靠轻字段就能筛出来数清（Phase A/B），
    // 不必再把全公司正文取回来数一遍。hasMore 据此判，供抽屉「加载更多」翻页。
    const { jobs, total } = await getCampusCompanyJobs(companies, pattern, mode, {
      filters,
      offset,
      limit: PAGE_SIZE,
    });
    return NextResponse.json({ ok: true, jobs, total, offset, hasMore: offset + jobs.length < total });
  } catch (e: any) {
    console.error("[api/campus-zone/jobs] 取岗失败:", e?.message);
    return NextResponse.json({ ok: false, error: e?.message || "fetch_failed" }, { status: 500 });
  }
}

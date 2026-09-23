// ============================================================
// 洞察库读模型 GET /api/insights/library
//
// 形状（前后端契约，改这里必须同步
//   docs/superpowers/specs/2026-09-03-insight-library-module-taskcard.md §2.2）：
//   · 列表：{ ok, total, page, page_size, subjects: LibrarySubject[], facets, index_built_at }
//   · 展开：?subject=<id> → { ok, subject: LibrarySubject, items: InsightItemView[] }
//
// ⚠️ 首屏不逐条下发洞察：列表返回的是**主体卡**（至多 6 条头条指标）+ 聚合分面。
//    某个主体的全部条目在展开时才取。/campus 曾因逐条下发 16,494 条岗位把首屏做到
//    10.1s / 2.09MB，这里从一开始就不许走那条路。
// ============================================================
import { NextRequest, NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import {
  attachCardContents,
  getInsightLibraryIndex,
  getSubjectItems,
  type IndexBuildTiming,
} from "@/lib/insight-library-store";
import {
  computeFacets,
  filterSubjects,
  parseLibraryFilters,
  sortSubjects,
  trimSubjectForCard,
  LIBRARY_PAGE_SIZE,
} from "@/lib/insight-library";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// 与 app/insights/page.tsx 同理：索引过期后的后台重建挂在 waitUntil 上，给它留足时间。
export const maxDuration = 60;

export async function GET(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;

  const params = request.nextUrl.searchParams;

  let index;
  const requestStartedAt = Date.now();
  const tIndex = performance.now();
  try {
    index = await getInsightLibraryIndex();
  } catch (error: any) {
    console.error("[insights/library] 建索引失败", error?.message || error);
    return NextResponse.json({ ok: false, error: "index_failed" }, { status: 500 });
  }

  // 展开某个主体：卡面之外的全部条目在这里才取。
  const subjectId = params.get("subject");
  if (subjectId) {
    const hit = index.subjects.find((s) => s.id === subjectId);
    if (!hit) return NextResponse.json({ ok: false, error: "not_found" }, { status: 404 });
    try {
      const items = await getSubjectItems(hit);
      return NextResponse.json({ ok: true, subject: hit, items });
    } catch (error: any) {
      console.error("[insights/library] 取主体条目失败", error?.message || error);
      return NextResponse.json({ ok: false, error: "items_failed" }, { status: 500 });
    }
  }

  const filters = parseLibraryFilters(params);
  const page = Math.max(1, Number(params.get("page") || 1) || 1);
  const matched = filterSubjects(index.subjects, filters);
  const sorted = sortSubjects(matched, filters.sort);
  const start = (page - 1) * LIBRARY_PAGE_SIZE;
  const indexMs = performance.now() - tIndex;

  // 正文只为这一页现取（见 lib/insight-library-store.attachCardContents）。
  const tCards = performance.now();
  const pageSubjects = await attachCardContents(
    sorted.slice(start, start + LIBRARY_PAGE_SIZE).map(trimSubjectForCard),
    3,
    filters.metric,
  );

  const cardsMs = performance.now() - tCards;

  const response = NextResponse.json({
    ok: true,
    total: sorted.length,
    page,
    page_size: LIBRARY_PAGE_SIZE,
    subjects: pageSubjects,
    facets: computeFacets(index.subjects, filters),
    index_built_at: index.builtAt,
  });
  // 分段耗时走标准 Server-Timing 头：curl / DevTools 直接可读，不改响应体契约。
  response.headers.set(
    "Server-Timing",
    `index;dur=${Math.round(indexMs)}, cards;dur=${Math.round(cardsMs)}` +
      // 只有本次请求亲自建了索引（缓存没命中）才带建索引分段。
      (index.buildTiming && Date.parse(index.builtAt) >= requestStartedAt
        ? `, build;dur=${index.buildTiming.total_ms};desc="${serverTimingDesc(index.buildTiming)}"`
        : ""),
  );
  return response;
}

/** 建索引分段压成一行 ASCII（Server-Timing 的 desc 只能放 ASCII）。 */
function serverTimingDesc(t: IndexBuildTiming) {
  return (
    `subjects ${t.subjects_ms}ms/${t.subject_rows}r items ${t.items_ms}ms/${t.item_rows}r/${t.items_kb}KB ` +
    `profiles ${t.profiles_ms}ms/${t.profile_rows}r build ${t.build_ms}ms index ${t.index_kb}KB`
  );
}

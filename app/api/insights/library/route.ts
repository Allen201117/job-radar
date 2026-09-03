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

export async function GET(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;

  const params = request.nextUrl.searchParams;

  let index;
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
      const items = await getSubjectItems(subjectId);
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

  // 正文只为这一页现取（见 lib/insight-library-store.attachCardContents）。
  const pageSubjects = await attachCardContents(
    sorted.slice(start, start + LIBRARY_PAGE_SIZE).map(trimSubjectForCard),
  );

  return NextResponse.json({
    ok: true,
    total: sorted.length,
    page,
    page_size: LIBRARY_PAGE_SIZE,
    subjects: pageSubjects,
    facets: computeFacets(index.subjects, filters),
    index_built_at: index.builtAt,
  });
}

// ============================================================
// 洞察库读模型 GET /api/insights/library
//
// 形状（前后端契约，改这里必须同步 docs/superpowers/specs/2026-09-03-insight-library-module-taskcard.md）：
//   { ok, total, page, page_size, subjects: LibrarySubject[], facets: LibraryFacets, index_built_at }
//
// ⚠️ 首屏不逐条下发洞察：返回的是**主体卡**（含至多 6 条头条指标）+ 聚合分面。
//    某个主体的全部条目在展开时另取（?subject=<id>）。/campus 曾因逐条下发 16,494 条
//    岗位把首屏做到 10.1s / 2.09MB，这里从一开始就不许走那条路。
//
// ⚠️ 索引跨实例缓存（unstable_cache，10 分钟）：它只依赖库里的洞察，与用户无关，
//    因此可以全站共享。serverless 多实例下进程内 Map 命中率≈0，不要退回去。
// ============================================================
import { NextRequest, NextResponse } from "next/server";
import { unstable_cache } from "next/cache";
import { requireUser } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import { fetchAllPages } from "@/lib/supabase-paginate";
import { ITEM_COLUMNS, flattenSources } from "@/lib/insight-bundle";
import {
  buildLibraryIndex,
  computeFacets,
  filterSubjects,
  parseLibraryFilters,
  sortSubjects,
  type LibrarySubject,
  type RawItemRow,
  type RawSubjectRow,
} from "@/lib/insight-library";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const PAGE_SIZE = 24;
/** 主体卡上最多展示几条指标；其余在展开时取。 */
const CARD_METRICS = 6;
const INDEX_TTL_SECONDS = 600;

async function loadIndex(): Promise<{ subjects: LibrarySubject[]; builtAt: string }> {
  const supabase = createServiceClient();

  // 1) 主体（公司 × 业务线）。rejected 是人工治理结论，索引里直接不要。
  const subjectRows = await fetchAllPages<RawSubjectRow>((from, to) =>
    supabase
      .from("insight_subjects")
      .select("id,company_id,kind,name,job_count,status")
      .eq("status", "active")
      .order("id", { ascending: true })
      .range(from, to),
  );

  // 2) 条目 + 来源。来源是 claim 展示门的必需输入（时间窗 + ≥2 独立域名），
  //    不带来源就没法判断「这条能不能展示」，卡面计数会比点进去看到的多。
  const itemRows = await fetchAllPages<any>((from, to) =>
    supabase
      .from("insight_items")
      .select(`${ITEM_COLUMNS}, insight_item_sources(insight_sources(url, deidentified, source_kind, publisher))`)
      .eq("status", "active")
      .not("subject_id", "is", null)
      .order("id", { ascending: true })
      .range(from, to),
  );
  const items: RawItemRow[] = itemRows.map((raw) => ({
    ...(raw as RawItemRow),
    sources: flattenSources(raw),
  }));

  // 3) 公司画像（名字 + 行业）
  const profileRows = await fetchAllPages<{ id: string; company: string; industry: string | null }>(
    (from, to) =>
      supabase
        .from("company_profiles")
        .select("id,company,industry")
        .order("id", { ascending: true })
        .range(from, to),
  );
  const companies = new Map(
    profileRows.map((row) => [row.id, { company: row.company, industry: row.industry ?? null }]),
  );

  return {
    subjects: buildLibraryIndex(subjectRows, items, companies),
    builtAt: new Date().toISOString(),
  };
}

const getCachedIndex = unstable_cache(loadIndex, ["insight-library-index-v1"], {
  revalidate: INDEX_TTL_SECONDS,
  tags: ["insight-library"],
});

/** 主体卡只带头条指标：signal 在前（第一方最可信），再按样本量。 */
function trimForCard(subject: LibrarySubject): LibrarySubject {
  const rank: Record<string, number> = { signal: 0, fact: 1, claim: 2 };
  const metrics = [...subject.metrics]
    .sort(
      (a, b) =>
        (rank[a.assertion] ?? 9) - (rank[b.assertion] ?? 9) ||
        (b.sample_size || 0) - (a.sample_size || 0),
    )
    .slice(0, CARD_METRICS);
  return { ...subject, metrics };
}

export async function GET(request: NextRequest) {
  const auth = await requireUser();
  if (auth.error) return auth.error;

  const params = request.nextUrl.searchParams;
  const filters = parseLibraryFilters(params);
  const page = Math.max(1, Number(params.get("page") || 1) || 1);

  let index: { subjects: LibrarySubject[]; builtAt: string };
  try {
    index = await getCachedIndex();
  } catch (error: any) {
    console.error("[insights/library] 建索引失败", error?.message || error);
    return NextResponse.json({ ok: false, error: "index_failed" }, { status: 500 });
  }

  // 单个主体的全部条目（展开时用）：这里不再限 CARD_METRICS。
  const subjectId = params.get("subject");
  if (subjectId) {
    const hit = index.subjects.find((s) => s.id === subjectId);
    if (!hit) return NextResponse.json({ ok: false, error: "not_found" }, { status: 404 });
    return NextResponse.json({ ok: true, subject: hit, index_built_at: index.builtAt });
  }

  const matched = filterSubjects(index.subjects, filters);
  const sorted = sortSubjects(matched, filters.sort);
  const start = (page - 1) * PAGE_SIZE;

  return NextResponse.json({
    ok: true,
    total: sorted.length,
    page,
    page_size: PAGE_SIZE,
    subjects: sorted.slice(start, start + PAGE_SIZE).map(trimForCard),
    facets: computeFacets(index.subjects, filters),
    index_built_at: index.builtAt,
  });
}

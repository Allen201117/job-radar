export const dynamic = "force-dynamic";

import { redirect } from "next/navigation";
import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { Compass } from "@phosphor-icons/react/ssr";
import { getRequestUser } from "@/lib/auth";
import { attachCardContents, getInsightLibraryIndex } from "@/lib/insight-library-store";
import {
  computeFacets,
  filterSubjects,
  parseLibraryFilters,
  sortSubjects,
  trimSubjectForCard,
  LIBRARY_PAGE_SIZE,
} from "@/lib/insight-library";
import InsightsClient from "./insights-client";

export const metadata = { title: "洞察库 · 求职雷达" };

const HERO = {
  eyebrow: "洞察库",
  title: "年终奖、加班、面试、晋升——别人怎么说的",
  description:
    "与岗位库平级的第二个库，只放你在岗位描述里看不到的那部分。每条都标清是「官方事实」还是「公开说法」，并给出来源——是转述，不是我们的结论。",
};

export default async function InsightsPage({
  searchParams,
}: {
  // 筛选条件同步在 URL 里：可分享、可收藏、刷新不丢。
  // 服务端就按它渲染，避免「先出全量、再闪一下变成筛选结果」。
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const user = await getRequestUser();
  if (!user) redirect("/login?next=/insights");

  const raw = (await searchParams) || {};
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(raw)) {
    for (const one of Array.isArray(value) ? value : [value]) {
      if (one) params.append(key, one);
    }
  }
  const filters = parseLibraryFilters(params);

  const index = await getInsightLibraryIndex();
  // 首屏在服务端就把第一页算好，客户端改筛选时再走 /api/insights/library。
  // 索引是跨实例缓存的，这里只是一次内存筛选与排序。
  const sorted = sortSubjects(filterSubjects(index.subjects, filters), filters.sort);
  const firstPage = await attachCardContents(
    sorted.slice(0, LIBRARY_PAGE_SIZE).map(trimSubjectForCard),
    3,
    filters.metric,
  );

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero {...HERO} icon={Compass} />
        <InsightsClient
          initialSubjects={firstPage}
          initialTotal={sorted.length}
          initialFacets={computeFacets(index.subjects, filters)}
          initialFilters={{
            q: filters.q || "",
            kind: filters.kind || "",
            assertion: filters.assertion || "",
            dimension: filters.dimension || "",
            metric: filters.metric || "",
            metricMin: filters.metricMin == null ? "" : String(filters.metricMin),
            metricMax: filters.metricMax == null ? "" : String(filters.metricMax),
            freshness: filters.freshness || "",
            sort: filters.sort || "fresh",
          }}
          subjectTotal={index.subjects.length}
        />
      </ProductPage>
    </div>
  );
}

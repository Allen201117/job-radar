export const dynamic = "force-dynamic";
// 洞察索引过期后在 waitUntil 里后台重建（lib/insight-library-store）：给它留足时间，
// 别让函数默认时长把重建掐断 —— 2026-09-04「索引三小时不动」疑似就是这么断的。
export const maxDuration = 60;

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

export default async function InsightsPage({
  searchParams,
}: {
  // 筛选条件同步在 URL 里：可分享、可收藏、刷新不丢。
  // 服务端就按它渲染，避免「先出全量、再闪一下变成筛选结果」。
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const tPageStart = performance.now();
  const requestStartedAt = Date.now();
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
  // 诊断开关：只有显式带 ?__timing=1 才把各段耗时渲染进页面（隐藏 JSON），普通用户拿不到。
  const wantTiming = params.get("__timing") === "1";

  const tIndex = performance.now();
  const index = await getInsightLibraryIndex();
  const indexMs = performance.now() - tIndex;
  // 首屏在服务端就把第一页算好，客户端改筛选时再走 /api/insights/library。
  // 索引是跨实例缓存的，这里只是一次内存筛选与排序。
  const sorted = sortSubjects(filterSubjects(index.subjects, filters), filters.sort);
  const tCards = performance.now();
  const firstPage = await attachCardContents(
    sorted.slice(0, LIBRARY_PAGE_SIZE).map(trimSubjectForCard),
    3,
    filters.metric,
  );
  const cardsMs = performance.now() - tCards;
  const timing = wantTiming
    ? {
        index_ms: Math.round(indexMs),
        // 本次请求是否亲自建了索引（缓存没命中）：builtAt 落在请求开始之后。
        index_built_in_request: Date.parse(index.builtAt) >= requestStartedAt,
        index_age_s: Math.round((Date.now() - Date.parse(index.builtAt)) / 1000),
        index_build: index.buildTiming ?? null,
        cards_ms: Math.round(cardsMs),
        server_total_ms: Math.round(performance.now() - tPageStart),
      }
    : null;

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero title="洞察库" icon={Compass} />
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
        {timing && (
          <script
            type="application/json"
            id="jr-timing"
            // 纯诊断数据（毫秒数与条数，无用户信息）；type 非 JS，浏览器不执行。
            dangerouslySetInnerHTML={{ __html: JSON.stringify(timing) }}
          />
        )}
      </ProductPage>
    </div>
  );
}

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

export default async function InsightsPage() {
  const user = await getRequestUser();
  if (!user) redirect("/login?next=/insights");

  const index = await getInsightLibraryIndex();
  // 首屏在服务端就把第一页算好，客户端改筛选时再走 /api/insights/library。
  // 索引是跨实例缓存的，这里只是一次内存筛选与排序。
  const filters = {};
  const sorted = sortSubjects(filterSubjects(index.subjects, filters), "fresh");
  const firstPage = await attachCardContents(
    sorted.slice(0, LIBRARY_PAGE_SIZE).map(trimSubjectForCard),
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
          subjectTotal={index.subjects.length}
        />
      </ProductPage>
    </div>
  );
}

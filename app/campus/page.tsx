export const dynamic = "force-dynamic";

import { unstable_cache } from "next/cache";
import { redirect } from "next/navigation";
import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { GraduationCap } from "@phosphor-icons/react/ssr";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import { companiesForIndustries, getUserCampusScope } from "@/lib/campus-user-industries";
import { getCampusZone } from "@/lib/jobs-store/read";
import { getCampusSourceCoverage } from "@/lib/campus-sources";
import { windowStatus, compareCompanyCards } from "@/lib/campus-zone";
import { getRecruitmentCyclesForCompanies } from "@/lib/recruitment-cycle-store";
import { getRecentCampusSurges } from "@/lib/campus-surge-store";
import { buildCampusFacets, type CampusFilterOptions } from "@/lib/campus-facets";
import {
  campusTimelineSummary,
  campusPreciseDates,
  campusBatchTimingGap,
  cleanCampusDeadlineMs,
} from "@/lib/recruitment-cycle";
import CampusClient, { type CampusBoardCard } from "./campus-client";

export type CampusBoard = {
  cards: CampusBoardCard[];
  filterOptions: { campus: CampusFilterOptions; intern: CampusFilterOptions };
};

/**
 * 校招看板的重活：聚合岗位、算职能分面、拉源覆盖 / 招聘周期 / 开闸快照。
 *
 * **只依赖行业清单，不含任何用户私有数据**，所以可以跨请求共享缓存 —— 这正是本页首屏
 * 从 10s 降下来的关键：这一坨活 live 实测要数秒（光 jobs 库那条聚合查询就 ~1.3s，
 * 还要把 30 家公司近 1.7 万个岗的 JD 正文取回来跑分类），逐请求重算纯属浪费。
 *
 * ⚠️ 缓存里**不放** windowStatus / 排序结果：它们依赖「此刻」（72h 新鲜度阈值），
 * 必须每请求用缓存里的 lastSeenAtMs 现算，否则徽章会随缓存一起冻住。
 * ⚠️ 函数体内不得读 cookies()/headers() 等动态 API（unstable_cache 限制）；
 * 这里用的 createServiceClient 只读环境变量，安全。
 */
const loadCampusBoard = unstable_cache(
  async (industries: string[]): Promise<CampusBoard> => {
    const companies = companiesForIndustries(industries);
    const [zone, sourceCov, cyclesByPattern, surgesByPattern] = await Promise.all([
      getCampusZone(companies),
      getCampusSourceCoverage(companies),
      getRecruitmentCyclesForCompanies(companies),
      getRecentCampusSurges(companies),
    ]);

    const campus = buildCampusFacets(zone.map((z) => ({ pattern: z.pattern, jobs: z.campusJobs })));
    const intern = buildCampusFacets(zone.map((z) => ({ pattern: z.pattern, jobs: z.internJobs })));

    const cards: CampusBoardCard[] = zone.map((z) => {
      const src = sourceCov.get(z.pattern) || { hasAnySource: z.hasAnyActiveJob, hasCampusSource: false };
      const deadlines = z.campusJobs
        .map((j) => (j.deadline ? Date.parse(j.deadline) : NaN))
        .filter((t) => !Number.isNaN(t));
      const obs = cyclesByPattern.get(z.pattern) || [];
      // 快路①：清洗后的公司级最近截止（滤掉「长期有效」/占位/远未来/过去），只作弱档提示。
      const cleanDl = z.campusJobs
        .map((j) => cleanCampusDeadlineMs(j.deadline))
        .filter((t): t is number => t != null);
      return {
        company: z.company,
        pattern: z.pattern,
        // ⚠️ 只下发聚合分面，**一条岗位记录都不下发**：逐条下发实测单页 2.09 MB（16,494 条），
        // 而岗位卡默认折叠、用户根本没看。展开某家公司时才经 /api/campus-zone/jobs 取完整行。
        campusTotal: campus.totals.get(z.pattern) ?? 0,
        internTotal: intern.totals.get(z.pattern) ?? 0,
        campusFacets: campus.byPattern.get(z.pattern) ?? [],
        internFacets: intern.byPattern.get(z.pattern) ?? [],
        // windowStatus 的三个输入原样带出，徽章在页面里按「此刻」现算（见上方注释）。
        hasCampusSource: src.hasCampusSource,
        hasAnySource: src.hasAnySource,
        lastSeenAtMs: z.lastSeenAtMs,
        nearestDeadlineMs: deadlines.length ? Math.min(...deadlines) : null,
        // ⚠️ 把「当下在招校招岗数」作为事实喂进去：时间线是外部聚合的推测，岗位库是第一手事实，
        // 打架时（如高途 212 个在招岗 vs「已近尾声」）必须以事实为准，否则同一张卡自相矛盾。
        timeline: obs.length > 0
          ? campusTimelineSummary(obs, new Date(), { campusJobCount: campus.totals.get(z.pattern) ?? 0 })
          : null,
        preciseDates: obs.length > 0 ? campusPreciseDates(obs) : [],
        batchTimingGap: obs.length > 0 ? campusBatchTimingGap(obs) : null,
        cleanDeadlineMs: cleanDl.length ? Math.min(...cleanDl) : null,
        // 「刚开正式批」：近 7 天检测到校招岗一次性放量（判据 crawler/campus_lane.detect_surge）。
        // 秋招正式批是一次性放量，这是用户最该马上行动的信号。
        surge: surgesByPattern.get(z.pattern) ?? null,
        // 明确标了往届（如 2026 届）而被移出列表的岗数——不静默丢弃，卡面照实说一句。
        pastClassJobCount: z.pastClassJobCount,
        // 每请求现算，这里先占位（缓存里不放随时间变化的值）。
        window: { state: "not_ingested" as const },
      };
    });

    return { cards, filterOptions: { campus: campus.options, intern: intern.options } };
  },
  ["campus-board-v1"],
  // 10 分钟：校招看板的数据由每日 / 每小时的抓取车道产出，10 分钟的滞后用户感知不到，
  // 但足以让绝大多数请求走缓存、不再逐次重算这坨重活。
  { revalidate: 600, tags: ["campus-board"] },
);

const HERO = {
  eyebrow: "校招专区",
  title: "按你的行业锁定必投目标公司的校招窗口",
  description:
    "已接入官方校招源并持续验证的岗位；据公开信息追踪聚合必投清单公司的校招/实习岗与窗口状态，非官方、仅供参考。",
};

export default async function CampusPage() {
  const user = await getRequestUser();
  if (!user) redirect("/login?next=/campus");

  const supabase = await createServerSupabase();
  const { rawIndustries, industries } = await getUserCampusScope(supabase, user.id);

  // 缓存键只认行业清单本身，排序后传入让「同一组行业、不同顺序」共用一份缓存。
  const board = await loadCampusBoard([...industries].sort());

  // 徽章与排序按「此刻」现算：缓存里存的是 lastSeenAtMs 等原始输入，不是随时间失效的结论。
  const nowMs = Date.now();
  const cards = board.cards
    .map((c) => ({
      ...c,
      window: windowStatus({
        campusJobCount: c.campusTotal,
        hasCampusSource: c.hasCampusSource,
        hasAnySource: c.hasAnySource,
        lastSeenAtMs: c.lastSeenAtMs,
        nowMs,
      }),
    }))
    .sort(compareCompanyCards);

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero eyebrow={HERO.eyebrow} title={HERO.title} description={HERO.description} icon={GraduationCap} />
        <CampusClient
          cards={cards}
          industries={industries}
          hasIndustry={rawIndustries.length > 0}
          filterOptions={board.filterOptions}
        />
      </ProductPage>
    </div>
  );
}

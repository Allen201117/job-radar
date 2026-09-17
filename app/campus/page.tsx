export const dynamic = "force-dynamic";
// ⚠️ 看板重算（30 家 ~2 万岗、含 JD 正文取回跑职能分类）live 实测数秒到十几秒。Hobby 档函数默认
// 10s：unstable_cache 的后台重算一旦被杀，Next 会**永远**继续服务旧快照且不报错——2026-09-09 线上
// /campus 就卡在 09-03 之前的快照上（京东 0 / 小米 6 / 百度 2，而库里是 127 / 852 / 158，接口
// /api/campus-zone/jobs 不走缓存返回的正是库里的数）。抬到 60s（Hobby 上限）给重算留足余量。
export const maxDuration = 60;

import { unstable_cache } from "next/cache";
import { redirect } from "next/navigation";
import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { GraduationCap } from "@phosphor-icons/react/ssr";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import { companiesForIndustries, getUserCampusScope } from "@/lib/campus-user-industries";
import { getCampusZone, getCampusFreshStats } from "@/lib/jobs-store/read";
import { getCampusSourceCoverage } from "@/lib/campus-sources";
import { windowStatus, compareCompanyCardsByFit } from "@/lib/campus-zone";
import { getRecruitmentCyclesForCompanies } from "@/lib/recruitment-cycle-store";
import { getRecentCampusSurges } from "@/lib/campus-surge-store";
import {
  buildCampusFacets,
  countFacetsForFit,
  selectFitIndexes,
  type CampusFilterOptions,
} from "@/lib/campus-facets";
import { classifyJobFunction, normalizeRolePhrases } from "@/lib/china-keyword-expansion";
import {
  campusTimelineSummary,
  campusPreciseDates,
  campusBatchTimingGap,
  cleanCampusDeadlineMs,
} from "@/lib/recruitment-cycle";
import CampusClient, { type CampusBoardCard } from "./campus-client";
import { snapshotAgeLabel } from "@/lib/relative-time";
import { currentGradClass } from "@/lib/grad-class";

/** 快照里的卡片**不含**「对你有货」的对口数：那是用户私有画像算出来的，进了按行业共享的缓存
 *  就会把 A 用户的方向算给 B 用户看。对口数在缓存外逐请求现算（见 CampusPage）。 */
type CachedCampusCard = Omit<CampusBoardCard, "fitCampusCount" | "fitInternCount" | "fitCount" | "fitTotal">;

export type CampusBoard = {
  cards: CachedCampusCard[];
  filterOptions: { campus: CampusFilterOptions; intern: CampusFilterOptions };
  /** 这份快照算出来的时刻。页面渲染成「数据更新于 …」，缓存卡死时用户和我们都能一眼看出来。 */
  generatedAtMs: number;
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
    const startedAt = Date.now();
    const companies = companiesForIndustries(industries);
    const [zone, sourceCov, cyclesByPattern, surgesByPattern] = await Promise.all([
      getCampusZone(companies),
      getCampusSourceCoverage(companies),
      getRecruitmentCyclesForCompanies(companies),
      getRecentCampusSurges(companies),
    ]);

    const campus = buildCampusFacets(zone.map((z) => ({ pattern: z.pattern, jobs: z.campusJobs })));
    const intern = buildCampusFacets(zone.map((z) => ({ pattern: z.pattern, jobs: z.internJobs })));

    const cards: CachedCampusCard[] = zone.map((z) => {
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

    const generatedAtMs = Date.now();
    // 留一条可 grep 的耗时日志：下次再「卡在旧快照」，Vercel 日志里能直接看到重算到底跑了多久 / 有没有跑完。
    console.log(`[campus-board] rebuilt industries=${industries.join(",")} companies=${companies.length} ms=${generatedAtMs - startedAt}`);
    return { cards, filterOptions: { campus: campus.options, intern: intern.options }, generatedAtMs };
  },
  // v3：职能改读物化列 job_function 后，看板重算不再拉几万条正文、变轻，换 key 让线上那份卡死的
  //     v2 facet 快照立刻失效并用新的轻重算刷新（Vercel 数据缓存跨部署存活，光部署不会刷掉它）。
  ["campus-board-v3"],
  // 10 分钟：校招看板的数据由每日 / 每小时的抓取车道产出，10 分钟的滞后用户感知不到，
  // 但足以让绝大多数请求走缓存、不再逐次重算这坨重活。
  { revalidate: 600, tags: ["campus-board"] },
);

export default async function CampusPage() {
  const user = await getRequestUser();
  if (!user) redirect("/login?next=/campus");

  const supabase = await createServerSupabase();
  const { industries, industrySource, targetRoles, targetLocations } = await getUserCampusScope(
    supabase,
    user.id,
  );

  // 缓存键只认行业清单本身，排序后传入让「同一组行业、不同顺序」共用一份缓存。
  const board = await loadCampusBoard([...industries].sort());

  // 「计数 + 新鲜度」用轻查询每请求现算，绕开这个可能冻住的重快照（见 getCampusFreshStats 注释）：
  // 快照卡死时，卡面的岗位数与「数据待更新」徽章不再跟着冻在旧值。轻查询失败就回退快照值、绝不让页面崩。
  const nowMs = Date.now();
  let fresh: Awaited<ReturnType<typeof getCampusFreshStats>> | null = null;
  try {
    fresh = await getCampusFreshStats(companiesForIndustries(industries));
  } catch (err) {
    console.error("[campus-board] fresh stats failed; fall back to snapshot counts", err);
  }

  // 「对你有货」：必投清单**保持静态**（北极星口径不动），这里只按用户方向派生一份可投量，
  // 用来排序 + 在卡面上区分「有你能投的岗」与「本季暂无对口岗」。
  //
  // ⚠️ 这段刻意**在 unstable_cache 之外**算：它吃用户私有数据（目标岗位 / 城市），
  // 放进那份按行业共享的快照里就会把 A 用户的方向算给 B 用户看。
  // 成本可忽略：分面已按四元组压过（live 16,494 条 → ~1,900 个四元组），只是再遍历一遍数组。
  //
  // 方向判定与 /today 推荐同口径：normalizeRolePhrases（拆「产品/运营」、去「相关·岗位」填充）
  // → classifyJobFunction 逐条整体分类 → 丢掉判不出的「其他」。**不拿关键词/技能判方向**
  // （"SQL/Python" 会把产品用户污染成研发，见 lib/opportunities/eligibility.userTargetFunctions 的注释）。
  const targetFunctions = Array.from(
    new Set(
      normalizeRolePhrases(targetRoles)
        .map((role: string) => classifyJobFunction({ title: role }))
        .filter((fn: string) => fn && fn !== "其他"),
    ),
  ) as string[];
  // 判不出方向 → fitCount 记 null（不是 0）：0 会被读成「一个对口岗都没有」，而事实是「我们不知道」。
  const fitKnown = targetFunctions.length > 0;
  const fitCampus = selectFitIndexes(targetFunctions, targetLocations, board.filterOptions.campus);
  const fitIntern = selectFitIndexes(targetFunctions, targetLocations, board.filterOptions.intern);

  // 徽章与排序按「此刻」现算：用现算的计数 / lastSeenAt（拿不到才退回快照里的原始输入）。
  const cards = board.cards
    .map((c) => {
      const f = fresh?.byPattern.get(c.pattern);
      const campusTotal = f ? f.campusTotal : c.campusTotal;
      const internTotal = f ? f.internTotal : c.internTotal;
      const lastSeenAtMs = f ? f.lastSeenAtMs : c.lastSeenAtMs;
      // ⚠️ 对口数来自**快照里的分面**，而总数是每请求现算的轻查询（getCampusFreshStats）——
      // 两者最多差一个 10 分钟的缓存周期。夹一下上限，免得出现「对口 20 个 / 共 12 个」这种自相矛盾
      // 的卡面（宁可少报，不可报出一个解释不了的数）。
      const fitCampusCount = fitKnown
        ? Math.min(countFacetsForFit(c.campusFacets, fitCampus), campusTotal)
        : null;
      const fitInternCount = fitKnown
        ? Math.min(countFacetsForFit(c.internFacets, fitIntern), internTotal)
        : null;
      return {
        ...c,
        campusTotal,
        internTotal,
        lastSeenAtMs,
        fitCampusCount,
        fitInternCount,
        // 排序用「当前模式」的两个值；服务端按默认模式（校招）排，切到实习由客户端同规则重排。
        fitCount: fitCampusCount,
        fitTotal: campusTotal,
        window: windowStatus({
          campusJobCount: campusTotal,
          hasCampusSource: c.hasCampusSource,
          hasAnySource: c.hasAnySource,
          lastSeenAtMs,
          nowMs,
        }),
      };
    })
    .sort(compareCompanyCardsByFit);

  // 计数现算成功 → 新鲜度按现算时刻（≈刚刚）；失败回退 → 沿用快照生成时刻，让「卡死」照旧一眼可见。
  const freshnessAtMs = fresh ? fresh.fetchedAtMs : board.generatedAtMs;

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero title="校园招聘" icon={GraduationCap} />
        <CampusClient
          cards={cards}
          industries={industries}
          industrySource={industrySource}
          filterOptions={board.filterOptions}
          generatedLabel={snapshotAgeLabel(freshnessAtMs, nowMs)}
          seasonGradClass={currentGradClass()}
          fitFunctions={targetFunctions}
          fitCities={targetLocations}
        />
      </ProductPage>
    </div>
  );
}

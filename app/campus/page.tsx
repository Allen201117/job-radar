export const dynamic = "force-dynamic";

import { redirect } from "next/navigation";
import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { GraduationCap } from "@phosphor-icons/react/ssr";
import { createServerSupabase, getRequestUser } from "@/lib/auth";
import { resolveMustApplyIndustries, MUST_APPLY_BY_INDUSTRY } from "@/lib/must-apply-list";
import { getCampusZone } from "@/lib/jobs-store/read";
import { getCampusSourceCoverage } from "@/lib/campus-sources";
import { windowStatus, compareCompanyCards } from "@/lib/campus-zone";
import { getRecruitmentCyclesForCompanies } from "@/lib/recruitment-cycle-store";
import { getRecentCampusSurges } from "@/lib/campus-surge-store";
import { classifyJobFunction } from "@/lib/china-keyword-expansion";
import {
  campusTimelineSummary,
  campusPreciseDates,
  campusBatchTimingGap,
  cleanCampusDeadlineMs,
} from "@/lib/recruitment-cycle";
import CampusClient from "./campus-client";

/** 下发给客户端的轻量岗位记录：只带「筛选 + 计数 + 按需取详情」真正需要的字段。
 *
 * 关键是 `fn`：职能标签在**服务端**用完整 summary 算好（classifyJobFunction 与客户端原先
 * 调用的是同一份实现、同一份输入），客户端拿标签直接比对即可 → 筛选选项、每家公司的计数、
 * 任意筛选组合下的结果都与改造前完全一致，**精度零损失**，但不必把 JD 正文发到浏览器。
 * 完整岗位行在用户展开某家公司时经 `/api/jobs/by-ids` 按需取回。 */
function slimJob(j: any) {
  return {
    id: j.id,
    city: j.city ?? null,
    education: j.education ?? null,
    fn: classifyJobFunction({ title: j.title, job_type: j.job_type, summary: j.summary }),
  };
}

/** 从若干公司的岗位桶里收集筛选候选值。与客户端原实现同口径（同样 trim / filter(Boolean) / sort）。 */
function collectOptions(lists: Array<ReturnType<typeof slimJob>[]>) {
  const cities = new Set<string>();
  const edus = new Set<string>();
  const fns = new Set<string>();
  for (const jobs of lists) {
    for (const j of jobs) {
      if (j.city) cities.add(String(j.city).trim());
      if (j.education) edus.add(String(j.education).trim());
      fns.add(j.fn);
    }
  }
  return {
    cityOptions: Array.from(cities).filter(Boolean).sort(),
    educationOptions: Array.from(edus).filter(Boolean).sort(),
    functionOptions: Array.from(fns).filter(Boolean).sort(),
  };
}

const HERO = {
  eyebrow: "校招专区",
  title: "按你的行业锁定必投目标公司的校招窗口",
  description:
    "已接入官方校招源并持续验证的岗位；据公开信息追踪聚合必投清单公司的校招/实习岗与窗口状态，非官方、仅供参考。",
};

export default async function CampusPage() {
  const user = await getRequestUser();
  if (!user) redirect("/login?next=/campus");

  // 读用户行业：candidate_profiles（简历解析）优先，回退 user_preferences（手填偏好）。
  // 走 createServerSupabase（RLS，只读用户自己的行），与 today/saved 等页面同一模式,
  // 不用 service-role client（这不是 admin 场景）。
  const supabase = await createServerSupabase();
  const [profRes, prefRes] = await Promise.all([
    supabase.from("candidate_profiles").select("target_industries").eq("user_id", user.id).maybeSingle(),
    supabase.from("user_preferences").select("target_industries").eq("user_id", user.id).maybeSingle(),
  ]);
  const rawIndustries =
    (profRes.data?.target_industries as string[] | null) ||
    (prefRes.data?.target_industries as string[] | null) ||
    [];
  const industries = resolveMustApplyIndustries(rawIndustries); // 空/归一不出 → 兜底"互联网/科技"

  // 按行业取必投清单公司，跨行业按 pattern 去重（同一公司可能出现在多个行业清单里）。
  const companies = Array.from(
    new Map(
      industries.flatMap((ind) => MUST_APPLY_BY_INDUSTRY[ind] || []).map((c) => [c.pattern, c] as const),
    ).values(),
  );

  const [zone, sourceCov, cyclesByPattern, surgesByPattern] = await Promise.all([
    getCampusZone(companies),
    getCampusSourceCoverage(companies),
    getRecruitmentCyclesForCompanies(companies),
    getRecentCampusSurges(companies),
  ]);

  const nowMs = Date.now();
  const cards = zone.map((z) => {
    const src = sourceCov.get(z.pattern) || { hasAnySource: z.hasAnyActiveJob, hasCampusSource: false };
    const window = windowStatus({
      campusJobCount: z.campusJobs.length,
      hasCampusSource: src.hasCampusSource,
      hasAnySource: src.hasAnySource,
      lastSeenAtMs: z.lastSeenAtMs,
      nowMs,
    });
    const deadlines = z.campusJobs
      .map((j) => (j.deadline ? Date.parse(j.deadline) : NaN))
      .filter((t) => !Number.isNaN(t));
    const nearestDeadlineMs = deadlines.length ? Math.min(...deadlines) : null;
    const obs = cyclesByPattern.get(z.pattern) || [];
    const timeline = obs.length > 0 ? campusTimelineSummary(obs) : null;
    const preciseDates = obs.length > 0 ? campusPreciseDates(obs) : [];
    const batchTimingGap = obs.length > 0 ? campusBatchTimingGap(obs) : null;
    // 快路①：清洗后的公司级最近截止（滤掉「长期有效」/占位/远未来/过去），只作弱档提示。
    const cleanDl = z.campusJobs
      .map((j) => cleanCampusDeadlineMs(j.deadline))
      .filter((t): t is number => t != null);
    const cleanDeadlineMs = cleanDl.length ? Math.min(...cleanDl) : null;
    return {
      company: z.company,
      pattern: z.pattern,
      // ⚠️ 只下发轻量岗位记录，**绝不再 `{...z}`**：那会把每家公司的完整岗位行（含 JD 正文）
      // 全序列化进 props，实测单页 16.3 MB，而岗位卡默认折叠、用户根本没看。
      campusJobs: z.campusJobs.map(slimJob),
      internJobs: z.internJobs.map(slimJob),
      window,
      nearestDeadlineMs, // 仅供下面 compareCompanyCards 在服务端排序，客户端不读
      timeline,
      preciseDates,
      batchTimingGap,
      cleanDeadlineMs,
      // 「刚开正式批」：近 7 天检测到校招岗一次性放量（判据 crawler/campus_lane.detect_surge）。
      // 秋招正式批是一次性放量，这是用户最该马上行动的信号。
      surge: surgesByPattern.get(z.pattern) ?? null,
      // 明确标了往届（如 2026 届）而被移出列表的岗数——不静默丢弃，卡面照实说一句。
      pastClassJobCount: z.pastClassJobCount,
    };
  });
  cards.sort(compareCompanyCards);

  // 筛选下拉候选值改在**服务端**算：客户端原先要靠 classifyJobFunction(title+job_type+summary)
  // 现算职能，才不得不拿到正文。现在服务端用完整正文算好（同一份实现、同一份输入、同样
  // 先收集再 filter(Boolean).sort()），选项值与改造前逐字节一致——精度零损失。
  // 按 mode 分开算，与客户端原来「只从当前态那个桶里收集」的口径一致。
  const filterOptions = {
    campus: collectOptions(cards.map((c) => c.campusJobs)),
    intern: collectOptions(cards.map((c) => c.internJobs)),
  };

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero eyebrow={HERO.eyebrow} title={HERO.title} description={HERO.description} icon={GraduationCap} />
        <CampusClient
          cards={cards}
          industries={industries}
          hasIndustry={rawIndustries.length > 0}
          filterOptions={filterOptions}
        />
      </ProductPage>
    </div>
  );
}

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
import CampusClient from "./campus-client";

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

  const [zone, sourceCov] = await Promise.all([
    getCampusZone(companies),
    getCampusSourceCoverage(companies),
  ]);

  const nowMs = Date.now();
  const cards = zone.map((z) => {
    const src = sourceCov.get(z.pattern) || { hasAnySource: z.hasAnyActiveJob, hasCampusSource: false };
    const window = windowStatus({
      campusJobCount: z.campusJobs.length,
      hasCampusSource: src.hasCampusSource,
      hasAnySource: src.hasAnySource || z.hasAnyActiveJob,
      lastSeenAtMs: z.lastSeenAtMs,
      nowMs,
    });
    const deadlines = z.campusJobs
      .map((j) => (j.deadline ? Date.parse(j.deadline) : NaN))
      .filter((t) => !Number.isNaN(t));
    const nearestDeadlineMs = deadlines.length ? Math.min(...deadlines) : null;
    return { ...z, window, nearestDeadlineMs };
  });
  cards.sort(compareCompanyCards);

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage>
        <ProductHero eyebrow={HERO.eyebrow} title={HERO.title} description={HERO.description} icon={GraduationCap} />
        <CampusClient cards={cards} industries={industries} hasIndustry={rawIndustries.length > 0} />
      </ProductPage>
    </div>
  );
}

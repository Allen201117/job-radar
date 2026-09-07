// 「热门在招」服务端组装：候选池（DB）→ 挑选（纯函数）→ 回填完整行 → 给 /today 的兜底视图用。
//
// ⚠️ 这份清单**不含任何用户私有数据**（不读偏好、不读简历、不读 job_actions），所以对所有
// 「还没设过求职目标」的用户完全相同 —— 因此整体走 unstable_cache 跨请求共享。
// 新用户注册后的第一次访问是产品最贵的一次首屏，不该让每个人各付一次 DB 的钱。
import "server-only";
import { unstable_cache } from "next/cache";
import { fetchPopularCandidates } from "./jobs-store/popular";
import { jobsByIds, jobsStoreEnabled } from "./jobs-store/read";
import { mustApplyPatterns, mustApplyUnion } from "./must-apply-list";
import { pickPopularJobs, POPULAR_INDUSTRIES } from "./popular-picks";
import type { Job } from "./types";

export interface PopularJob {
  job: Job;
  industry: string;
}

export interface PopularFeed {
  jobs: PopularJob[];
  /** 有货的行业（按必投清单顺序），前端 chips 用。 */
  industries: string[];
  generatedAt: string;
}

const EMPTY: PopularFeed = { jobs: [], industries: [], generatedAt: "" };

/** 同一家公司最多 2 条、单行业最多 12 条 → 上限 11 × 12 = 132 条，实际按有货行业数收敛。 */
const PER_COMPANY = 2;
const PER_INDUSTRY = 12;

/** 缓存 10 分钟：与 /campus 首屏同档。热门岗位的变化以「天」为单位，10 分钟的陈旧完全无感。 */
const CACHE_TTL_SECONDS = 600;

async function buildPopularFeed(): Promise<PopularFeed> {
  if (!jobsStoreEnabled()) return EMPTY;
  const patterns = mustApplyUnion("domestic").flatMap((c) => mustApplyPatterns(c));
  const candidates = await fetchPopularCandidates(patterns);
  if (!candidates.length) return EMPTY;

  const picks = pickPopularJobs(candidates, { perCompany: PER_COMPANY, perIndustry: PER_INDUSTRY });
  if (!picks.length) return EMPTY;

  // 挑完才回填完整行（summary / salary / deadline 等展示字段）：候选查询只取轻字段，
  // 一次性把两千行的完整 JD 拉过太平洋没有意义（同 /campus 的两段取数）。
  const rows = (await jobsByIds(picks.map((p) => p.id), true)) as Job[];
  const byId = new Map(rows.map((r) => [r.id, r]));

  const jobs: PopularJob[] = [];
  for (const pick of picks) {
    const job = byId.get(pick.id);
    // 取不到 = 这一刻它已被 sweep 判死并下架（activeOnly），正好不该展示。
    if (job) jobs.push({ job, industry: pick.industry });
  }
  const present = new Set(jobs.map((j) => j.industry));
  return {
    jobs,
    industries: POPULAR_INDUSTRIES.filter((i) => present.has(i)),
    generatedAt: new Date().toISOString(),
  };
}

const cachedPopularFeed = unstable_cache(buildPopularFeed, ["today-popular-feed-v1"], {
  revalidate: CACHE_TTL_SECONDS,
  tags: ["today-popular-feed"],
});

/**
 * 取「热门在招」清单。失败一律返回空清单而不是抛 —— 这是个**兜底位**，
 * 它自己挂掉不该把新用户的 /today 变成错误页（调用方看到空清单会退回纯引导态）。
 */
export async function getPopularFeed(): Promise<PopularFeed> {
  try {
    const feed = await cachedPopularFeed();
    // unstable_cache 条目跨部署存活：上线那一小段里缓存中可能是**旧形状**的对象，
    // 直接 feed.jobs.map 会在 /today 上抛。这里做一次形状检查，不合就当空。
    if (!feed || !Array.isArray(feed.jobs) || !Array.isArray(feed.industries)) return EMPTY;
    return feed;
  } catch (e) {
    console.error("[popular-feed] build failed:", (e as Error).message);
    return EMPTY;
  }
}

// 「热门在招」的挑选逻辑：把一大堆候选岗压成一份**跨行业、跨公司都摊得开**的短清单。
// 纯函数、不碰网络不碰 DB，测试见 tests/popular-picks.test.js。
//
// 为什么要专门挑：候选池是「每家公司取 3 条」直接拼起来的（见 lib/jobs-store/popular.ts，
// 那里刻意不排序换速度），原样渲染的话大公司和同名批量岗会把版面吃光，新用户看到的就是
// 「一屏 6 条星级咖啡师」而不是「各行业头部公司在招什么」。

import { MUST_APPLY_BY_INDUSTRY, MUST_APPLY_INDUSTRIES, mustApplyPatterns } from "./must-apply-list";

export interface PopularCandidate {
  id: string;
  company: string;
  title: string;
  location?: string | null;
  job_type?: string | null;
  jd_url?: string | null;
  posted_at?: string | null;
  last_seen_at?: string | null;
}

export interface PopularPick {
  id: string;
  /** 该岗归属的必投行业（清单里最长的命中 pattern 胜出，与校招专区同规则）。 */
  industry: string;
  company: string;
}

export interface PickOptions {
  /** 同一家公司最多出几条。默认 2。 */
  perCompany?: number;
  /** 单个行业最多出几条。默认 12。 */
  perIndustry?: number;
}

/** 行业顺序 = 必投清单的声明顺序，前端 chips 直接用它，保证服务端/客户端同序。 */
export const POPULAR_INDUSTRIES = MUST_APPLY_INDUSTRIES;

export interface IndustryNeedle {
  needle: string;
  industry: string;
}

/**
 * 公司名 → 行业的匹配表。
 *
 * 归属规则与 /campus 同源：一家公司只能落一个行业，靠「**更长的 pattern 优先**」实现
 * （`腾讯音乐 TME` 归 `%腾讯音乐%` 而不是 `%腾讯%`）。不这么定的话同一家公司会在两个
 * 行业里各出一次，用户切 chips 时会看到重复卡片。
 *
 * 判不出行业的公司**整条丢弃**、不塞「其它」桶：这份必投清单本身就是本产品对「热门公司」
 * 的定义（北极星口径），不在清单里的公司没有资格占这个兜底位。
 */
export function buildIndustryIndex(): IndustryNeedle[] {
  const entries: IndustryNeedle[] = [];
  for (const industry of MUST_APPLY_INDUSTRIES) {
    for (const company of MUST_APPLY_BY_INDUSTRY[industry] || []) {
      for (const pattern of mustApplyPatterns(company)) {
        const needle = pattern.replace(/%/g, "").trim().toLowerCase();
        if (needle) entries.push({ needle, industry });
      }
    }
  }
  // 长 needle 在前 →「腾讯音乐」压过「腾讯」。同长度保持清单顺序（排序稳定，结果可复现）。
  return entries.sort((a, b) => b.needle.length - a.needle.length);
}

export function industryOfCompany(company: string, index: IndustryNeedle[]): string | null {
  const lower = String(company || "").toLowerCase();
  if (!lower) return null;
  for (const entry of index) if (lower.includes(entry.needle)) return entry.industry;
  return null;
}

const BRACKETS = /[（(【[].*?[）)】\]]/g;
const SERIAL = /[a-z]?\d{3,}/g;
const SEPARATORS = /[\s\-_/·、,，.。:：|]+/g;

/**
 * 归一岗位标题，用来在同一家公司内部去重。
 *
 * 门店 / 产线类岗位一家公司能发几千条、只差城市或编号（星巴克 9,044 行归一后只有 36 种角色，
 * 见 CLAUDE.md「抬上限之后必须量多进来的是什么」）。**必须按归一标题去重、不能按 id**——
 * 这类岗每条 id 都不同，按 id 去重等于没去。
 */
export function normalizeTitle(title: string): string {
  return String(title || "")
    .toLowerCase()
    .replace(BRACKETS, " ")
    .replace(SERIAL, " ")
    .replace(SEPARATORS, "")
    .trim();
}

/** 新鲜度排序键：官方发布日优先，其次最近一次被抓到。都没有的排最后。 */
function freshnessKey(job: PopularCandidate): number {
  const posted = Date.parse(job.posted_at || "");
  if (!Number.isNaN(posted)) return posted;
  const seen = Date.parse(job.last_seen_at || "");
  return Number.isNaN(seen) ? 0 : seen;
}

/**
 * 从候选里挑出最终展示清单。
 *
 * 算法 = 行业内**按公司轮转**（round-robin）：第 1 轮每家公司各出 1 条，第 2 轮再各出 1 条……
 * 这样一家公司再大也压不住别人，`perCompany` 是硬上限。
 * 返回顺序再按行业交错，使「全部」视图第一屏就能看到多个行业而不是一整屏同一个行业。
 */
export function pickPopularJobs(
  candidates: PopularCandidate[],
  options: PickOptions = {},
): PopularPick[] {
  const perCompany = Math.max(1, options.perCompany ?? 2);
  const perIndustry = Math.max(1, options.perIndustry ?? 12);
  const index = buildIndustryIndex();

  // 行业 → 公司 → 岗位；同公司内去重同名岗
  const byIndustry = new Map<string, Map<string, PopularCandidate[]>>();
  const seenTitle = new Set<string>();
  for (const job of candidates) {
    if (!job || !job.id || !job.company || !job.title) continue;
    const industry = industryOfCompany(job.company, index);
    if (!industry) continue;
    const dedupKey = `${job.company.toLowerCase()} ${normalizeTitle(job.title)}`;
    if (seenTitle.has(dedupKey)) continue;
    seenTitle.add(dedupKey);
    let byCompany = byIndustry.get(industry);
    if (!byCompany) {
      byCompany = new Map();
      byIndustry.set(industry, byCompany);
    }
    const list = byCompany.get(job.company);
    if (list) list.push(job);
    else byCompany.set(job.company, [job]);
  }

  // 每个行业内做公司轮转，得到该行业的有序清单
  const perIndustryPicks = new Map<string, PopularPick[]>();
  for (const [industry, byCompany] of byIndustry) {
    const companies = Array.from(byCompany.entries()).map(([company, jobs]) => {
      jobs.sort((a, b) => freshnessKey(b) - freshnessKey(a) || a.id.localeCompare(b.id));
      return { company, jobs };
    });
    // 手里岗位最新的公司排前面；同分按公司名，避免同分随机导致每次刷新顺序乱跳。
    companies.sort(
      (a, b) => freshnessKey(b.jobs[0]) - freshnessKey(a.jobs[0]) || a.company.localeCompare(b.company),
    );

    const picks: PopularPick[] = [];
    for (let round = 0; round < perCompany && picks.length < perIndustry; round++) {
      for (const { company, jobs } of companies) {
        if (picks.length >= perIndustry) break;
        const job = jobs[round];
        if (!job) continue;
        picks.push({ id: job.id, industry, company });
      }
    }
    perIndustryPicks.set(industry, picks);
  }

  // 跨行业交错输出：第 1 轮每个行业各出 1 条……「全部」的第一屏因此必然是多行业混排。
  const out: PopularPick[] = [];
  const order = POPULAR_INDUSTRIES.filter((i) => (perIndustryPicks.get(i) || []).length > 0);
  for (let round = 0; round < perIndustry; round++) {
    for (const industry of order) {
      const list = perIndustryPicks.get(industry) || [];
      if (round < list.length) out.push(list[round]);
    }
  }
  return out;
}

// 「热门在招」候选池：给**还没设过求职目标**的新用户兜底用（app/today/page.tsx）。
// 与个人机会召回（opportunities.ts）无关——它不读任何用户数据，因此结果对所有新用户相同、可整体缓存。
import "server-only";
import { jobsQuery } from "./client";
import { resolveActiveCompanyNames } from "./read";

/** 候选行只带「挑选 + 分面」需要的轻字段；展示用的完整行由调用方按 id 回填（见 campus-zone 同款两段取数）。 */
export interface PopularCandidateRow {
  id: string;
  company: string;
  title: string;
  location: string | null;
  job_type: string | null;
  jd_url: string;
  posted_at: string | null;
  last_seen_at: string | null;
}

/**
 * 「这个岗还能点开」的判据 = **源上一次抓取时它还在列表里**（last_seen_at 在 30 小时内），
 * 不是 `enrich_checked_at`。
 *
 * 这条不是拍脑袋，是 2026-09-06 用 Playwright 真渲染对拍出来的（两个池子各随机抽 120 条、
 * 跨公司铺开、同一套 DEAD_MARKERS 判定）：
 *   · last_seen_at ≤30h        → 死岗 **0** 条，118 alive，2 条渲染不出（百度/海康威视 SPA，未证明是死的）
 *   · enrich_checked_at ≤14d   → 死岗 **5** 条（4.2%）：人保「停止招聘」、恒力石化「职位不存在」、
 *                                 泡泡玛特 / 阅文 / 零跑 均「停止招聘」
 * 直觉解释：`enrich_checked_at` 只说明「我们那天补过正文/探过一次」，中间关掉了没人知道；
 * 而 last_seen_at 新 = 官网列表**昨天还挂着它**。30h 而不是 24h 是给日更 CI 的抖动留余量。
 *
 * ⚠️ 已知边界有两条、方向相反，都靠展示层的异步探活兜底（app/today-popular-client.tsx），
 * 别把本条判据当唯一保险：
 *   ① wt / hotjob 的**列表本身**就夹带已关闭岗（52% / 71%，见 CLAUDE.md「列表夹带已关闭岗」）
 *      → last_seen_at 对这两类源说服力最弱。所幸 `lib/liveness-client.js` 的探活**恰好覆盖**
 *      wt / hotjob（它们有快速 JSON 撤岗信号），两层正好互补。2026-09-06 那一版最终清单里
 *      它们是 0 条，但那是当天的巧合、不是保证。
 *   ② moka 系 SPA 反过来：列表可信，但探活不支持它（要浏览器渲染），靠每日 dead-link-audit 兜。
 *      当天最终 132 条里占 24 条，逐条渲染核过、全活。
 */
const LAST_SEEN_WINDOW = "30 hours";

/**
 * 每家公司最多取几条。**故意不写 ORDER BY**：加了排序 Postgres 就必须把该公司全部匹配行
 * 取出来排一遍，实测 443 家 = 14.2s；不排序则命中即停，同样 414 家只要 243ms。
 * 这里取到的少量行由 JS 侧再排（见 lib/popular-picks.ts）。
 */
const PER_COMPANY = 3;

/**
 * 取「知名公司 + 当前确实挂在官网列表上 + 有 JD 正文」的候选岗。
 * companies 由调用方按必投清单解析成库里的确切公司名（避免 `company ilike any('%x%')` 全表扫）。
 */
export async function fetchPopularCandidates(patterns: string[]): Promise<PopularCandidateRow[]> {
  const names = await resolveActiveCompanyNames(patterns);
  if (!names.length) return [];
  return jobsQuery<PopularCandidateRow>(
    `
    select t.id, t.company, t.title, t.location, t.job_type, t.jd_url, t.posted_at, t.last_seen_at
    from unnest($1::text[]) as c(company)
    cross join lateral (
      select j.id, j.company, j.title, j.location, j.job_type, j.jd_url, j.posted_at, j.last_seen_at
      from jobs j
      where j.company = c.company
        and j.status = 'active'
        and j.job_scope = 'domestic'
        and j.jd_url <> ''
        and char_length(btrim(coalesce(j.summary, ''))) >= 60
        and j.last_seen_at > now() - interval '${LAST_SEEN_WINDOW}'
      limit ${PER_COMPANY}
    ) t
    `,
    [names],
  );
}

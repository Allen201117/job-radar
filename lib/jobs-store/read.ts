// 自建香港 jobs 库的简单读取（非搜索）。供 jobs 页 SSR / companies / saved / applied / career-path 等用。
// 返回的行是 snake_case 列（与 supabase.from("jobs").select("*") 同形），下游 scoring/job-filter 直接吃。
import "server-only";
import { jobsQuery, jobsScalar } from "./client";
import { JOB_COLUMNS } from "./types";
import { appendJobScopeWhere } from "@/lib/job-scope";
import type { UserPreferences } from "@/lib/types";

/** 是否启用自建香港库（配了连接串即用；否则各路由回退 Supabase）。 */
export function jobsStoreEnabled(): boolean {
  return !!process.env.JOBS_DATABASE_URL;
}

/** 「有效在招」计数（首页计数卡：active + 有 JD 正文）。 */
export async function countValidActive(): Promise<number> {
  const n = await jobsScalar<string | number>("select count_valid_active_jobs() as n");
  return Number(n ?? 0);
}

/** 近 24h 内仍被确认在招的岗位数（计数卡「24h 确认在招」；sinceIso 由调用方算好）。 */
export async function countRecentActive(sinceIso: string): Promise<number> {
  const n = await jobsScalar<string | number>(
    "select count(*) as n from jobs where status = 'active' and last_seen_at >= $1",
    [sinceIso],
  );
  return Number(n ?? 0);
}

export type JobsHealthSnapshot = {
  validActive: number;
  todayNew: number;
  todayUpdated: number;
  activeTotal: number;
  thinActive: number;
  expired: number;
  removed: number;
  total: number;
  neverChecked: number;
};

/**
 * 管理员健康面板的 jobs 聚合。
 * 一条 SQL 只返回一行；「有效在招」严格复用 count_valid_active_jobs()，不拉岗位明细到 JS。
 * 今日口径固定为 Asia/Shanghai 当日 00:00。
 */
export async function getJobsHealthSnapshot(): Promise<JobsHealthSnapshot> {
  const rows = await jobsQuery<{
    valid_active: string | number;
    today_new: string | number;
    today_updated: string | number;
    active_total: string | number;
    expired: string | number;
    removed: string | number;
    total: string | number;
    never_checked: string | number;
  }>(`
    with bounds as (
      select date_trunc('day', now() at time zone 'Asia/Shanghai')
        at time zone 'Asia/Shanghai' as today_start
    )
    select
      count_valid_active_jobs() as valid_active,
      count(*) filter (where first_seen_at >= bounds.today_start) as today_new,
      count(*) filter (
        where last_seen_at >= bounds.today_start
          and first_seen_at < bounds.today_start
      ) as today_updated,
      count(*) filter (where status = 'active') as active_total,
      count(*) filter (where status = 'expired') as expired,
      count(*) filter (where status = 'removed') as removed,
      count(*) as total,
      count(*) filter (
        where status = 'active' and enrich_checked_at is null
      ) as never_checked
    from jobs
    cross join bounds
  `);
  const row = rows[0];
  if (!row) {
    throw new Error("jobs health query returned no rows");
  }
  const validActive = Number(row.valid_active || 0);
  const activeTotal = Number(row.active_total || 0);
  const expired = Number(row.expired || 0);
  const removed = Number(row.removed || 0);
  return {
    validActive,
    todayNew: Number(row.today_new || 0),
    todayUpdated: Number(row.today_updated || 0),
    activeTotal,
    thinActive: Math.max(0, activeTotal - validActive),
    expired,
    removed,
    total: Number(row.total || 0),
    neverChecked: Number(row.never_checked || 0),
  };
}

/** 最新 active 一页（jobs 页 SSR 首屏种子 / list 路由）。 */
export async function listLatestActive(
  limit: number,
  offset = 0,
  preferences: UserPreferences | null = null,
  filters: { region?: string | null } = {},
): Promise<any[]> {
  const conds = ["status = 'active'"];
  const params: unknown[] = [];
  appendJobScopeWhere(conds, params, preferences, filters);
  params.push(limit, offset);
  return jobsQuery(
    `select ${JOB_COLUMNS} from jobs where ${conds.join(" and ")} order by first_seen_at desc limit $${params.length - 1} offset $${params.length}`,
    params,
  );
}

/** 岗位库列表用 scoped active 计数；首页统计仍使用 countValidActive() 合并总数。 */
export async function countActiveForScope(
  preferences: UserPreferences | null = null,
  filters: { region?: string | null } = {},
): Promise<number> {
  const conds = ["status = 'active'"];
  const params: unknown[] = [];
  appendJobScopeWhere(conds, params, preferences, filters);
  const n = await jobsScalar<string | number>(
    `select count(*) as n from jobs where ${conds.join(" and ")}`,
    params,
  );
  return Number(n ?? 0);
}

/** 在招公司清单（companies 面板，distinct company）。 */
export async function activeCompanies(): Promise<string[]> {
  const rows = await jobsQuery<{ company: string }>("select company from active_companies()");
  return rows.map((r) => r.company);
}

/** 在招岗位按公司计数（career-path 用）。 */
export async function activeJobCountsByCompany(): Promise<Array<{ company: string; job_count: number }>> {
  return jobsQuery("select company, job_count from active_job_counts_by_company()");
}

/** Today 两段召回：location 命中任一城市 AND title 命中任一职位词，最新优先（无信号时调用方走 listLatestActive）。 */
export async function recallByPrefs(locTerms: string[], titleTerms: string[], limit: number): Promise<any[]> {
  const conds = ["status = 'active'"];
  const params: unknown[] = [];
  if (locTerms.length) {
    const ors = locTerms.map((t) => {
      params.push(`%${t}%`);
      return `location ilike $${params.length}`;
    });
    conds.push(`(${ors.join(" or ")})`);
  }
  if (titleTerms.length) {
    const ors = titleTerms.map((t) => {
      params.push(`%${t}%`);
      return `title ilike $${params.length}`;
    });
    conds.push(`(${ors.join(" or ")})`);
  }
  params.push(limit);
  return jobsQuery(
    `select ${JOB_COLUMNS} from jobs where ${conds.join(" and ")} order by first_seen_at desc limit $${params.length}`,
    params,
  );
}

/** 按 id 批量取岗（saved/applied：job_actions 在 Supabase，岗位在香港库）。 */
export async function jobsByIds(ids: string[], activeOnly = false): Promise<any[]> {
  if (!ids.length) return [];
  return jobsQuery(
    `select ${JOB_COLUMNS} from jobs where id = any($1::uuid[])${activeOnly ? " and status = 'active'" : ""}`,
    [ids],
  );
}

/** 按 jd_url 批量取岗（discovery 缓存/进度回查、enrich 薄卡回查：按产出/薄卡 jd_url 找香港库行）。 */
export async function jobsByUrls(urls: string[], activeOnly = false): Promise<any[]> {
  if (!urls.length) return [];
  return jobsQuery(
    `select ${JOB_COLUMNS} from jobs where jd_url = any($1::text[])${activeOnly ? " and status = 'active'" : ""}`,
    [urls],
  );
}

/** 按 company 批量取 active 岗（insights Tier1 派生：聚合某公司在招岗算事实洞察）。 */
export async function activeJobsByCompanies(companies: string[], limit: number): Promise<any[]> {
  if (!companies.length) return [];
  return jobsQuery(
    `select ${JOB_COLUMNS} from jobs where status = 'active' and company = any($1::text[]) limit $2`,
    [companies, limit],
  );
}

// 自建香港 jobs 库的简单读取（非搜索）。供 jobs 页 SSR / companies / saved / applied / career-path 等用。
// 返回的行是 snake_case 列（与 supabase.from("jobs").select("*") 同形），下游 scoring/job-filter 直接吃。
import "server-only";
import { jobsQuery, jobsScalar } from "./client";
import { JOB_COLUMNS } from "./types";
import { appendJobScopeWhere } from "@/lib/job-scope";
import type { UserPreferences } from "@/lib/types";
import { ilikeMatcher } from "@/lib/ilike-matcher";
import { campusAdmission } from "@/lib/campus-zone";

export { ilikeMatcher } from "@/lib/ilike-matcher";

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

export type MustApplyCoverageRow = {
  name: string;
  activeTotal: number;
  healthy: number;
  new7d: number;
  checked72h: number;
};

export type CompanyActiveAggregate = {
  company: string | null;
  activeTotal: number;
  healthy: number;
  new7d: number;
  checked72h: number;
};

let companyActiveAggregatesCache: { expiresAt: number; value: CompanyActiveAggregate[] } | null = null;
let companyActiveAggregatesInFlight: Promise<CompanyActiveAggregate[]> | null = null;

/**
 * 每家公司只聚合一次，避免必投清单每个 pattern 都扫一遍 active jobs。
 * 短 TTL 与 in-flight 合并只用于降低同一实例的瞬时重复读取，不作为跨请求数据缓存。
 */
export async function getCompanyActiveAggregates(): Promise<CompanyActiveAggregate[]> {
  const now = Date.now();
  if (companyActiveAggregatesCache && companyActiveAggregatesCache.expiresAt > now) {
    return companyActiveAggregatesCache.value;
  }
  if (companyActiveAggregatesInFlight) return companyActiveAggregatesInFlight;
  companyActiveAggregatesInFlight = jobsQuery<{
    company: string | null;
    active_total: string | number;
    healthy: string | number;
    new_7d: string | number;
    checked_72h: string | number;
  }>(`
    select
      company,
      count(*) as active_total,
      count(*) filter (where summary is not null and char_length(btrim(summary)) >= 60) as healthy,
      count(*) filter (where first_seen_at > now() - interval '7 days') as new_7d,
      count(*) filter (where enrich_checked_at > now() - interval '72 hours') as checked_72h
    from jobs
    where status = 'active'
    group by company
  `)
    .then((rows) => rows.map((row) => ({
      company: row.company,
      activeTotal: Number(row.active_total || 0),
      healthy: Number(row.healthy || 0),
      new7d: Number(row.new_7d || 0),
      checked72h: Number(row.checked_72h || 0),
    })))
    .then((value) => {
      companyActiveAggregatesCache = { value, expiresAt: Date.now() + 60_000 };
      return value;
    })
    .finally(() => {
      companyActiveAggregatesInFlight = null;
    });
  return companyActiveAggregatesInFlight;
}

/**
 * 北极星指标：「必投清单健康覆盖」逐家统计（admin 运营看板）。
 * healthy 谓词与 count_valid_active_jobs() 字节级同口径（active + btrim(summary)≥60）。
 * 先聚合公司，再在 Node 内按 ILIKE 语义匹配，避免每条清单都扫描 active jobs。
 */
export async function getMustApplyCoverage(
  list: Array<{ name: string; pattern: string }>,
): Promise<MustApplyCoverageRow[]> {
  const aggregates = await getCompanyActiveAggregates();
  return list.map(({ name, pattern }) => {
    const matches = ilikeMatcher(pattern);
    return aggregates.reduce<MustApplyCoverageRow>((total, company) => {
      if (!company.company || !matches(company.company)) return total;
      total.activeTotal += company.activeTotal;
      total.healthy += company.healthy;
      total.new7d += company.new7d;
      total.checked72h += company.checked72h;
      return total;
    }, { name, activeTotal: 0, healthy: 0, new7d: 0, checked72h: 0 });
  });
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

export type CampusCompanyRow = {
  company: string;          // 必投清单展示名
  pattern: string;
  campusJobs: any[];        // 通过准入门 campus 的在招岗
  internJobs: any[];        // intern 桶
  hasAnyActiveJob: boolean; // 该公司「校招相关粗筛」里有没有岗（判 source_only_social 的输入之一，非严格任意在招）
  lastSeenAtMs: number | null;
};

/**
 * 校招专区：按必投清单公司聚合校招/实习岗。
 * SQL 先按 pattern 粗筛校招相关岗（缩小行数：job_type/title/jd_url 任一命中校招或实习关键词），
 * JS 用 campusAdmission（复用 recruitmentCategory 全量判定逻辑，含 job.experience 硬经验年限门）精筛入桶。
 * 一次 unnest join 覆盖整份清单（~30 家）；行数=这些公司的校招相关岗，实测数百，秒级。
 */
export async function getCampusZone(list: Array<{ name: string; pattern: string }>): Promise<CampusCompanyRow[]> {
  const names = list.map((c) => c.name);
  const pats = list.map((c) => c.pattern);
  const rows = await jobsQuery<any>(
    `
    select t.name as company_key, t.pat,
      j.id, j.company, j.title, j.job_type, j.jd_url, j.apply_url, j.summary,
      j.experience, j.deadline, j.first_seen_at, j.last_seen_at, j.location as city, j.education, j.status
    from unnest($1::text[], $2::text[]) as t(name, pat)
    left join jobs j on j.status = 'active' and j.company ilike t.pat
      and (
        coalesce(j.job_type,'') ~ '校|campus|应届|管培|培训生|graduate|new.?grad|实习|intern'
        or coalesce(j.title,'') ~ '校|应届|届|管培|培训生|graduate|campus|new.?grad|实习|intern'
        or coalesce(j.jd_url,'') ~ '/(xiaozhao|campus|shixi|intern)(/|\\?|$)'
      )
    `,
    [names, pats],
  );
  const byName = new Map<string, CampusCompanyRow>();
  for (const c of list) byName.set(c.name, {
    company: c.name, pattern: c.pattern, campusJobs: [], internJobs: [], hasAnyActiveJob: false, lastSeenAtMs: null,
  });
  for (const r of rows) {
    const agg = byName.get(r.company_key);
    if (!agg || !r.id) continue;
    agg.hasAnyActiveJob = true;
    const seen = r.last_seen_at ? Date.parse(r.last_seen_at) : NaN;
    if (!Number.isNaN(seen)) agg.lastSeenAtMs = Math.max(agg.lastSeenAtMs || 0, seen);
    const bucket = campusAdmission(r);
    if (bucket === "campus") agg.campusJobs.push(r);
    else if (bucket === "intern") agg.internJobs.push(r);
  }
  return list.map((c) => byName.get(c.name)!);
}

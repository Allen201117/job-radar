// 自建香港 jobs 库的简单读取（非搜索）。供 jobs 页 SSR / companies / saved / applied / career-path 等用。
// 返回的行是 snake_case 列（与 supabase.from("jobs").select("*") 同形），下游 scoring/job-filter 直接吃。
import "server-only";
import { jobsQuery, jobsScalar } from "./client";
import { JOB_COLUMNS } from "./types";
import { appendJobScopeWhere } from "@/lib/job-scope";
import type { UserPreferences } from "@/lib/types";
import { ilikeMatcher } from "@/lib/ilike-matcher";
import { campusAdmission, compareCampusJobs } from "@/lib/campus-zone";
import { isCurrentSeasonGradClass } from "@/lib/grad-class";
import { classifyJobFunction } from "@/lib/china-keyword-expansion";
import { mustApplyUnion, type MustApplyCompany } from "@/lib/must-apply-list";

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
  directHealthy: number;
  parentPortalHealthy: number;
  coveredViaParentPortal: boolean;
};

export type CompanyActiveAggregate = {
  company: string | null;
  activeTotal: number;
  healthy: number;
  new7d: number;
  checked72h: number;
  /** 招聘类型拆分——供「校招供给覆盖」度量用（lib/campus-supply-coverage.ts）。
   *  刻意挂在这次已有的全表聚合上：多两个 count filter 不额外扫一遍表。 */
  campusJobs: number;
  internJobs: number;
  socialJobs: number;
  brandRollups: Record<string, ActiveAggregateCounts>;
};

type ActiveAggregateCounts = {
  activeTotal: number;
  healthy: number;
  new7d: number;
  checked72h: number;
};

let companyActiveAggregatesCache: { expiresAt: number; value: CompanyActiveAggregate[] } | null = null;
let companyActiveAggregatesInFlight: Promise<CompanyActiveAggregate[]> | null = null;

type BrandRollupRule = {
  pattern: string;
  parentPattern: string;
  brandTokens: string[];
  alias: string;
};

function brandRollupRules(): BrandRollupRule[] {
  return mustApplyUnion("domestic")
    .filter(
      (company): company is MustApplyCompany & {
        parentPattern: string;
        brandTokens: string[];
      } => Boolean(company.parentPattern && company.brandTokens?.length),
    )
    .map((company, index) => ({
      pattern: company.pattern,
      parentPattern: company.parentPattern,
      brandTokens: company.brandTokens,
      alias: `brand_healthy_${index}`,
    }));
}

/**
 * 品牌 rollup **单独一条查询**，且按**精确公司名**取，不再拼进主聚合。
 *
 * ⚠️ 为什么必须拆开（2026-07-31，live explain analyze）：rollup 每条规则贡献 4 个
 * `count(*) filter (...)`，每个都带 `company ilike '%x%'`（前导 % 用不上索引）。混在主聚合里
 * 意味着**全部 31 万 active 行都要跑 16 个 ilike 表达式** → 该查询 1.1s 涨到 **5.8s**，
 * 而它正是 /admin/health 的关键路径。
 *
 * ⚠️ 为什么用「精确公司名」而不是 `company ilike any(父公司pattern)`：
 * 后者仍要全扫 active（实测 1.04s）；而父公司名字可以直接从**主聚合已经返回的公司清单**里挑出来
 * （实测只有 9 家），再用 `company = any($1)` 走 `jobs_active_company_idx` btree → 实测 **227ms**。
 * 也别想着「两条并行就不用管各自多快」：香港库只有 2 vCPU，实测并行跑两条全扫，
 * 各自从 1.1s 一起涨到 2.1s，总时间一点没省。所以是**串行两条**：1.1s + 0.23s。
 *
 * 结果**逐字节等价**（已用同一 MVCC 快照 live 对拍 1051 家公司，0 差异）：
 * 主聚合里非匹配公司的 rollup 计数本来就全是 0，computeMustApplyCoverage 按 pattern 跨公司求和，
 * 少加一堆 0 不改变结果；每条规则的归属判定仍由 SQL 里原样保留的 ilike 谓词决定，
 * JS 只负责挑「要把哪些公司名送进这条查询」，且用的是与 computeMustApplyCoverage 同一个
 * `ilikeMatcher`（宁可多送几家，也不会漏——多送的公司 rollup 算出来也是 0）。
 */
function brandRollupQuery(rules: BrandRollupRule[], companies: string[]): { sql: string; params: unknown[] } {
  const params: unknown[] = [companies];
  const columns = rules.map((rule) => {
    params.push(rule.parentPattern, rule.pattern, rule.brandTokens.map((token) => `%${token}%`));
    const parentParam = params.length - 2;
    const directParam = params.length - 1;
    const tokensParam = params.length;
    const matchesBrand = `
          company ilike $${parentParam}
          and company not ilike $${directParam}
          and title ilike any($${tokensParam}::text[])`;
    return `
      count(*) filter (
        where ${matchesBrand}
      ) as ${rule.alias}_active,
      count(*) filter (
        where summary is not null
          and char_length(btrim(summary)) >= 60
          and ${matchesBrand}
      ) as ${rule.alias}_healthy,
      count(*) filter (
        where first_seen_at > now() - interval '7 days'
          and ${matchesBrand}
      ) as ${rule.alias}_new_7d,
      count(*) filter (
        where enrich_checked_at > now() - interval '72 hours'
          and ${matchesBrand}
      ) as ${rule.alias}_checked_72h`;
  });
  return {
    sql: `
      select company, ${columns.join(",")}
      from jobs
      where status = 'active' and company = any($1::text[])
      group by company
    `,
    params,
  };
}

/** 主聚合已返回的公司里，挑出可能属于某个父公司门户的（与 computeMustApplyCoverage 同一套 ILIKE 语义）。 */
function parentPortalCompanies(rules: BrandRollupRule[], companies: Array<string | null>): string[] {
  if (!rules.length) return [];
  const matchers = rules.map((rule) => ilikeMatcher(rule.parentPattern));
  const out = new Set<string>();
  for (const company of companies) {
    if (company && matchers.some((matches) => matches(company))) out.add(company);
  }
  return Array.from(out);
}

const EMPTY_ROLLUP: ActiveAggregateCounts = { activeTotal: 0, healthy: 0, new7d: 0, checked72h: 0 };

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
  const rules = brandRollupRules();
  type AggregateRow = {
    company: string | null;
    active_total: string | number;
    healthy: string | number;
    new_7d: string | number;
    checked_72h: string | number;
    campus_jobs: string | number;
    intern_jobs: string | number;
    social_jobs: string | number;
  };
  type RollupRow = { company: string | null; [key: string]: string | number | null };
  // 主聚合先跑；品牌 rollup 用它返回的公司名精确取第二条（不合成一条、也不并行，见 brandRollupQuery 注释）。
  companyActiveAggregatesInFlight = jobsQuery<AggregateRow>(`
      select
        company,
        count(*) as active_total,
        count(*) filter (where summary is not null and char_length(btrim(summary)) >= 60) as healthy,
        count(*) filter (where first_seen_at > now() - interval '7 days') as new_7d,
        count(*) filter (where enrich_checked_at > now() - interval '72 hours') as checked_72h,
        count(*) filter (where recruitment_category = '校招') as campus_jobs,
        count(*) filter (where recruitment_category = '实习') as intern_jobs,
        count(*) filter (where recruitment_category = '社招') as social_jobs
      from jobs
      where status = 'active'
      group by company
    `)
    .then(async (rows) => {
      const portals = parentPortalCompanies(rules, rows.map((row) => row.company));
      const rollup = portals.length ? brandRollupQuery(rules, portals) : null;
      const rollupRows = rollup ? await jobsQuery<RollupRow>(rollup.sql, rollup.params) : ([] as RollupRow[]);
      const rollupByCompany = new Map(rollupRows.map((row) => [row.company, row]));
      return rows.map((row) => {
        const hit = rollupByCompany.get(row.company);
        return {
          company: row.company,
          activeTotal: Number(row.active_total || 0),
          healthy: Number(row.healthy || 0),
          new7d: Number(row.new_7d || 0),
          checked72h: Number(row.checked_72h || 0),
          campusJobs: Number(row.campus_jobs || 0),
          internJobs: Number(row.intern_jobs || 0),
          socialJobs: Number(row.social_jobs || 0),
          brandRollups: Object.fromEntries(
            rules.map((rule) => [rule.pattern, hit
              ? {
                activeTotal: Number(hit[`${rule.alias}_active`] || 0),
                healthy: Number(hit[`${rule.alias}_healthy`] || 0),
                new7d: Number(hit[`${rule.alias}_new_7d`] || 0),
                checked72h: Number(hit[`${rule.alias}_checked_72h`] || 0),
              }
              : EMPTY_ROLLUP]),
          ),
        };
      });
    })
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
  list: MustApplyCompany[],
): Promise<MustApplyCoverageRow[]> {
  const aggregates = await getCompanyActiveAggregates();
  return computeMustApplyCoverage(list, aggregates);
}

/**
 * 必投清单每家的「校招供给」原料（分类判定见 lib/campus-supply-coverage.ts）。
 * 复用 getCompanyActiveAggregates 那一次全表聚合 —— 不额外扫表。
 * `hasCampusSource` 由调用方从 sources 侧带入（jobs 库里没有源信息）。
 */
export async function getCampusSupplyInputs(
  list: MustApplyCompany[],
): Promise<Array<{ company: string; campusJobs: number; internJobs: number; socialJobs: number }>> {
  const aggregates = await getCompanyActiveAggregates();
  return list.map(({ name, pattern }) => {
    const matches = ilikeMatcher(pattern);
    return aggregates.reduce(
      (total, c) => {
        if (!c.company || !matches(c.company)) return total;
        total.campusJobs += c.campusJobs;
        total.internJobs += c.internJobs;
        total.socialJobs += c.socialJobs;
        return total;
      },
      { company: name, campusJobs: 0, internJobs: 0, socialJobs: 0 },
    );
  });
}

export function computeMustApplyCoverage(
  list: MustApplyCompany[],
  aggregates: CompanyActiveAggregate[],
): MustApplyCoverageRow[] {
  return list.map(({ name, pattern, parentPattern, brandTokens }) => {
    const matches = ilikeMatcher(pattern);
    const direct = aggregates.reduce<Omit<
      MustApplyCoverageRow,
      "directHealthy" | "parentPortalHealthy" | "coveredViaParentPortal"
    >>((total, company) => {
      if (!company.company || !matches(company.company)) return total;
      total.activeTotal += company.activeTotal;
      total.healthy += company.healthy;
      total.new7d += company.new7d;
      total.checked72h += company.checked72h;
      return total;
    }, { name, activeTotal: 0, healthy: 0, new7d: 0, checked72h: 0 });
    const parentRollup = parentPattern && brandTokens?.length
      ? aggregates.reduce<ActiveAggregateCounts>((sum, company) => {
        const rollup = company.brandRollups?.[pattern];
        if (!rollup) return sum;
        sum.activeTotal += rollup.activeTotal;
        sum.healthy += rollup.healthy;
        sum.new7d += rollup.new7d;
        sum.checked72h += rollup.checked72h;
        return sum;
      }, { activeTotal: 0, healthy: 0, new7d: 0, checked72h: 0 })
      : { activeTotal: 0, healthy: 0, new7d: 0, checked72h: 0 };
    const acceptedParent = parentRollup.healthy >= 3
      ? parentRollup
      : { activeTotal: 0, healthy: 0, new7d: 0, checked72h: 0 };
    const parentPortalHealthy = acceptedParent.healthy;
    return {
      ...direct,
      activeTotal: direct.activeTotal + acceptedParent.activeTotal,
      healthy: direct.healthy + parentPortalHealthy,
      new7d: direct.new7d + acceptedParent.new7d,
      checked72h: direct.checked72h + acceptedParent.checked72h,
      directHealthy: direct.healthy,
      parentPortalHealthy,
      coveredViaParentPortal: parentPortalHealthy > 0,
    };
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
  pastClassJobCount: number; // 明确标了往届（如秋招期库里没下架干净的 2026 届）而被移出列表的岗数，供卡面诚实说明
};

/** 校招专区粗筛条件：job_type / title / jd_url 任一命中校招或实习关键词。
 *  getCampusZone（全清单聚合）与 getCampusCompanyJobs（展开单家取完整行）共用同一份，
 *  两边口径必须逐字一致——否则卡面计数与展开区列表会对不上。 */
const CAMPUS_PREFILTER_SQL = `(
          coalesce(j.job_type,'') ~* '校|campus|应届|管培|培训生|graduate|new.?grad|实习|intern'
          or coalesce(j.title,'') ~* '校|应届|届|管培|培训生|graduate|campus|new.?grad|实习|intern'
          or coalesce(j.jd_url,'') ~* '/(xiaozhao|campus|shixi|intern)(/|\\?|$)'
        )`;

/**
 * 把必投清单的 `%关键词%` pattern 解析成库里**确切的** company 取值。
 *
 * 为什么多这一跳：`company ilike any($1)` 带前导 % 用不了任何 btree 索引 → 规划器只能对
 * 39 万 active 行做并行全表扫（live EXPLAIN：Execution 2567ms / 127,726 buffers）。
 * 先用 `jobs_active_company_idx` 走 Index Only Scan 拿到全部 1467 个 active 公司名（384ms），
 * 在 JS 里按同样的「不区分大小写子串」语义筛出命中的确切名字，主查询就能改成
 * `company = any($1::text[])` 走 Bitmap Index Scan（live EXPLAIN：957ms / 46,413 buffers）。
 * 合计 1.34s vs 2.57s，且**结果集逐行相同**（live 对拍两侧都是 16,494 行）。
 *
 * 语义等价性：SQL 的 `ilike '%x%'` = 不区分大小写子串，与这里的 toLowerCase().includes 同义；
 * 候选集来自 `status='active'`，与主查询的 status 条件一致，所以不会漏。
 */
// 全部 active 公司名的短 TTL 缓存：这份清单 live 只有 1467 行、且只在新源入库时才变，
// 但每次校招看板刷新 / 每次展开一家公司都要用它，不缓存就是每次白付 ~384ms。
let activeCompanyNamesCache: { expiresAt: number; value: string[] } | null = null;
let activeCompanyNamesInFlight: Promise<string[]> | null = null;

async function allActiveCompanyNames(): Promise<string[]> {
  const now = Date.now();
  if (activeCompanyNamesCache && activeCompanyNamesCache.expiresAt > now) {
    return activeCompanyNamesCache.value;
  }
  if (activeCompanyNamesInFlight) return activeCompanyNamesInFlight;
  activeCompanyNamesInFlight = (async () => {
    const rows = await jobsQuery<{ company: string | null }>(
      "select distinct company from jobs where status = 'active'",
    );
    return rows.map((r) => r.company).filter((c): c is string => !!c);
  })();
  try {
    const value = await activeCompanyNamesInFlight;
    activeCompanyNamesCache = { expiresAt: Date.now() + 5 * 60_000, value };
    return value;
  } finally {
    activeCompanyNamesInFlight = null;
  }
}

async function resolveActiveCompanyNames(patterns: string[]): Promise<string[]> {
  const needles = patterns
    .map((p) => p.replace(/%/g, "").toLowerCase())
    .filter(Boolean);
  if (!needles.length) return [];
  const all = await allActiveCompanyNames();
  return all.filter((c) => {
    const lower = c.toLowerCase();
    return needles.some((n) => lower.includes(n));
  });
}

/**
 * 校招专区：按必投清单公司聚合校招/实习岗。
 * SQL 先按公司 + 校招关键词粗筛（见 resolveActiveCompanyNames / CAMPUS_PREFILTER_SQL），
 * JS 用 campusAdmission（复用 recruitmentCategory 全量判定逻辑，含 job.experience 硬经验年限门）精筛入桶。
 * 公司归属在 JS 端按 pattern 子串匹配回填（见下方 for 循环）。短 TTL 缓存降同实例重复读取；
 * 跨请求复用由调用方（app/campus/page.tsx 的 unstable_cache）负责。
 */
export type CampusZoneCacheEntry = { expiresAt: number; value: CampusCompanyRow[] };
const campusZoneCache = new Map<string, CampusZoneCacheEntry>();
const campusZoneInFlight = new Map<string, Promise<CampusCompanyRow[]>>();

/**
 * 短 TTL 与 in-flight 合并只用于降低同一实例的瞬时重复读取，不作为跨请求数据缓存。
 * cache key 用排序后的 pattern 数组拼接，不同行业组（不同必投清单）各自独立缓存、互不串号。
 */
export async function getCampusZone(list: Array<{ name: string; pattern: string }>): Promise<CampusCompanyRow[]> {
  const pats = list.map((c) => c.pattern);
  const cacheKey = [...pats].sort().join("");
  const now = Date.now();
  const cached = campusZoneCache.get(cacheKey);
  if (cached && cached.expiresAt > now) return cached.value;
  const inFlight = campusZoneInFlight.get(cacheKey);
  if (inFlight) return inFlight;

  const promise = (async () => {
    const names = await resolveActiveCompanyNames(pats);
    const rows = names.length
      ? await jobsQuery<any>(
          `
      select
        j.id, j.company, j.title, j.job_type, j.jd_url, j.apply_url, j.summary,
        j.experience, j.deadline, j.first_seen_at, j.last_seen_at, j.location as city, j.education, j.status,
        j.grad_class
      from jobs j
      where j.status = 'active'
        and j.company = any($1::text[])
        and ${CAMPUS_PREFILTER_SQL}
      `,
          [names],
        )
      : [];
    const byName = new Map<string, CampusCompanyRow>();
    for (const c of list) byName.set(c.name, {
      company: c.name, pattern: c.pattern, campusJobs: [], internJobs: [], hasAnyActiveJob: false, lastSeenAtMs: null,
      pastClassJobCount: 0,
    });
    for (const r of rows) {
      if (!r.id || !r.company) continue;
      const companyLower = String(r.company).toLowerCase();
      // 归属取第一个 needle 命中的公司；必投 pattern 是人工策展的互异公司名（如 %字节% %腾讯%），
      // 子串重叠概率极低。注意：这与重构前 SQL unnest 交叉 join「一岗可归多家」的语义不同（现在只归一家）。
      const owner = list.find((c) => companyLower.includes(c.pattern.replace(/%/g, "").toLowerCase()));
      if (!owner) continue;
      const agg = byName.get(owner.name);
      if (!agg) continue;
      agg.hasAnyActiveJob = true;
      const seen = r.last_seen_at ? Date.parse(r.last_seen_at) : NaN;
      if (!Number.isNaN(seen)) agg.lastSeenAtMs = Math.max(agg.lastSeenAtMs || 0, seen);
      const bucket = campusAdmission(r);
      if (bucket === "reject") continue;
      // 往届岗（明确标了比当季更早的届别，如秋招开闸期库里没下架干净的 2026 届）不进默认列表——
      // 校招用户投一个往届岗就白费一轮。届别未知（绝大多数岗）照常展示，留白不等于隐藏。
      // 不静默丢弃：计数留给卡面说明「另有 N 个往届岗」，避免用户以为我们漏抓。
      if (!isCurrentSeasonGradClass(r.grad_class)) {
        agg.pastClassJobCount += 1;
        continue;
      }
      if (bucket === "campus") agg.campusJobs.push(r);
      else agg.internJobs.push(r);
    }
    return list.map((c) => byName.get(c.name)!);
  })();

  campusZoneInFlight.set(cacheKey, promise);
  try {
    const value = await promise;
    campusZoneCache.set(cacheKey, { expiresAt: Date.now() + 60_000, value });
    return value;
  } finally {
    campusZoneInFlight.delete(cacheKey);
  }
}

/**
 * 校招专区「展开某家公司」时按需取该公司当前桶的完整岗位行。
 *
 * 页面本身只下发筛选/计数用的**聚合分面**（见 app/campus/page.tsx），一行岗位都不下发，
 * 所以展开时必须回库取。与 getCampusZone 共用同一套判定，逐条对齐：
 *   · 同一份粗筛 SQL（CAMPUS_PREFILTER_SQL）
 *   · 同一条归属规则（list 里第一个 pattern 命中者得，`腾讯音乐 TME` 归 %腾讯音乐% 不归 %腾讯%）
 *   · 同一道准入门（campusAdmission + isCurrentSeasonGradClass）
 * 任一处漂移都会让卡面计数与展开列表对不上，改动务必两边同步。
 *
 * `fn` 由服务端用**完整 summary** 算好随行返回：客户端拿它做职能筛选，与分面里的职能标签
 * 同源同值，不必在浏览器里重跑分类器、也不会两处算出不同结果。
 *
 * ⚡ 为什么分两段取：准入门 campusAdmission 要看 JD 正文，所以「哪些岗算这个桶的」离不开正文；
 * 但**排序键（deadline / first_seen_at）和归属键（company）都是轻字段**。于是先只取轻字段把
 * 全公司的岗排好序，再顺着这个顺序**分批**取完整行（含正文）跑准入门，够 limit 条就停。
 * 字节这种大厂一个桶 5,524 个岗、粗筛命中 8,100 行，一次性拉完整行是 ~8 MB / live 实测 5.8s；
 * 分批后通常一两批（500~1000 行）就够，其余正文根本不取。
 * 语义与「全取回来再排序截断」**完全一致**：排序在取正文之前就已定好，顺序靠前的先判，
 * 收满 200 条时后面的岗不可能挤进前 200。最坏情况（该桶的岗全排在最后）退化成旧行为，不会更差。
 */
export type CampusCompanyJobs = { jobs: any[]; scanned: number };

/** 每批取多少条完整行。够大以求一批命中，又不至于为 200 条结果拉回上千条正文。 */
const CAMPUS_DETAIL_CHUNK = 500;

export async function getCampusCompanyJobs(
  list: Array<{ name: string; pattern: string }>,
  pattern: string,
  bucket: "campus" | "intern",
  limit: number,
): Promise<CampusCompanyJobs> {
  const target = list.find((c) => c.pattern === pattern);
  if (!target) return { jobs: [], scanned: 0 };
  const names = await resolveActiveCompanyNames([pattern]);
  if (!names.length) return { jobs: [], scanned: 0 };

  // 第一段：只取轻字段（不含 summary），足够做归属 + 届别门 + 排序。
  const light = await jobsQuery<any>(
    `
    select j.id, j.company, j.grad_class, j.deadline, j.first_seen_at
    from jobs j
    where j.status = 'active'
      and j.company = any($1::text[])
      and ${CAMPUS_PREFILTER_SQL}
    `,
    [names],
  );
  const candidates: any[] = [];
  for (const r of light) {
    if (!r.id || !r.company) continue;
    const companyLower = String(r.company).toLowerCase();
    // 归属规则与 getCampusZone 逐字一致：list 里第一个 pattern 命中者得。
    const owner = list.find((c) => companyLower.includes(c.pattern.replace(/%/g, "").toLowerCase()));
    if (!owner || owner.pattern !== target.pattern) continue;
    // 届别门只看 grad_class，轻字段就能判，先剪枝再取正文。
    if (!isCurrentSeasonGradClass(r.grad_class)) continue;
    candidates.push(r);
  }
  // 临近截止优先、其次新增降序 —— 与全量排序结果相同（这两个键都在轻字段里）。
  candidates.sort(compareCampusJobs);

  // 第二段：顺着排好的顺序分批取完整行跑准入门，收满 limit 就不再往下取。
  const kept: any[] = [];
  let scanned = 0;
  for (let i = 0; i < candidates.length && kept.length < limit; i += CAMPUS_DETAIL_CHUNK) {
    const ids = candidates.slice(i, i + CAMPUS_DETAIL_CHUNK).map((r) => r.id);
    const rows = await jobsQuery<any>(
      `select ${JOB_COLUMNS}, j.location as city from jobs j where j.id = any($1::uuid[])`,
      [ids],
    );
    scanned += ids.length;
    const byId = new Map(rows.map((r: any) => [r.id, r]));
    // 按本批在候选序列里的顺序处理，保证「先来的先占名额」与全量排序一致。
    for (const c of candidates.slice(i, i + CAMPUS_DETAIL_CHUNK)) {
      if (kept.length >= limit) break;
      const full = byId.get(c.id);
      if (!full) continue;
      if (campusAdmission(full) !== bucket) continue;
      kept.push({ ...full, fn: classifyJobFunction(full) });
    }
  }
  return { jobs: kept, scanned };
}

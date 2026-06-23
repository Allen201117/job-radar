// 个人机会雷达候选召回（§6.3）。返回「可能匹配的超集」，由 Opportunity Engine（eligibility/scoring）精筛。
// 召回集合 = 三查询并集（按 id 去重）：① role+keyword 的 FTS OR；② 目标公司（≤30，子串）；③ 目标城市（≤10）+ 近7天新增。
// 共同窗口：status=active、last_seen_at≥now-7d、summary 去空白≥60。超过 limit 按 first_seen desc 截断并标 capped。
// gated：配了 JOBS_DATABASE_URL 用香港 pg，否则回退 Supabase（本地/回滚；prod 该表已空）。形状一致（snake_case 行）。
import "server-only";
import { jobsQuery } from "./client";
import { jobsStoreEnabled } from "./read";
import { JOB_COLUMNS } from "./types";
import { buildTsquery } from "@/lib/job-search";
import { ftsCandidateTerms, normalizeChinaCity } from "@/lib/china-keyword-expansion";
import type { RadarProfile } from "@/lib/opportunities/types";

type SupabaseLike = { from: (table: string) => any };

export interface RecallResult {
  jobs: any[];
  capped: boolean;
}

const SEVEN_DAYS_MS = 7 * 86_400_000;
const MIN_SUMMARY = 60;

function roleQueryTsquery(profile: RadarProfile): string | null {
  const terms = [...profile.targetRoles, ...profile.targetKeywords];
  if (!terms.length) return null;
  const ftsTerms = terms.flatMap((t) => ftsCandidateTerms(t));
  return buildTsquery(ftsTerms, []); // 组内 OR：命中任一目标词即召回
}

function cityPatterns(profile: RadarProfile): string[] {
  const out = new Set<string>();
  for (const c of profile.targetLocations.slice(0, 10)) {
    if (c) out.add(`%${c}%`);
    const n = normalizeChinaCity(c);
    if (n && n !== c) out.add(`%${n}%`);
  }
  return Array.from(out);
}

function companyPatterns(profile: RadarProfile): string[] {
  return profile.targetCompanies.slice(0, 30).map((c) => `%${c}%`);
}

function mergeById(target: Map<string, any>, rows: any[] | null | undefined): void {
  for (const r of rows || []) {
    if (r && r.id != null && !target.has(r.id)) target.set(r.id, r);
  }
}

function finalize(byId: Map<string, any>, limit: number): RecallResult {
  const jobs = Array.from(byId.values()).sort((a, b) =>
    String(b.first_seen_at || "").localeCompare(String(a.first_seen_at || "")),
  );
  return { jobs: jobs.slice(0, limit), capped: jobs.length > limit };
}

// ---- 香港 pg 路径 ----
async function recallViaStore(profile: RadarProfile, sinceIso: string, limit: number): Promise<RecallResult> {
  const byId = new Map<string, any>();
  const COMMON = `status = 'active' and last_seen_at >= $1 and char_length(btrim(coalesce(summary, ''))) >= ${MIN_SUMMARY}`;

  const tsquery = roleQueryTsquery(profile);
  if (tsquery) {
    mergeById(
      byId,
      await jobsQuery(
        `select ${JOB_COLUMNS} from jobs where ${COMMON} and search_doc @@ to_tsquery('simple', $2) order by first_seen_at desc limit $3`,
        [sinceIso, tsquery, limit],
      ),
    );
  }

  const companies = companyPatterns(profile);
  if (companies.length) {
    mergeById(
      byId,
      await jobsQuery(
        `select ${JOB_COLUMNS} from jobs where ${COMMON} and company ilike any($2::text[]) order by first_seen_at desc limit $3`,
        [sinceIso, companies, limit],
      ),
    );
  }

  const cities = cityPatterns(profile);
  if (cities.length) {
    mergeById(
      byId,
      await jobsQuery(
        `select ${JOB_COLUMNS} from jobs where ${COMMON} and location ilike any($2::text[]) and first_seen_at >= $1 order by first_seen_at desc limit $3`,
        [sinceIso, cities, limit],
      ),
    );
  }

  return finalize(byId, limit);
}

// ---- Supabase 回退（本地/回滚；prod jobs 表已空）----
async function recallViaSupabase(
  profile: RadarProfile,
  sinceIso: string,
  supabase: SupabaseLike,
  limit: number,
): Promise<RecallResult> {
  const byId = new Map<string, any>();
  const summaryOk = (j: any) => String(j?.summary || "").trim().length >= MIN_SUMMARY;

  const tsquery = roleQueryTsquery(profile);
  if (tsquery) {
    const { data } = await supabase
      .from("jobs")
      .select("*")
      .eq("status", "active")
      .gte("last_seen_at", sinceIso)
      .textSearch("search_doc", tsquery, { config: "simple" })
      .limit(limit);
    mergeById(byId, (data || []).filter(summaryOk));
  }

  const companies = profile.targetCompanies.slice(0, 30);
  if (companies.length) {
    const { data } = await supabase
      .from("jobs")
      .select("*")
      .eq("status", "active")
      .gte("last_seen_at", sinceIso)
      .or(companies.map((c) => `company.ilike.%${c}%`).join(","))
      .limit(limit);
    mergeById(byId, (data || []).filter(summaryOk));
  }

  const cities = profile.targetLocations.slice(0, 10);
  if (cities.length) {
    const ors: string[] = [];
    for (const c of cities) {
      ors.push(`location.ilike.%${c}%`);
      const n = normalizeChinaCity(c);
      if (n && n !== c) ors.push(`location.ilike.%${n}%`);
    }
    const { data } = await supabase
      .from("jobs")
      .select("*")
      .eq("status", "active")
      .gte("last_seen_at", sinceIso)
      .gte("first_seen_at", sinceIso)
      .or(ors.join(","))
      .limit(limit);
    mergeById(byId, (data || []).filter(summaryOk));
  }

  return finalize(byId, limit);
}

export async function recallOpportunityCandidates(
  profile: RadarProfile,
  now: Date,
  supabaseFallback: SupabaseLike | null,
  limit = 4000,
): Promise<RecallResult> {
  const sinceIso = new Date(now.getTime() - SEVEN_DAYS_MS).toISOString();
  if (jobsStoreEnabled()) {
    return recallViaStore(profile, sinceIso, limit);
  }
  if (supabaseFallback) {
    return recallViaSupabase(profile, sinceIso, supabaseFallback, limit);
  }
  return { jobs: [], capped: false };
}

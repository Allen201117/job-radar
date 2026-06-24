// 个人机会雷达候选召回（§6.3 + P0-1 性能修复）。返回「可能匹配的超集」，由引擎精筛。
//
// P0-1 实测根因：plan 很快（EXPLAIN 22–188ms），慢在**把数千行的完整 summary 文本跨区传输**（FTS 分支
// 取 4000 行 × full summary × 3 分支 → 实测整页 >30s）。修法（不抬 timeout、不降 4000 cap、不加 first_seen 硬窗）：
//   ① recall 只回**截断 summary**（left 500）+ 排除词在 SQL 应用 → 单行载荷砍数倍；展示的 ≤约33 张卡由 service 再回填完整 summary。
//   ② 三类召回**并行**（Promise.all），城市/公司都走 **search_doc GIN**（location/company 已在 search_doc 内），不再 ILIKE 全表扫。
//   ③ 保留 order by first_seen desc（实测 plan 仍走 GIN+sort，31ms）+ limit 4000，按 id 去重、candidate_capped 诚实。
// companyHit 的权威判定用 normalizeCompany() exact（见 eligibility.ts），此处公司分支只做超集召回。
import "server-only";
import { jobsQuery } from "./client";
import { jobsStoreEnabled } from "./read";
import { buildTsquery } from "@/lib/job-search";
import { ftsCandidateTerms } from "@/lib/china-keyword-expansion";
import type { RadarProfile } from "@/lib/opportunities/types";

type SupabaseLike = { from: (table: string) => any };

export interface RecallResult {
  jobs: any[];
  capped: boolean;
}

const SEVEN_DAYS_MS = 7 * 86_400_000;
const SUMMARY_TRUNC = 500;
const BRANCH_LIMIT = 4000;

// recall 列：summary 截断为 ≤500 字，砍跨区传输；展示卡由 service 回填完整 summary。
// 只取硬门 + 打分必需列 + 截断 summary：把 4000 行候选的跨区载荷压到最小（P0-1）。
// apply_url/posted_at/experience/deadline/content_hash/... 等展示字段不在此，由 service 对最终少量入选卡片回填完整行。
// enrich_checked_at 是分层核验 SLA（today 24h 硬门）的判定输入，必须随召回带回（单 timestamptz，载荷可忽略）。
const RECALL_COLUMNS =
  "id, source_id, company, title, location, job_type, " +
  `left(btrim(summary), ${SUMMARY_TRUNC}) as summary, ` +
  "jd_url, salary_text, first_seen_at, last_seen_at, enrich_checked_at, status, education";

function roleTsquery(profile: RadarProfile): string | null {
  const terms = [...profile.targetRoles, ...profile.targetKeywords];
  if (!terms.length) return null;
  return buildTsquery(terms.flatMap((t) => ftsCandidateTerms(t)), []);
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

// ---- 香港 pg 路径：三分支均走 search_doc GIN，并行 ----
function excludePatterns(profile: RadarProfile): string[] {
  return profile.excludeKeywords
    .map((k) => String(k || "").trim().toLowerCase())
    .filter(Boolean)
    .map((k) => `%${k}%`);
}

// 三类召回（role/keyword、目标公司、城市近7天）合并成**一条** SQL：三个 search_doc @@ 用 OR，
// 走同一 GIN 索引的 BitmapOr → 单连接、单次跨区往返。
// P0-1 复验真因 = 连接/跨区往返开销（服务端 plan 4ms、110 行仍 22s 并连接超时），不是 plan 也不是行数；
// 3 个并行分支 = serverless 冷池下最多 3 次 SSL 握手 → 合并为 1 连接最稳。不抬 timeout、不降 cap、不加无关硬窗。
async function recallViaStore(profile: RadarProfile, sinceIso: string, limit: number): Promise<RecallResult> {
  const excl = excludePatterns(profile);
  const roleTs = roleTsquery(profile);
  const companyTs = profile.targetCompanies.length
    ? buildTsquery(profile.targetCompanies.slice(0, 30), [])
    : null;
  const cityTs = profile.targetLocations.length
    ? buildTsquery(profile.targetLocations.slice(0, 10), [])
    : null;

  const params: unknown[] = [sinceIso];
  let where = `status = 'active' and last_seen_at >= $1 and summary is not null and char_length(btrim(summary)) >= 60`;
  if (excl.length) {
    params.push(excl);
    // 排除词用完整 summary 比对（不受 left 截断影响），逐字对齐 crawler jobExcluded 的字段集
    where += ` and not (lower(concat_ws(' ', title, company, location, job_type, summary, salary_text)) like any($${params.length}::text[]))`;
  }

  const ors: string[] = [];
  if (roleTs) {
    params.push(roleTs);
    ors.push(`search_doc @@ to_tsquery('simple', $${params.length})`);
  }
  if (companyTs) {
    params.push(companyTs);
    ors.push(`search_doc @@ to_tsquery('simple', $${params.length})`);
  }
  if (cityTs) {
    params.push(cityTs);
    // 城市分支额外要求「近 7 天新增」（first_seen_at >= sinceIso，复用 $1）
    ors.push(`(search_doc @@ to_tsquery('simple', $${params.length}) and first_seen_at >= $1)`);
  }
  if (ors.length === 0) return { jobs: [], capped: false }; // profile_ready 应保证至少一项；防御性返回
  where += ` and (${ors.join(" or ")})`;

  params.push(limit);
  const sql = `select ${RECALL_COLUMNS} from jobs where ${where} order by first_seen_at desc limit $${params.length}`;
  const rows = await jobsQuery(sql, params);
  // 命中 limit = 发生截断 → capped 诚实为 true（修 P0-6：旧逻辑用「去重后数量 > limit」，恰好截断到 limit 时误判 false）
  return { jobs: rows, capped: rows.length >= limit };
}

// ---- Supabase 回退（本地/回滚；prod jobs 表已空，非性能关键路径）----
async function recallViaSupabase(
  profile: RadarProfile,
  sinceIso: string,
  supabase: SupabaseLike,
  limit: number,
): Promise<RecallResult> {
  const byId = new Map<string, any>();
  let branchCapped = false;
  const summaryOk = (j: any) => String(j?.summary || "").trim().length >= 60;
  const take = (data: any[] | null | undefined) => {
    const rows = data || [];
    if (rows.length >= limit) branchCapped = true; // 分支命中 limit = 截断
    mergeById(byId, rows.filter(summaryOk));
  };

  const roleTs = roleTsquery(profile);
  if (roleTs) {
    const { data } = await supabase
      .from("jobs")
      .select("*")
      .eq("status", "active")
      .gte("last_seen_at", sinceIso)
      .textSearch("search_doc", roleTs, { config: "simple" })
      .limit(limit);
    take(data);
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
    take(data);
  }
  const cityTs = profile.targetLocations.length
    ? buildTsquery(profile.targetLocations.slice(0, 10), [])
    : null;
  if (cityTs) {
    const { data } = await supabase
      .from("jobs")
      .select("*")
      .eq("status", "active")
      .gte("last_seen_at", sinceIso)
      .gte("first_seen_at", sinceIso)
      .textSearch("search_doc", cityTs, { config: "simple" })
      .limit(limit);
    take(data);
  }
  const r = finalize(byId, limit);
  return { jobs: r.jobs, capped: branchCapped || r.capped };
}

export async function recallOpportunityCandidates(
  profile: RadarProfile,
  now: Date,
  supabaseFallback: SupabaseLike | null,
  limit = BRANCH_LIMIT,
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

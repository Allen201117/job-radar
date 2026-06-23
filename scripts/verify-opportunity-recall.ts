// 只读性能验证：用真实 JOBS_DATABASE_URL + 固定画像，量「机会召回」三分支与合并的耗时。
// 跑：JOBS_DATABASE_URL 已在环境（set -a; source .env.local; set +a）后 `npx tsx scripts/verify-opportunity-recall.ts`
// 不打印连接串/密码。复刻 lib/jobs-store/opportunities.ts 的召回 SQL（截断 summary + GIN + 并行 + order by + cap 4000），
// 量真实往返（含行传输）——这是 EXPLAIN 测不到、却是 P0-1 真正瓶颈的部分。
import { Pool } from "pg";
// china-keyword-expansion 为 CommonJS（.js），含 ftsCandidateTerms。
import { ftsCandidateTerms } from "../lib/china-keyword-expansion";

// —— 复刻 lib/job-search.ts 的 buildTsquery（中文 bigram / 英文整词，组内 OR）——
function queryTokens(term: string): string[] {
  const out: string[] = [];
  for (const tok of String(term || "").toLowerCase().split(/\s+/)) {
    if (!tok) continue;
    if (/^[a-z0-9]+$/.test(tok)) { out.push(tok); continue; }
    if (tok.length === 1) { if (/^[㐀-䶿一-鿿]$/.test(tok)) out.push(tok); continue; }
    for (let i = 0; i < tok.length - 1; i++) { const bg = tok.slice(i, i + 2); if (/^[a-z0-9㐀-䶿一-鿿]{2}$/.test(bg)) out.push(bg); }
  }
  return out;
}
function termClause(term: string): string | null { const t = queryTokens(term); return t.length ? `(${t.join(" & ")})` : null; }
function buildTsquery(kw: string[], andT: string[]): string | null {
  const c: string[] = [];
  const k = kw.map(termClause).filter((x): x is string => !!x);
  if (k.length) c.push(`(${k.join(" | ")})`);
  for (const t of andT) { const x = termClause(t); if (x) c.push(x); }
  return c.length ? c.join(" & ") : null;
}

const PROFILE = {
  targetRoles: ["算法"],
  targetKeywords: [] as string[],
  targetLocations: ["上海"],
  targetCompanies: ["字节跳动", "示例新公司XYZ"],
};
const SUMMARY_TRUNC = 500;
const COLS =
  `id, source_id, company, title, location, job_type, left(btrim(summary), ${SUMMARY_TRUNC}) as summary, ` +
  "jd_url, apply_url, salary_text, posted_at, first_seen_at, last_seen_at, status, content_hash, created_at, " +
  "experience, education, deadline, enrich_fail_count, enrich_checked_at, canonical_jd_url";

function branchSql(recentToo: boolean): string {
  let where = "status='active' and last_seen_at >= now() - interval '7 days' and summary is not null and char_length(btrim(summary)) >= 60 and search_doc @@ to_tsquery('simple', $1)";
  if (recentToo) where += " and first_seen_at >= now() - interval '7 days'";
  return `select ${COLS} from jobs where ${where} order by first_seen_at desc limit 4000`;
}

async function main() {
  const url = process.env.JOBS_DATABASE_URL;
  if (!url) { console.error("JOBS_DATABASE_URL 未配置"); process.exit(2); }
  const u = new URL(url);
  const pool = new Pool({
    host: u.hostname, port: u.port ? Number(u.port) : 5432,
    user: decodeURIComponent(u.username), password: decodeURIComponent(u.password),
    database: u.pathname.replace(/^\//, "") || "jobradar_jobs",
    ssl: { rejectUnauthorized: false }, max: 5, connectionTimeoutMillis: 12_000, statement_timeout: 15_000,
  });
  pool.on("error", (e) => console.warn("[pool] idle error:", e.message));

  const roleTs = buildTsquery(ftsCandidateTerms("算法"), []);
  const cityTs = buildTsquery(PROFILE.targetLocations, []);
  const companyTs = buildTsquery(PROFILE.targetCompanies, []);

  const run = async (label: string, sql: string, ts: string) => {
    const t0 = Date.now();
    const r = await pool.query(sql, [ts]);
    const ms = Date.now() - t0;
    console.log(`  ${label.padEnd(10)} ${String(ms).padStart(6)}ms  rows=${r.rowCount}`);
    return { ms, rows: r.rows };
  };

  try {
    console.log("画像：算法 / 上海 / 字节跳动+示例新公司XYZ / 互联网 / daily 5");
    console.log(`roleTs ${roleTs ? roleTs.length : 0} 字符\n分支耗时（含行传输）：`);
    const t0 = Date.now();
    const [role, company, city] = await Promise.all([
      run("role", branchSql(false), roleTs!),
      run("company", branchSql(false), companyTs!),
      run("city", branchSql(true), cityTs!),
    ]);
    const recallMs = Date.now() - t0;
    const byId = new Map<string, any>();
    for (const set of [role.rows, company.rows, city.rows]) for (const r of set) if (!byId.has(r.id)) byId.set(r.id, r);
    const merged = byId.size;
    const capped = merged > 4000;
    const slowest = Math.max(role.ms, company.ms, city.ms);

    console.log(`\n合并候选：${Math.min(merged, 4000)}（去重前 ${merged}，candidate_capped=${capped}）`);
    console.log(`并行 recall 总耗时：${recallMs}ms`);
    console.log("\n门槛检查：");
    console.log(`  单条 ≤2500ms：${slowest <= 2500 ? "PASS" : "FAIL"}（最慢 ${slowest}ms）`);
    console.log(`  recall ≤5000ms：${recallMs <= 5000 ? "PASS" : "FAIL"}（${recallMs}ms）`);
    if (slowest > 2500 || recallMs > 5000) {
      console.log("  ⚠️ 未达标：贴上 EXPLAIN(ANALYZE) 看是 plan 还是传输，再决定优化；不要靠抬 timeout 蒙混。");
    }
  } finally {
    await pool.end();
  }
}

main().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });

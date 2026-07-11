// 只读性能验证：用真实 JOBS_DATABASE_URL + 固定画像，量「机会召回」的真实往返耗时（含行传输）。
// 跑：JOBS_DATABASE_URL 已在环境（set -a; source .env.local; set +a）后 `npx tsx scripts/verify-opportunity-recall.ts`
// 不打印连接串/密码。
//
// ⚠️ 必须与 lib/jobs-store/opportunities.ts 的 recallViaStore 同口径：P0-1 第二轮已把「三并行分支」
//    合并成**一条** search_doc OR 查询（单连接单往返）——本脚本随之改为量这条合并查询，否则测的是旧设计。
import { Pool } from "pg";
import { buildJobsDatabaseSsl } from "../lib/jobs-store/tls-options.js";
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
// 与 RECALL_COLUMNS 同步（opportunities.ts，P0-1 已缩到硬门/打分必需列）
const COLS =
  `id, source_id, company, title, location, job_type, left(btrim(summary), ${SUMMARY_TRUNC}) as summary, ` +
  "jd_url, salary_text, first_seen_at, last_seen_at, status, education";

async function main() {
  const url = process.env.JOBS_DATABASE_URL;
  if (!url) { console.error("JOBS_DATABASE_URL 未配置"); process.exit(2); }
  const u = new URL(url);
  const pool = new Pool({
    host: u.hostname, port: u.port ? Number(u.port) : 5432,
    user: decodeURIComponent(u.username), password: decodeURIComponent(u.password),
    database: u.pathname.replace(/^\//, "") || "jobradar_jobs",
    ssl: buildJobsDatabaseSsl(process.env, u.hostname), max: 5, connectionTimeoutMillis: 12_000, statement_timeout: 15_000,
  });
  pool.on("error", (e) => console.warn("[pool] idle error:", e.message));

  const roleTs = buildTsquery(ftsCandidateTerms("算法"), []);
  const cityTs = buildTsquery(PROFILE.targetLocations, []);
  const companyTs = buildTsquery(PROFILE.targetCompanies, []);

  // 复刻 recallViaStore：role OR company OR (city AND 近7天)，单条查询、单连接。
  const params: unknown[] = [];
  const ors: string[] = [];
  if (roleTs) { params.push(roleTs); ors.push(`search_doc @@ to_tsquery('simple', $${params.length})`); }
  if (companyTs) { params.push(companyTs); ors.push(`search_doc @@ to_tsquery('simple', $${params.length})`); }
  if (cityTs) { params.push(cityTs); ors.push(`(search_doc @@ to_tsquery('simple', $${params.length}) and first_seen_at >= now() - interval '7 days')`); }
  const sql =
    `select ${COLS} from jobs where status='active' and last_seen_at >= now() - interval '7 days' ` +
    `and summary is not null and char_length(btrim(summary)) >= 60 and (${ors.join(" or ")}) ` +
    `order by first_seen_at desc limit 4000`;

  try {
    console.log("画像：算法 / 上海 / 字节跳动+示例新公司XYZ");
    console.log("召回 = 单条合并 search_doc OR 查询（单连接单往返）\n");
    // 先 warm 一次连接（排除冷池 SSL 握手对单次测量的污染），再正式量 3 次取中位。
    await pool.query("select 1");
    const samples: number[] = [];
    let lastRows = 0;
    let lastPayloadBytes = 0;
    for (let i = 0; i < 3; i++) {
      const t0 = Date.now();
      const r = await pool.query(sql, params);
      samples.push(Date.now() - t0);
      lastRows = r.rowCount ?? 0;
      lastPayloadBytes = Buffer.byteLength(JSON.stringify(r.rows), "utf8"); // 仅量大小，不打印行内容
    }
    samples.sort((a, b) => a - b);
    const median = samples[1];
    const capped = lastRows >= 4000;
    console.log(`三次耗时(ms)：${samples.join(" / ")}  中位 ${median}ms  rows=${lastRows}  payload_bytes=${lastPayloadBytes}  candidate_capped=${capped}`);
    console.log("\n门槛检查：");
    console.log(`  合并召回 ≤5000ms：${median <= 5000 ? "PASS" : "FAIL"}（中位 ${median}ms）`);
    console.log("  （/today SSR ≤8s 由此 + 引擎纯 JS 推断；引擎对数千行通常 <1s + 一次 sources 批查）");
    if (median > 5000) {
      console.log("  ⚠️ 未达标：贴 EXPLAIN(ANALYZE) 看 plan vs 传输——plan 快而总慢=跨区延迟(基础设施层，需定 region/连接池)，不要靠抬 timeout 蒙混。");
    }
  } finally {
    await pool.end();
  }
}

main().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });

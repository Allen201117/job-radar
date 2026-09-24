#!/usr/bin/env node
"use strict";
/**
 * 求职雷达 — jobs 唯一性只读审计（读香港 jobs 库）
 *
 * 什么时候跑：改 canonical 规则（lib/canonical-url.js / crawler/normalizer.py / jobs-db/schema.sql 的
 *   canonicalize_jd_url）或给 jobs 加唯一约束之前——先看清存量里会撞多少行，再上迁移。
 *
 * 📌 纠错（2026-09-24）：旧版用 supabase-js 读 Supabase 的 `jobs`，而 jobs 自 2026-06-19（Phase 1）起在香港库，
 *   Supabase 那张表 09-24 实测 0 行 → 旧版恒报「库为空 / 无重复」= 假绿。现在读 JOBS_DATABASE_URL；
 *   active 为 0 直接报错退出，不再把「连错了库」说成「没有重复」。
 *
 * 两段：
 *   A. 库内（每项是一条语句，在一个快照里算完，数字精确）
 *      ① jobs 上每条唯一索引：有没有失效 + 按它自己的键列 / 谓词数重复组。定义从库里读，不写死。
 *         有效的唯一索引下「键里没有 NULL 的重复」必然是 0，不为 0 = 索引失效。
 *         唯一索引把 NULL 当互不相等 → 键里有 NULL 的行不受约束，单独数「NULL 漏网」。
 *      ② 已存的 canonical_jd_url 与库内 canonicalize_jd_url(jd_url) 对不上的行（改了 SQL 函数没回填）。
 *   B. 按 lib/canonical-url.js 在 JS 里重算 active 行的 canonical（keyset 翻页拉 jd_url）
 *      ③ JS 结果与库里已存值对不上的行（JS 与 SQL 两份实现漂移）
 *      ④ ★ 按 JS 规则分组的重复 = 改完 lib/canonical-url.js、按新规则重建唯一索引前要先降级的行数
 *      翻页不是快照：拉取期间有岗上下架。④ 的候选组会按 id 回库复核「现在仍都是 active」才计数。
 *      要精确数「当前规则」的重复，看 A 段。
 *
 * 只读：会话级 default_transaction_read_only=on，任何写语句都会被库拒绝。绝不打印连接串 / 密钥。
 *
 * 用法（本机，需 psql + .env.local 里的 JOBS_DATABASE_URL）：
 *   set -a; source .env.local; set +a
 *   node scripts/audit-job-duplicates.js              # A + B（B 拉约 45 万行，一两分钟）
 *   node scripts/audit-job-duplicates.js --sql-only   # 只跑 A
 *
 * 退出码：0 没查出问题；1 跑不下去（连不上 / active 为 0 / 翻页自检失败）；2 查出了问题（输出里的 ✗ 行）。
 */
const { runPsql } = require("./lib/psql.js");
const { canonicalizeJdUrl } = require("../lib/canonical-url");

// 2026-09-24 实测：一页 2 万行约 4MB、4 秒；游标翻到 40 万行深处照样走 jobs_status_first_seen_idx，
// 每页只多过滤掉游标所在的那一个并列块（251 行）。
const PAGE_SIZE = 20000;
const SAMPLE = 8;
const VERIFY_CHUNK = 5000;
const SQL_ONLY = process.argv.includes("--sql-only");
// canonical 去重的那条索引（jobs-db/schema.sql）。它不在或失效 = 整个去重设计失守。
const CANONICAL_INDEX = "jobs_canonical_jd_url_active_uniq";

const PSQL_OPTS = {
  maxBuffer: 256 * 1024 * 1024,
  env: {
    ...process.env,
    PGAPPNAME: "audit-job-duplicates",
    // 只读兜底 + 语句超时：jobs 库是线上的 2C2G 小机器，别让一条失控的查询拖住它。
    PGOPTIONS: `${process.env.PGOPTIONS || ""} -c default_transaction_read_only=on -c statement_timeout=300s`.trim(),
  },
};

const lit = (v) => "'" + String(v).replace(/'/g, "''") + "'";
const ident = (name) => '"' + String(name).replace(/"/g, '""') + '"';
const pct = (n, total) => (total ? ((n / total) * 100).toFixed(2) : "0.00") + "%";
const num = (n) => Number(n).toLocaleString("en-US");

/** 一条 SQL → 行数组。连接串经环境变量传给 psql，不进命令行（scripts/lib/psql.js）。 */
function rows(sql, aggOrder = "") {
  const text = runPsql(
    ["-X", "-q", "-t", "-A", "-c", `select coalesce(json_agg(t${aggOrder ? ` order by ${aggOrder}` : ""}), '[]'::json) from (${sql}) t`],
    PSQL_OPTS,
  ).trim();
  return JSON.parse(text);
}

let problems = 0;
const bad = (msg) => {
  problems += 1;
  console.log(`  ✗ ${msg}`);
};
const ok = (msg) => console.log(`  ✓ ${msg}`);

// ── A① 唯一索引 ─────────────────────────────────────────────────────────────────
function auditUniqueIndexes() {
  const indexes = rows(`
    select c.relname as name, i.indisvalid as valid, i.indisready as ready,
           i.indnullsnotdistinct as nulls_not_distinct, i.indexprs is not null as has_expressions,
           pg_get_expr(i.indpred, i.indrelid) as predicate, pg_get_indexdef(i.indexrelid) as def,
           (select json_agg(a.attname order by k.ord)
              from unnest(i.indkey::int2[]) with ordinality k(attnum, ord)
              join pg_attribute a on a.attrelid = i.indrelid and a.attnum = k.attnum
             where k.ord <= i.indnkeyatts) as columns
      from pg_index i join pg_class c on c.oid = i.indexrelid
     where i.indrelid = 'public.jobs'::regclass and i.indisunique and not i.indisprimary`, "t.name");

  console.log("\n—— A① jobs 上的唯一索引（定义从库里读）——");
  if (!indexes.some((ix) => ix.name === CANONICAL_INDEX)) bad(`没找到 ${CANONICAL_INDEX}：canonical 去重不受库约束`);

  for (const ix of indexes) {
    console.log(`\n  ${ix.name}\n    ${ix.def}`);
    if (!ix.valid || !ix.ready) bad(`索引无效（valid=${ix.valid} ready=${ix.ready}）：库不再拦重复，下面的数字就是真实重复`);
    if (ix.has_expressions || !ix.columns || !ix.columns.length) {
      console.log("    ⚠ 表达式索引，本脚本不会数，请手动按它的表达式 group by");
      continue;
    }
    const cols = ix.columns.map(ident);
    const where = ix.predicate ? `where ${ix.predicate}` : "";
    const hasNull = cols.map((c) => `${c} is null`).join(" or ");
    const [s] = rows(`
      select (select count(*) from jobs ${where}) as scope_rows,
             (select count(*) from jobs ${where ? `${where} and` : "where"} (${hasNull})) as null_key_rows,
             count(*) filter (where not g.has_null) as dup_groups,
             coalesce(sum(g.n) filter (where not g.has_null), 0) as dup_rows,
             count(*) filter (where g.has_null) as null_dup_groups,
             coalesce(sum(g.n) filter (where g.has_null), 0) as null_dup_rows
        from (select count(*) as n, bool_or(${hasNull}) as has_null
                from jobs ${where} group by ${cols.join(", ")} having count(*) > 1) g`);
    // NULLS NOT DISTINCT 的索引连 NULL 键也拦，此时两类重复都算「本该被拦」。
    const enforcedGroups = s.dup_groups + (ix.nulls_not_distinct ? s.null_dup_groups : 0);
    const enforcedRows = s.dup_rows + (ix.nulls_not_distinct ? s.null_dup_rows : 0);
    console.log(`    范围内行数: ${num(s.scope_rows)}；键里有 NULL（不受约束）: ${num(s.null_key_rows)}`);
    if (enforcedGroups) {
      bad(`重复 ${num(enforcedGroups)} 组 / ${num(enforcedRows)} 行（多出 ${num(enforcedRows - enforcedGroups)} 行）`);
      printGroups(cols, where, "not");
    } else {
      ok("按索引键列没有重复");
    }
    if (ix.nulls_not_distinct || !s.null_key_rows) continue;
    if (s.null_dup_groups) {
      console.log(
        `    ⚠ NULL 漏网：键里有 NULL 的重复 ${num(s.null_dup_groups)} 组 / ${num(s.null_dup_rows)} 行` +
          `（这条索引不拦它们；若要改成 NULLS NOT DISTINCT，先处理这些行）`,
      );
      printGroups(cols, where, "");
    } else {
      ok("键里有 NULL 的行之间也没有重复");
    }
  }
}

function printGroups(cols, where, notNull) {
  const hasNull = cols.map((c) => `${c} is null`).join(" or ");
  const sample = rows(`
    select ${cols.join(", ")}, count(*) as n, (array_agg(id::text || '(' || status || ')' order by id))[1:6] as members
      from jobs ${where} group by ${cols.join(", ")}
    having count(*) > 1 and ${notNull} bool_or(${hasNull})
     order by count(*) desc, ${cols.join(", ")} limit ${SAMPLE}`);
  for (const g of sample) {
    const key = cols.map((c) => g[c.slice(1, -1).replace(/""/g, '"')]).map((v) => (v == null ? "NULL" : v)).join(" | ");
    console.log(`      ${g.n} 行  ${key}\n        ${g.members.join(" ")}${g.n > g.members.length ? " …" : ""}`);
  }
}

// ── A② 已存 canonical vs 库内 SQL 函数 ──────────────────────────────────────────
function auditStoredCanonical() {
  console.log("\n—— A② 已存 canonical_jd_url 与库内 canonicalize_jd_url(jd_url) 是否一致（全部 status）——");
  const drift = rows(`
    select status, count(*) as n from jobs
     where canonical_jd_url is distinct from canonicalize_jd_url(jd_url) group by status`, "t.status");
  const total = drift.reduce((a, r) => a + r.n, 0);
  if (!total) return ok("全部一致");
  bad(`对不上 ${num(total)} 行（${drift.map((r) => `${r.status} ${num(r.n)}`).join("，")}）——SQL 函数改过但没回填`);
  const sample = rows(`
    select id, status, jd_url, canonical_jd_url as stored, canonicalize_jd_url(jd_url) as recomputed from jobs
     where canonical_jd_url is distinct from canonicalize_jd_url(jd_url) order by id limit ${SAMPLE}`);
  for (const r of sample) console.log(`      ${r.id}(${r.status})\n        已存 ${r.stored}\n        重算 ${r.recomputed}`);
}

// ── B 段：keyset 翻页拉 active 行 ────────────────────────────────────────────────
// 游标 = 上一页最后一行的 (first_seen_at, id)。first_seen_at 必须原样留 JSON 里的文本：
// 它精确到微秒，转成 JS Date 会截到毫秒，游标落进并列块中间 → 漏行或重复。
// 不用一条 COPY 全拉：那是一条跑好几分钟的长语句，线上小库上全程占着快照和表锁。
const PAGE_COLS = "id, jd_url, nullif(canonical_jd_url, jd_url) as stored"; // 绝大多数行 canonical == jd_url，省一半流量

function* activePages() {
  let cur = null;
  for (;;) {
    const bound = cur ? `and (first_seen_at, id) < (${lit(cur.first_seen_at)}::timestamptz, ${lit(cur.id)}::uuid)` : "";
    const page = rows(
      `select ${PAGE_COLS}, first_seen_at from jobs
        where status = 'active' and first_seen_at is not null ${bound}
        order by first_seen_at desc, id desc limit ${PAGE_SIZE}`,
      "t.first_seen_at desc, t.id desc",
    );
    if (page.length) yield page;
    if (page.length < PAGE_SIZE) break;
    cur = page[page.length - 1];
  }
  // first_seen_at 可空：行比较遇 NULL 恒不成立，上面取不到这些行 → 单独按 id 翻。
  let lastId = null;
  for (;;) {
    const page = rows(
      `select ${PAGE_COLS} from jobs
        where status = 'active' and first_seen_at is null ${lastId ? `and id < ${lit(lastId)}::uuid` : ""}
        order by id desc limit ${PAGE_SIZE}`,
      "t.id desc",
    );
    if (page.length) yield page;
    if (page.length < PAGE_SIZE) break;
    lastId = page[page.length - 1].id;
  }
}

function auditJsCanonical(activeBefore) {
  console.log(`\n—— B 按 lib/canonical-url.js 重算 active 行（keyset 翻页，每页 ${num(PAGE_SIZE)} 行）——`);
  const t0 = Date.now();
  const seenIds = new Set();
  const firstIdOf = new Map(); // JS canonical → 第一个 id
  const candidates = new Map(); // JS canonical → [id, ...]（≥2 行）
  const drift = [];
  let driftCount = 0;
  let nullCanon = 0;
  let pageNo = 0;

  for (const page of activePages()) {
    pageNo += 1;
    for (const r of page) {
      if (seenIds.has(r.id)) throw new Error(`翻页自检失败：id ${r.id} 被拉到两次（keyset 写错了）`);
      seenIds.add(r.id);
      const stored = r.stored ?? r.jd_url;
      const canon = canonicalizeJdUrl(r.jd_url);
      if (canon !== stored) {
        driftCount += 1;
        if (drift.length < SAMPLE) drift.push({ id: r.id, jd_url: r.jd_url, stored, canon });
      }
      if (canon == null) {
        nullCanon += 1; // 唯一索引不拦 NULL，和库里的口径一致
        continue;
      }
      const first = firstIdOf.get(canon);
      if (first === undefined) firstIdOf.set(canon, r.id);
      else if (candidates.has(canon)) candidates.get(canon).push(r.id);
      else candidates.set(canon, [first, r.id]);
    }
    process.stderr.write(`\r  第 ${pageNo} 页，累计 ${num(seenIds.size)} 行，${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
  process.stderr.write("\n");

  const [{ active: activeAfter }] = rows(`select count(*) as active from jobs where status = 'active'`);
  console.log(`  拉到 ${num(seenIds.size)} 行（开始时 active ${num(activeBefore)}，结束时 ${num(activeAfter)}；差额是拉取期间的上下架）`);
  if (seenIds.size < 0.95 * Math.min(activeBefore, activeAfter)) {
    throw new Error(`翻页自检失败：只拉到 ${seenIds.size} 行，比 active 少 5% 以上`);
  }
  if (nullCanon) console.log(`  jd_url 为 NULL（不受唯一索引约束）: ${num(nullCanon)}`);

  console.log("\n  ③ JS 重算值 vs 库里已存的 canonical_jd_url");
  if (!driftCount) ok("全部一致（JS 与库内 SQL 两份实现在真实数据上没有漂移）");
  else {
    bad(`对不上 ${num(driftCount)} 行 (${pct(driftCount, seenIds.size)})——JS 与 SQL 两份实现漂移，或本地改了规则还没同步三处`);
    for (const d of drift) console.log(`      ${d.id}\n        jd_url ${d.jd_url}\n        库里   ${d.stored}\n        JS     ${d.canon}`);
  }

  // ④ 候选组回库复核：只数「现在仍有 ≥2 行 active」的组，排除翻页期间一下一上的时间差。
  const ids = [...candidates.values()].flat();
  const now = new Map();
  for (let i = 0; i < ids.length; i += VERIFY_CHUNK) {
    const chunk = ids.slice(i, i + VERIFY_CHUNK);
    for (const r of rows(`select id, status, company, title from jobs where id = any(array[${chunk.map(lit).join(",")}]::uuid[])`)) {
      now.set(r.id, r);
    }
  }
  const confirmed = [];
  let groupRows = 0;
  let conflicts = 0;
  for (const [canon, members] of candidates) {
    const live = members.map((id) => now.get(id)).filter((r) => r && r.status === "active");
    if (live.length < 2) continue;
    groupRows += live.length;
    const companies = new Set(live.map((r) => (r.company || "").trim()));
    const titles = new Set(live.map((r) => (r.title || "").trim()));
    if (companies.size > 1 || titles.size > 1) conflicts += 1;
    confirmed.push({ canon, n: live.length, companies: [...companies], titles: [...titles] });
  }
  const groups = confirmed.length;
  const samples = confirmed
    .sort((a, b) => b.n - a.n)
    .slice(0, SAMPLE)
    .map((g) => `      ${g.n} 行  ${g.canon}\n        ${g.companies.slice(0, 3).join(" | ")} :: ${g.titles.slice(0, 3).join(" / ")}`);
  console.log("\n  ④ ★ 按 JS 规则分组的重复（= 按这版规则重建唯一索引前要先降级的行）");
  console.log(`    翻页时发现的候选组 ${num(candidates.size)}，回库复核后仍都 active 的 ${num(groups)}`);
  if (!groups) ok("没有重复");
  else {
    bad(`重复 ${num(groups)} 组 / ${num(groupRows)} 行，要降级 ${num(groupRows - groups)} 行（每组留 1 行）；其中 company/title 不一致 ${num(conflicts)} 组`);
    console.log(samples.join("\n"));
  }
}

function main() {
  console.log("================ 求职雷达 · jobs 唯一性审计（香港 jobs 库，只读）================");
  const [head] = rows(`select count(*) filter (where status = 'active') as active, count(*) as total from jobs`);
  console.log(`jobs 总行数 ${num(head.total)}，其中 active ${num(head.active)}`);
  if (!head.active) {
    // 旧版在这里打印「库为空 → 无需审计」然后正常退出，连错库时就是一个绿灯。
    throw new Error("jobs 里 active 为 0：多半连错了库（Supabase 的 jobs 自 2026-06-19 起不是真数据），不能当作「没有重复」");
  }

  auditUniqueIndexes();
  auditStoredCanonical();
  if (SQL_ONLY) console.log("\n（--sql-only：跳过 B 段 JS 重算）");
  else auditJsCanonical(head.active);

  console.log("\n==================================================================================");
  console.log(problems ? `✗ 查出 ${problems} 项问题，先处理再上唯一约束类迁移。` : "✓ 没查出问题。");
  process.exitCode = problems ? 2 : 0;
}

try {
  main();
} catch (e) {
  // runPsql 抛出的报错已脱敏（不含连接串 / 主机 / 密码）。
  console.error(`\n审计失败: ${e.message}`);
  process.exit(1);
}

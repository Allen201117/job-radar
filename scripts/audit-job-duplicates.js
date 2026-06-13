#!/usr/bin/env node
/**
 * 求职雷达 — jobs 重复 / 数据可信度只读审计（P0-1 前置）
 *
 * 目的：在给 active jobs 加 canonical_jd_url 唯一约束（partial unique index）之前，
 *   先量化存量里：① 重复 jd_url（原样 / canonical 归一后）② 同链接不同 company/title 冲突
 *   ③ 空 summary ④ 过旧 last_seen_at 占比。
 *   ★ canonical 重复数 = 迁移会「降级为 removed」的行数，先跑这个脚本看清影响面，再上迁移。
 *
 * 只读：仅 SELECT，不写任何表。绝不打印任何密钥。
 *
 * 用法（本机，需 .env.local 里有 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY）：
 *   set -a; source .env.local; set +a
 *   node scripts/audit-job-duplicates.js
 */
const { createClient } = require("@supabase/supabase-js");
const { canonicalizeJdUrl } = require("../lib/canonical-url");

const URL = process.env.SUPABASE_URL;
const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!URL || !KEY) {
  console.error("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 环境变量。");
  console.error("  先执行：set -a; source .env.local; set +a");
  process.exit(1);
}

const isEmpty = (v) => v == null || String(v).trim() === "";
const pct = (n, total) => (total ? ((n / total) * 100).toFixed(1) : "0.0") + "%";
const days = (ms) => Math.floor(ms / 86400000);

async function fetchAllActiveJobs(sb) {
  const cols = "id,company,title,location,jd_url,summary,last_seen_at,first_seen_at";
  const pageSize = 1000;
  const all = [];
  for (let from = 0; ; from += pageSize) {
    const { data, error } = await sb
      .from("jobs")
      .select(cols)
      .eq("status", "active")
      .order("first_seen_at", { ascending: false })
      .range(from, from + pageSize - 1);
    if (error) throw new Error("查询 jobs 失败: " + error.message);
    if (!data || data.length === 0) break;
    all.push(...data);
    if (data.length < pageSize) break;
  }
  return all;
}

// 把 active 行按某个 key 函数分组，返回 Map<key, rows[]>，只保留 size>1 的重复组。
function dupGroups(jobs, keyOf) {
  const m = new Map();
  for (const j of jobs) {
    const k = keyOf(j);
    if (isEmpty(k)) continue;
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(j);
  }
  for (const [k, rows] of m) if (rows.length < 2) m.delete(k);
  return m;
}

(async () => {
  const sb = createClient(URL, KEY, { auth: { persistSession: false } });
  console.log("正在拉取活跃岗位库（只读，分页）…");
  const jobs = await fetchAllActiveJobs(sb);
  const N = jobs.length;

  console.log("\n================ 求职雷达 · jobs 重复 / 可信度审计 ================");
  console.log(`活跃岗位总数: ${N}`);
  if (N === 0) {
    console.log("库为空 → 无需审计。");
    return;
  }

  // ① 原样 jd_url 重复
  const rawDups = dupGroups(jobs, (j) => j.jd_url);
  let rawDupRows = 0;
  for (const rows of rawDups.values()) rawDupRows += rows.length;
  console.log("\n—— ① 原样 jd_url 重复（active）——");
  console.log(`  重复 jd_url 组数      : ${rawDups.size}`);
  console.log(`  涉及行数              : ${rawDupRows} (${pct(rawDupRows, N)})`);
  console.log(`  其中冗余可降级行数    : ${rawDupRows - rawDups.size}`);

  // ② canonical 归一后重复（= 迁移会降级 removed 的影响面）
  const canonDups = dupGroups(jobs, (j) => canonicalizeJdUrl(j.jd_url));
  let canonDupRows = 0;
  let canonDemote = 0; // 每组保留 1 行、其余降级
  for (const rows of canonDups.values()) {
    canonDupRows += rows.length;
    canonDemote += rows.length - 1;
  }
  console.log("\n—— ② canonical_jd_url 归一后重复（★ 迁移影响面）——");
  console.log(`  重复 canonical 组数   : ${canonDups.size}`);
  console.log(`  涉及行数              : ${canonDupRows} (${pct(canonDupRows, N)})`);
  console.log(`  ★ 迁移将降级 removed  : ${canonDemote} 行（每组保留最新 1 行）`);
  console.log(`  归一比原样多抓出的重复: ${canonDups.size - rawDups.size} 组`);

  // ③ 同 canonical 不同 company/title 的冲突（数据质量隐患：同链接被标成不同岗）
  let conflictGroups = 0;
  const conflictSamples = [];
  for (const [k, rows] of canonDups) {
    const companies = new Set(rows.map((r) => (r.company || "").trim()));
    const titles = new Set(rows.map((r) => (r.title || "").trim()));
    if (companies.size > 1 || titles.size > 1) {
      conflictGroups += 1;
      if (conflictSamples.length < 8) {
        conflictSamples.push(
          `    ${k}\n      → ${[...companies].join(" | ")} :: ${[...titles].slice(0, 3).join(" / ")}`,
        );
      }
    }
  }
  console.log("\n—— ③ 同 canonical 不同 company/title 冲突 ——");
  console.log(`  冲突组数: ${conflictGroups}`);
  if (conflictSamples.length) console.log(conflictSamples.join("\n"));

  // ④ 空 summary
  const nullSum = jobs.filter((j) => isEmpty(j.summary)).length;
  console.log("\n—— ④ 空 summary（active）——");
  console.log(`  summary 为空: ${nullSum} (${pct(nullSum, N)})`);

  // ⑤ 过旧 last_seen_at 占比（撤岗治理信号：很久没在抓取里再见到的 active 岗）
  const now = Date.now();
  const ages = jobs
    .map((j) => (j.last_seen_at ? days(now - new Date(j.last_seen_at).getTime()) : null))
    .filter((d) => d != null);
  const olderThan = (d) => ages.filter((a) => a > d).length;
  const nullSeen = jobs.filter((j) => isEmpty(j.last_seen_at)).length;
  console.log("\n—— ⑤ last_seen_at 时效（active）——");
  console.log(`  > 7 天未再见 : ${olderThan(7)} (${pct(olderThan(7), N)})`);
  console.log(`  > 14 天未再见: ${olderThan(14)} (${pct(olderThan(14), N)})`);
  console.log(`  > 30 天未再见: ${olderThan(30)} (${pct(olderThan(30), N)})`);
  console.log(`  last_seen_at 为空: ${nullSeen}`);

  console.log("\n==================================================================");
  console.log("解读：");
  console.log("  · ② 的「迁移将降级 removed」即新迁移要处理的存量重复——非 0 时迁移内置 dedup 会把它们降级，");
  console.log("     不会让 CREATE UNIQUE INDEX 失败阻塞后续迁移。先看这个数确认影响面。");
  console.log("  · ③ 冲突组多 → 抓取端把同一链接标成了不同岗，属元数据质量问题，可单独排查。");
})().catch((e) => {
  console.error("审计失败:", e.message);
  process.exit(1);
});

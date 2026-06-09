#!/usr/bin/env node
/**
 * 求职雷达 — 岗位库 & 检索漏斗只读诊断脚本（改造 Phase 0）
 *
 * 目的：用真实数据验证「库很大却筛不出一个」的根因——
 *   元数据稀薄（空地点/空摘要/空类型） + 城市 ∧ 类型 ∧ 关键词 的硬 AND 过滤。
 *
 * 关键：本脚本直接复用前端真实筛选逻辑 lib/china-keyword-expansion.js
 *   （recruitmentCategory / normalizeChinaCity / jobMatchesChinaKeyword / classifyJobFunction），
 *   所以这里算出的「漏斗」数字 == 你在岗位库页设同样筛选看到的结果。
 *
 * 只读：仅 SELECT，不写任何表。绝不打印任何密钥。
 *
 * 用法（本机，需 .env.local 里有 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY）：
 *   set -a; source .env.local; set +a
 *   node scripts/diagnose-jobs.js
 *   # 可选：用你自己的真实筛选组合看漏斗
 *   node scripts/diagnose-jobs.js --city 上海 --type 社招 --keyword 算法
 */
const { createClient } = require("@supabase/supabase-js");
const {
  recruitmentCategory,
  normalizeChinaCity,
  jobMatchesChinaKeyword,
  keywordMatchTier,
  classifyJobFunction,
} = require("../lib/china-keyword-expansion");

const URL = process.env.SUPABASE_URL;
const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!URL || !KEY) {
  console.error("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 环境变量。");
  console.error("  先执行：set -a; source .env.local; set +a");
  process.exit(1);
}

const TIER_CITIES = [
  "北京", "上海", "深圳", "广州", "杭州", "成都", "南京", "苏州",
  "武汉", "西安", "重庆", "天津", "厦门", "长沙", "青岛", "合肥",
];

const isEmpty = (v) => v == null || String(v).trim() === "";
const pct = (n, total) => (total ? ((n / total) * 100).toFixed(1) : "0.0") + "%";
const argOf = (name) => {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 ? process.argv[i + 1] : null;
};

// 复刻 jobs-client.tsx 的 jobMatchesFilters 三刀，逐刀可独立施加。
const cutCity = (job, city) => {
  if (!city) return true;
  const loc = job.location || "";
  return loc.includes(city) || loc.includes(normalizeChinaCity(city));
};
const cutType = (job, type) => (type ? recruitmentCategory(job) === type : true);
const cutKeyword = (job, kw) => (kw ? jobMatchesChinaKeyword(job, kw) : true);

async function fetchAllActiveJobs(sb) {
  const cols =
    "title,company,location,job_type,summary,salary_text,posted_at,first_seen_at,jd_url,apply_url";
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

function funnel(jobs, { city, type, keyword }) {
  const afterCity = jobs.filter((j) => cutCity(j, city));
  const afterType = afterCity.filter((j) => cutType(j, type));
  const afterKw = afterType.filter((j) => cutKeyword(j, keyword)); // 旧：一刀切（=精确）
  // 新：两层匹配（P1-B）——精确 + 同职能相关。
  let exact = 0;
  let related = 0;
  for (const j of afterType) {
    const t = keyword ? keywordMatchTier(j, keyword) : "exact";
    if (t === "exact") exact += 1;
    else if (t === "related") related += 1;
  }
  return { n0: jobs.length, city: afterCity.length, type: afterType.length, kw: afterKw.length, exact, related };
}

(async () => {
  const sb = createClient(URL, KEY, { auth: { persistSession: false } });
  console.log("正在拉取活跃岗位库（只读，分页）…");
  const jobs = await fetchAllActiveJobs(sb);
  const N = jobs.length;

  console.log("\n================ 求职雷达 · 岗位库诊断 ================");
  console.log(`活跃岗位总数: ${N}`);
  if (N === 0) {
    console.log("库为空 → 问题在抓取端，不在检索端。");
    return;
  }

  // ① 元数据完整度（= 检索杀伤的弹药）
  const nullLoc = jobs.filter((j) => isEmpty(j.location)).length;
  const nullSum = jobs.filter((j) => isEmpty(j.summary)).length;
  const nullType = jobs.filter((j) => isEmpty(j.job_type)).length;
  const nullPosted = jobs.filter((j) => isEmpty(j.posted_at)).length;
  const nullSalary = jobs.filter((j) => isEmpty(j.salary_text)).length;
  const reachableTier = jobs.filter((j) => TIER_CITIES.some((c) => cutCity(j, c))).length;

  console.log("\n—— ① 元数据完整度（稀薄度 = 硬 AND 的弹药）——");
  console.log(`  location 为空 : ${nullLoc} (${pct(nullLoc, N)})   ← 任何城市筛选都会秒杀这些`);
  console.log(`  summary  为空 : ${nullSum} (${pct(nullSum, N)})   ← 关键词只能靠光秃秃的标题匹配`);
  console.log(`  job_type 为空 : ${nullType} (${pct(nullType, N)})   ← 三桶分类只能靠标题猜，默认堆社招`);
  console.log(`  posted_at为空 : ${nullPosted} (${pct(nullPosted, N)})`);
  console.log(`  salary   为空 : ${nullSalary} (${pct(nullSalary, N)})`);
  console.log(`  能被任一主流城市筛选命中的岗位: ${reachableTier} (${pct(reachableTier, N)})`);

  // ② 三桶 & 职能分布
  const bucket = {};
  const func = {};
  for (const j of jobs) {
    const b = recruitmentCategory(j);
    bucket[b] = (bucket[b] || 0) + 1;
    const f = classifyJobFunction(j);
    func[f] = (func[f] || 0) + 1;
  }
  console.log("\n—— ② 三桶招聘类型分布（recruitmentCategory，前端「类型」筛选口径）——");
  for (const k of ["社招", "校招", "实习"]) {
    console.log(`  ${k}: ${bucket[k] || 0} (${pct(bucket[k] || 0, N)})`);
  }
  console.log("\n—— ② 职能分布（classifyJobFunction）——");
  Object.entries(func)
    .sort((a, b) => b[1] - a[1])
    .forEach(([k, v]) => console.log(`  ${k}: ${v} (${pct(v, N)})`));

  // ③ 筛选漏斗模拟（城市 → +类型 → +关键词，硬 AND）
  console.log("\n—— ③ 筛选漏斗模拟（城市 → +类型 → +关键词，逐刀硬 AND）——");
  const user = { city: argOf("city"), type: argOf("type"), keyword: argOf("keyword") };
  const combos =
    user.city || user.type || user.keyword
      ? [user]
      : [
          { city: "上海", type: "社招", keyword: "算法" },
          { city: "北京", type: "社招", keyword: "产品" },
          { city: "深圳", type: "社招", keyword: "后端" },
          { city: "上海", type: "实习", keyword: "算法" },
        ];
  for (const c of combos) {
    const f = funnel(jobs, c);
    console.log(`\n  组合: 城市=${c.city || "—"}  类型=${c.type || "—"}  关键词=${c.keyword || "—"}`);
    console.log(`    起始              ${f.n0}`);
    console.log(`    +城市             ${f.city} (${pct(f.city, f.n0)})`);
    console.log(`    +类型             ${f.type} (${pct(f.type, f.n0)})`);
    console.log(`    +关键词【旧·一刀切】 ${f.kw}  ←★ 改造前用户实际看到的`);
    console.log(`    +关键词【新·两层】   精确 ${f.exact} + 相关 ${f.related} = ${f.exact + f.related}  ←★ P1 改造后`);
  }

  // ④ 抓取产出健康度
  const byCompany = {};
  for (const j of jobs) {
    const c = j.company || "（空公司名）";
    byCompany[c] = (byCompany[c] || 0) + 1;
  }
  const companies = Object.entries(byCompany).sort((a, b) => b[1] - a[1]);
  console.log("\n—— ④ 抓取产出：岗位最多的 15 家公司 ——");
  companies.slice(0, 15).forEach(([c, n]) => console.log(`  ${c}: ${n}`));

  const now = Date.now();
  const freshWithin = (h) =>
    jobs.filter(
      (j) => j.first_seen_at && now - new Date(j.first_seen_at).getTime() <= h * 3600000,
    ).length;
  console.log("\n—— ④ 抓取新鲜度（first_seen_at）——");
  console.log(`  近 24h 新增: ${freshWithin(24)}`);
  console.log(`  近 7d  新增: ${freshWithin(24 * 7)}`);

  try {
    const { data: srcs } = await sb.from("sources").select("company,enabled");
    if (srcs) {
      const enabled = srcs.filter((s) => s.enabled);
      const withJobs = new Set(companies.map(([c]) => c));
      const zero = enabled.filter((s) => !withJobs.has(s.company));
      console.log("\n—— ④ 源通道 vs 实际有岗 ——");
      console.log(`  enabled 源通道数      : ${enabled.length}`);
      console.log(`  库中有岗位的公司数    : ${withJobs.size}`);
      console.log(`  通道开了但库里 0 岗    : ${zero.length} (${pct(zero.length, enabled.length)})`);
      if (zero.length) {
        const sample = zero.slice(0, 20).map((s) => s.company).join("、");
        console.log(`    例: ${sample}${zero.length > 20 ? " …" : ""}`);
      }
    }
  } catch (e) {
    console.log("  （sources 查询跳过: " + e.message + "）");
  }

  try {
    const { data: runs } = await sb
      .from("crawl_runs")
      .select("source_id,status,jobs_found,jobs_created,created_at")
      .order("created_at", { ascending: false })
      .limit(3000);
    if (runs && runs.length) {
      const latest = {};
      for (const r of runs) if (!(r.source_id in latest)) latest[r.source_id] = r;
      const dist = {};
      let created = 0;
      for (const r of Object.values(latest)) {
        dist[r.status] = (dist[r.status] || 0) + 1;
        created += r.jobs_created || 0;
      }
      console.log("\n—— ④ 各源「最近一次」抓取状态分布 ——");
      Object.entries(dist)
        .sort((a, b) => b[1] - a[1])
        .forEach(([s, n]) => console.log(`  ${s}: ${n}`));
      console.log(`  （这些「最近一次」合计 jobs_created = ${created}）`);
    }
  } catch (e) {
    console.log("  （crawl_runs 查询跳过: " + e.message + "）");
  }

  console.log("\n====================================================");
  console.log("解读速查：");
  console.log("  · ① location 空占比高 + ③「+城市」那刀掉得狠 → 检索端「空地点秒杀」实锤，Phase 1 先修。");
  console.log("  · ② job_type 多空 + 三桶几乎全堆社招 → 类型桶失真，校招/实习生天然筛不到。");
  console.log("  · ④ 大量通道 0 岗 / 最近状态多 partial_success·failed → 抓取端适配器脆，Phase 2/3 富化+提速。");
})().catch((e) => {
  console.error("诊断失败:", e.message);
  process.exit(1);
});

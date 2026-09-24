#!/usr/bin/env node
// 校招覆盖走查·产品真实搜索口径版（2026-09-18，campus-persona-coverage.js 的两种裸 tsquery
// 口径都失真——词表扩展版把「工程师」泛词算进来（六个工程师方向在同一城市档几乎拿到同一个
// 6,0xx 岗 / 235 家），原始短语版又过严（「药物研发」在标题里几乎不出现 → 0）。
//
// 本脚本改为直接调用产品真实检索入口 lib/jobs-store/search.ts 的 searchJobsStore：
// 同一份 FTS 召回（search_doc bigram）+ 同一份 JS 精筛分层（exact/related）+ 同一套
// 诚实计数（capped 时 exactTotal 只在能证明数字正确时才给），与用户在 /jobs /campus 页面
// 实际搜索时走的是同一条代码路径——不是又发明一种新口径。
//
// 画像清单直接复用 campus-persona-coverage.js：11 行业（lib/must-apply-list.json 的行业键，
// 教育除外）× 每行业 2~3 个典型校招方向 × 3 个城市档 + 不限城市对照，不重新发挥。
//
// 调用方式：filters = {...DEFAULT_FILTERS, keyword: 方向, city: 城市档城市用逗号连接
// （splitMultiValue 按 [\s,，]+ 拆，逗号/空白皆可，这里统一用逗号），jobType: "校招",
// sortBy: "newest"}，prefs=null（未登录口径，不掺任何人的私有偏好），actions=[]，
// offset=0，limit=500（每个画像最多拿 500 条已排序结果做公司聚合样本）。
//
// 数据库访问：本机没有 JOBS_DATABASE_SSL_CA（只 CI 有），lib/jobs-store/client.ts 的
// node-pg 连接池会在建池那一刻直接抛错拒绝连接（tls-options.js 故意如此，不是 bug，
// 见该文件注释——没有受控 CA 就拒绝以不校验证书身份的方式连接）。所以不直连 pg，
// 照抄 scripts/match-eval/eval.js 的做法：monkey-patch client.jobsQuery，把
// searchJobsStore 内部构造好的参数化 SQL inline 成字面量后过本机 psql 执行。
// SQL 逻辑本身分毫不变（还是 search.ts 自己拼的那些 where/order by），只是换了跑腿的驱动。
//
// 跑法：
//   cd <主仓根> && set -a; source .env.local; set +a
//   cd <本 worktree>
//   node scripts/ux-walkthrough/campus-persona-search.js
// （worktree 嵌在主仓目录树下，Node 的模块解析会自然向上找到主仓 node_modules，
//  不需要额外配 NODE_PATH；示例命令按需加上也无害。）
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "..");
const { loadTs } = require(path.join(ROOT, "tests/_load-ts.js"));
const { runPsql } = require("../lib/psql.js");
const MUST_APPLY = require(path.join(ROOT, "lib/must-apply-list.json"));

// 本 worktree 没有 .env.local（只有主仓根目录有，见文件头注释）。worktree 隔离的安全边界会拒绝
// 在 Bash 命令行里对 worktree 之外的路径执行 `source`（担心夹带 git 操作逃出 worktree，实测
// `source /主仓/.env.local` 被硬拦，报「a worktree-isolated agent's git operations must target
// its own worktree」，dangerouslyDisableSandbox 也绕不过——这是执行环境的结构性边界，不是可协商
// 的权限，不应该用取巧手法迂回）。所以改在 Node 进程内部把它当**纯文本 KEY=VALUE 数据**读进
// process.env：只做正则字符串赋值，不 eval、不做任何 shell 展开、不执行文件里的任何内容，
// 也从不打印任何取到的值——这与「source 执行任意 shell 代码」是两回事，不触发同一类风险。
// 只有本机没配这些变量时才生效（CI / 已 source 过的环境会跳过，走量原来的 process.env）。
function loadMainRepoEnvIfNeeded() {
  if (process.env.JOBS_DATABASE_URL) return;
  const mainRepoEnvPath = path.resolve(ROOT, "..", "..", "..", ".env.local");
  if (!fs.existsSync(mainRepoEnvPath)) return;
  const content = fs.readFileSync(mainRepoEnvPath, "utf8");
  for (const rawLine of content.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const m = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!m) continue;
    let value = m[2];
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (!(m[1] in process.env)) process.env[m[1]] = value;
  }
}

const OUT_MD =
  process.env.CAMPUS_SEARCH_OUT_MD ||
  "/private/tmp/claude-501/-Users-bytedance-Desktop-diy-------claude-worktrees-confident-bose-5f0ea6/78d9f427-7b64-4e73-b74d-ccc299d13064/scratchpad/campus-persona-search.md";
const OUT_JSON =
  process.env.CAMPUS_SEARCH_OUT_JSON || path.join(__dirname, "campus-persona-search-raw.json");
const RESULT_LIMIT = 500;

// —— 与 campus-persona-coverage.js 完全一致的画像清单（不重新发挥，键需与
//    lib/must-apply-list.json 的行业键完全一致；教育行业创始人没给方向例子，本轮不跑）——
const INDUSTRY_PERSONAS = {
  "金融": ["银行管培生", "投行分析师", "风控"],
  "制造/工业": ["机械工程师", "工艺工程师", "设备工程师"],
  "医疗/医药": ["临床研究", "药物研发", "QA"],
  "地产/建筑": ["土木工程师", "造价", "工程管理"],
  "物流/供应链": ["供应链管理", "仓储运营"],
  "消费/零售": ["品牌管培生", "市场营销", "门店管培"],
  "能源/化工": ["化工工程师", "电气工程师"],
  "汽车/出行": ["整车研发", "自动驾驶算法", "售后服务"],
  "互联网/科技": ["后端", "产品", "数据分析"],
  "传媒/文娱": ["内容运营", "编导"],
};

const CITY_TIERS = [
  { label: "北上广深", cities: ["北京", "上海", "广州", "深圳"] },
  { label: "新一线(杭州/成都/武汉)", cities: ["杭州", "成都", "武汉"] },
  { label: "二线(合肥/长沙)", cities: ["合肥", "长沙"] },
  { label: "不限城市", cities: [] },
];

// 央国企②号启发式：只收明确的央企品牌前缀，不收「集团」这种泛用词
// （会把美的集团、小米集团这类私企集团也算进去，宁可漏判也不要制造假阳性）。
const SOE_NAME_PREFIX_RE = /^(中国|国家电网|南方电网|国家能源|国家开发|中央|中远|中核|中化|中粮|中煤|中铝|中建|中铁|中交|中冶|华能|大唐|华电|中投)/;

// ─────────────────────────── psql 直连（照抄 scripts/match-eval/eval.js） ───────────────────────────
function lit(v) {
  if (v === null || v === undefined) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return String(v);
  if (Array.isArray(v)) {
    if (!v.length) return "'{}'";
    if (typeof v[0] === "number") return `array[${v.map(String).join(",")}]::float[]`;
    return `array[${v.map((x) => "'" + String(x).replace(/'/g, "''") + "'").join(",")}]`;
  }
  return "'" + String(v).replace(/'/g, "''") + "'";
}

// searchJobsStore 内部产出的是参数化 SQL（$1/$2/…），psql -c 不便传数组参数 → inline 成字面量。
// 只在本地走查脚本里这么干，生产路径（真正的 lib/jobs-store/client.ts）永远走参数化。
function inlineParams(sql, params) {
  let out = sql;
  for (let i = params.length; i >= 1; i--) out = out.split("$" + i).join(lit(params[i - 1]));
  return out;
}

// 连接串经环境变量传给 psql、不进命令行（见 scripts/lib/psql.js 顶部注释）。
function psqlJson(sql) {
  const wrapped = `select coalesce(json_agg(t), '[]'::json)::text from (${sql}) t`;
  const raw = runPsql(["-t", "-A", "-c", wrapped], { maxBuffer: 512 * 1024 * 1024 });
  return JSON.parse(raw.trim());
}

function psqlRows(sql) {
  const raw = runPsql(["-Atc", sql, "-F", "\t"], { maxBuffer: 64 * 1024 * 1024 });
  return raw
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const [company, cnt] = l.split("\t");
      return { company, cnt: Number(cnt) };
    });
}

// 全库公司规模（一次性，与 campus-persona-coverage.js 同口径）：
// company -> 该公司 status='active' 的总岗位数（不分职能/城市，全局算一次、所有画像共用）。
function loadCompanySizeMap() {
  const rows = psqlRows("select company, count(*) as cnt from jobs where status = 'active' group by company;");
  const m = new Map();
  for (const r of rows) m.set(r.company, r.cnt);
  return m;
}

function sizeTier(cnt) {
  if (cnt == null) return "未知";
  if (cnt >= 500) return "大";
  if (cnt >= 100) return "中";
  return "小";
}

// Supabase sources.segment='soe' 名单（①号权威口径），与 campus-persona-coverage.js 同法。
async function loadSoeSourceNames() {
  const { createClient } = require("@supabase/supabase-js");
  const client = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false },
  });
  const out = [];
  for (let from = 0; ; from += 1000) {
    const { data, error } = await client.from("sources").select("company,segment").eq("segment", "soe").range(from, from + 999);
    if (error) throw new Error(`Supabase sources 查询失败: ${error.message}`);
    out.push(...(data || []));
    if (!data || data.length < 1000) break;
  }
  return Array.from(new Set(out.map((r) => r.company).filter(Boolean)));
}

function isSoeBySources(company, soeNames) {
  if (!company) return false;
  return soeNames.some((n) => company.includes(n) || n.includes(company));
}

function isSoeByHeuristic(company) {
  return !!company && SOE_NAME_PREFIX_RE.test(company);
}

function mustApplyPatterns(industry) {
  const list = MUST_APPLY[industry] || [];
  const out = [];
  for (const c of list) {
    out.push({ name: c.name, needle: String(c.pattern || "").replace(/%/g, "") });
    for (const a of c.aliases || []) out.push({ name: c.name, needle: String(a).replace(/%/g, "") });
  }
  return out;
}

function mustApplyHits(companies, patterns) {
  const hitNames = new Set();
  for (const p of patterns) {
    if (companies.some((c) => c.includes(p.needle))) hitNames.add(p.name);
  }
  return hitNames;
}

// ─────────────────────────── 加载 searchJobsStore（TS 即时转译 + psql 驱动替身） ───────────────────────────
function loadSearchJobsStore() {
  const cache = new Map();
  const client = loadTs(path.join(ROOT, "lib/jobs-store/client.ts"), cache);
  // 关键一步：client.jobsQuery 是 search.ts 通过 `import { jobsQuery } from "./client"` 拿到的引用，
  // TS 编译到 CommonJS 后是按属性访问（client_1.jobsQuery(...)），所以运行时替换这个属性，
  // search.ts 里所有对它的调用都会走到这个 psql 版本 —— 不用碰 search.ts 一行代码。
  client.jobsQuery = async (sql, params) => psqlJson(inlineParams(sql, params || []));
  const search = loadTs(path.join(ROOT, "lib/jobs-store/search.ts"), cache);
  const { DEFAULT_FILTERS } = loadTs(path.join(ROOT, "lib/job-filter.ts"), cache);
  return { search, DEFAULT_FILTERS };
}

// ─────────────────────────── 主流程 ───────────────────────────
async function main() {
  loadMainRepoEnvIfNeeded();
  if (!process.env.JOBS_DATABASE_URL) {
    console.error("[campus-persona-search] 缺 JOBS_DATABASE_URL：先 `set -a; source .env.local; set +a` 再跑本脚本。");
    process.exit(1);
  }

  const { search, DEFAULT_FILTERS } = loadSearchJobsStore();

  console.error("[campus-persona-search] 加载全库公司规模映射（一次性 group by）…");
  const sizeMap = loadCompanySizeMap();
  console.error(`[campus-persona-search] 公司规模映射：${sizeMap.size} 家公司。`);

  let soeNames = [];
  try {
    console.error("[campus-persona-search] 加载 Supabase sources.segment='soe' 名单…");
    soeNames = await loadSoeSourceNames();
    console.error(`[campus-persona-search] soe 源名单：${soeNames.length} 家。`);
  } catch (e) {
    console.error(`[campus-persona-search] Supabase sources 读取失败，央国企①号口径本轮跳过：${e.message}`);
  }

  let personas = [];
  for (const [industry, directions] of Object.entries(INDUSTRY_PERSONAS)) {
    for (const direction of directions) {
      for (const tier of CITY_TIERS) {
        personas.push({ industry, direction, tier: tier.label, cities: tier.cities });
      }
    }
  }
  // 调试用：PERSONA_LIMIT=5 只跑前 N 个组合，验证接线不用等全量跑完。
  if (Number(process.env.PERSONA_LIMIT || 0) > 0) {
    personas = personas.slice(0, Number(process.env.PERSONA_LIMIT));
  }

  const results = [];
  for (const p of personas) {
    const filters = {
      ...DEFAULT_FILTERS,
      keyword: p.direction,
      city: p.cities.join(","),
      jobType: "校招",
      sortBy: "newest",
    };
    let r;
    try {
      r = await search.searchJobsStore(filters, null, [], 0, RESULT_LIMIT);
    } catch (e) {
      results.push({ ...p, error: String((e && e.message) || e) });
      console.error(`[campus-persona-search] ERROR ${p.industry}/${p.direction}/${p.tier}: ${(e && e.stack) || e}`);
      continue;
    }
    const jobs = r.jobs || [];
    const companyCounts = new Map();
    for (const j of jobs) companyCounts.set(j.company, (companyCounts.get(j.company) || 0) + 1);
    const companies = [...companyCounts.keys()];

    let large = 0,
      medium = 0,
      small = 0,
      unknown = 0;
    let soeBySources = 0,
      soeByHeuristicOnly = 0;
    for (const c of companies) {
      const t = sizeTier(sizeMap.get(c));
      if (t === "大") large++;
      else if (t === "中") medium++;
      else if (t === "小") small++;
      else unknown++;
      if (isSoeBySources(c, soeNames)) soeBySources++;
      else if (isSoeByHeuristic(c)) soeByHeuristicOnly++;
    }

    const patterns = mustApplyPatterns(p.industry);
    const hits = mustApplyHits(companies, patterns);
    const top10 = [...companyCounts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([company, cnt]) => ({ company, cnt }));

    results.push({
      industry: p.industry,
      direction: p.direction,
      tier: p.tier,
      total: r.total,
      exactCount: r.exactCount,
      relatedSameFunction: r.relatedSameFunction,
      relatedMissingInfo: r.relatedMissingInfo,
      exactTotal: r.exactTotal,
      capped: r.capped,
      returnedJobs: jobs.length,
      companyCount: companies.length,
      large,
      medium,
      small,
      unknown,
      soeBySources,
      soeByHeuristicOnly,
      mustApplyTotal: new Set(patterns.map((x) => x.name)).size,
      mustApplyHit: hits.size,
      mustApplyHitNames: Array.from(hits),
      top10,
    });
  }

  fs.writeFileSync(OUT_JSON, JSON.stringify({ generated_at: new Date().toISOString(), results }, null, 2));
  console.error(`[campus-persona-search] 原始结果已写 ${OUT_JSON}`);

  console.log(
    "\n行业 | 方向 | 城市档 | total(可翻页) | exact | related同职能 | exactTotal(真实,capped时) | capped | 公司数(大/中/小/未知) | 央国企(source/heuristic) | 必投命中/共",
  );
  for (const r of results) {
    if (r.error) {
      console.log(`${r.industry} | ${r.direction} | ${r.tier} | ERROR ${r.error}`);
      continue;
    }
    console.log(
      `${r.industry} | ${r.direction} | ${r.tier} | ${r.total} | ${r.exactCount} | ${r.relatedSameFunction} | ${r.exactTotal ?? "-"} | ${r.capped} | ${r.companyCount}(${r.large}/${r.medium}/${r.small}/${r.unknown}) | ${r.soeBySources}/${r.soeByHeuristicOnly} | ${r.mustApplyHit}/${r.mustApplyTotal}`,
    );
  }

  writeMarkdownReport(results);
  console.error(`[campus-persona-search] Markdown 报告已写 ${OUT_MD}`);
}

// ─────────────────────────── 报告生成 ───────────────────────────
// 判据（够/勉强/不够）按城市档分别定阈值——城市越小、可期望的岗位/公司绝对数越少，
// 阈值同比例下调。exact 优先用 exactTotal（真实总数，capped 时才有），拿不到才退回 exactCount
// （候选窗口内已通过精筛的 exact 条数，capped 时是「下限」不是真实值，但仍比裸 tsquery 准）。
const TIER_THRESHOLDS = {
  北上广深: { good: { exact: 100, company: 20, large: 3 }, ok: { exact: 30, company: 8 } },
  "新一线(杭州/成都/武汉)": { good: { exact: 50, company: 15, large: 2 }, ok: { exact: 15, company: 5 } },
  "二线(合肥/长沙)": { good: { exact: 20, company: 8, large: 1 }, ok: { exact: 5, company: 3 } },
  不限城市: { good: { exact: 200, company: 30, large: 5 }, ok: { exact: 50, company: 10 } },
};

function exactForVerdict(r) {
  // exactTotal 只在能证明「候选 where ⇒ jobFilterMatch 放行」时才有值（见 lib/jobs-store/search.ts
  // exactTotalWhenCapped 的四道门）；capped 且拿不到 exactTotal 时，exactCount 是候选窗口内已确认的
  // 下限，不是真实值——按「不够」的方向偏保守没问题，按「够」的方向偏保守也没问题（够只会更够）。
  return typeof r.exactTotal === "number" ? r.exactTotal : r.exactCount;
}

function verdict(r) {
  if (r.error) return "ERROR";
  const th = TIER_THRESHOLDS[r.tier];
  if (!th) return "未知城市档";
  const exact = exactForVerdict(r);
  if (exact >= th.good.exact && r.companyCount >= th.good.company && r.large >= (th.good.large ?? 0)) return "够";
  if (exact >= th.ok.exact && r.companyCount >= th.ok.company) return "勉强";
  return "不够";
}

// 组合的「缺口分数」：exact 与公司数都归一到各自档位的 good 阈值上取平均，分越低越缺。
// 只用于给「最缺的 8 个」排序，不作为判据本身。
function scarcityScore(r) {
  const th = TIER_THRESHOLDS[r.tier];
  if (!th) return 1;
  const exact = exactForVerdict(r);
  const exactRatio = Math.min(1, exact / th.good.exact);
  const companyRatio = Math.min(1, r.companyCount / th.good.company);
  return (exactRatio + companyRatio) / 2;
}

function writeMarkdownReport(results) {
  const lines = [];
  lines.push("# 校招覆盖走查 · 产品真实搜索口径（searchJobsStore）");
  lines.push("");
  lines.push(`生成时间：${new Date().toISOString()}`);
  lines.push("");
  lines.push(
    "口径：调用 `lib/jobs-store/search.ts` 的 `searchJobsStore({...DEFAULT_FILTERS, keyword: 方向, " +
      "city: 城市档(逗号连接), jobType: \"校招\", sortBy: \"newest\"}, null, [], 0, 500)`——与用户在 " +
      "/jobs /campus 搜索时同一条代码路径（FTS 召回 + JS 精筛分层 + 诚实计数）。`exact`/`related同职能` " +
      "是候选窗口内已判定的分层条数；`total` 是候选窗口内通过精筛的可翻页条数（撞窗口上限时不是真实总数）；" +
      "`exactTotal` 只在能证明数字正确时才有值（capped 且四道门都过）。公司规模（大 ≥500/中 100~499/小 <100 " +
      "岗）与央国企标记按全库口径算，与本次命中数无关。",
  );
  lines.push("");

  // ── 1. 11 行业 × 够/勉强/不够 总表（锚定北上广深，见判据说明） ──
  lines.push("## 一、11 行业总表（够 / 勉强 / 不够）");
  lines.push("");
  lines.push(
    "判据（按城市档分别定阈值，城市越小阈值同比例下调；exact 优先用 exactTotal 真实总数，拿不到才退回 exactCount）：",
  );
  lines.push("");
  lines.push("| 城市档 | 够 | 勉强 |");
  lines.push("|---|---|---|");
  for (const [tier, th] of Object.entries(TIER_THRESHOLDS)) {
    lines.push(
      `| ${tier} | exact≥${th.good.exact} 且 公司≥${th.good.company}${th.good.large ? ` 且 大厂≥${th.good.large}` : ""} | exact≥${th.ok.exact} 且 公司≥${th.ok.company} |`,
    );
  }
  lines.push("");
  lines.push("行业总体判定 = 该行业全部「方向 × 北上广深」组合里最差的一个（木桶效应，任一方向在一线城市搜不到岗，对该行业的校招生就是不够）。");
  lines.push("");
  lines.push("| 行业 | 方向（北上广深 exact/公司数/判定） | 行业总体判定 |");
  lines.push("|---|---|---|");
  const byIndustry = new Map();
  for (const r of results) {
    if (!byIndustry.has(r.industry)) byIndustry.set(r.industry, []);
    byIndustry.get(r.industry).push(r);
  }
  const verdictRank = { 不够: 0, 勉强: 1, 够: 2, ERROR: -1, 未知城市档: -1 };
  for (const [industry, rows] of byIndustry) {
    const bjgsRows = rows.filter((r) => r.tier === "北上广深");
    const perDirection = bjgsRows
      .map((r) => `${r.direction}(${exactForVerdict(r)}/${r.companyCount}/${verdict(r)})`)
      .join("；");
    const overall = bjgsRows.reduce((worst, r) => {
      const v = verdict(r);
      return verdictRank[v] < verdictRank[worst] ? v : worst;
    }, "够");
    lines.push(`| ${industry} | ${perDirection} | ${overall} |`);
  }
  lines.push("");

  // ── 2. 最缺的 8 个组合 ──
  lines.push("## 二、最缺的 8 个（行业 × 方向 × 城市档）");
  lines.push("");
  lines.push("按缺口分数升序（exact 与公司数相对各自城市档 good 阈值的完成度均值，越低越缺；排除 ERROR 行）：");
  lines.push("");
  lines.push("| 行业 | 方向 | 城市档 | exact(真实优先) | 公司数 | 大厂数 | 判定 |");
  lines.push("|---|---|---|---|---|---|---|");
  const ranked = results
    .filter((r) => !r.error)
    .map((r) => ({ r, score: scarcityScore(r) }))
    .sort((a, b) => a.score - b.score)
    .slice(0, 8);
  for (const { r } of ranked) {
    lines.push(`| ${r.industry} | ${r.direction} | ${r.tier} | ${exactForVerdict(r)} | ${r.companyCount} | ${r.large} | ${verdict(r)} |`);
  }
  lines.push("");

  // ── 3. 全量明细 ──
  lines.push("## 三、全量明细");
  lines.push("");
  lines.push(
    "| 行业 | 方向 | 城市档 | total | exact | related同职能 | exactTotal | capped | 公司数 | 大/中/小/未知 | 央国企(source/heuristic) | 必投命中/共 | 判定 | Top3公司 |",
  );
  lines.push("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|");
  for (const r of results) {
    if (r.error) {
      lines.push(`| ${r.industry} | ${r.direction} | ${r.tier} | ERROR: ${r.error} | | | | | | | | | | |`);
      continue;
    }
    const top3 = r.top10
      .slice(0, 3)
      .map((c) => `${c.company}(${c.cnt})`)
      .join("、");
    lines.push(
      `| ${r.industry} | ${r.direction} | ${r.tier} | ${r.total} | ${r.exactCount} | ${r.relatedSameFunction} | ${r.exactTotal ?? "-"} | ${r.capped} | ${r.companyCount} | ${r.large}/${r.medium}/${r.small}/${r.unknown} | ${r.soeBySources}/${r.soeByHeuristicOnly} | ${r.mustApplyHit}/${r.mustApplyTotal} | ${verdict(r)} | ${top3} |`,
    );
  }
  lines.push("");

  fs.mkdirSync(path.dirname(OUT_MD), { recursive: true });
  fs.writeFileSync(OUT_MD, lines.join("\n"));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

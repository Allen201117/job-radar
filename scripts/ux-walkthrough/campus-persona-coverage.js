#!/usr/bin/env node
// 校招覆盖走查（2026-09-18，创始人问「各行各业校招覆盖到底够不够，中型/大型/央国企都支持了吗」）：
// 用 10 个行业（lib/must-apply-list.json 的行业键，教育除外）× 每行业 2~3 个典型校招方向 ×
// 3 个城市档（北上广深 / 杭州成都武汉 / 合肥长沙）+「不限城市」对照，逐个查香港 jobs 库，
// 回答「这类学生打开 /campus 或搜方向词，能不能搜到岗、公司够不够大/够不够正规」。
//
// SQL 口径（与创始人给的一致，不做额外发挥）：
//   校招岗 = status='active' and recruitment_category='校招'
//          and search_doc @@ to_tsquery('simple', <方向词 ftsCandidateTerms 展开>)
//          and (location ilike '%城市1%' or location ilike '%城市2%' or ...)   -- 不限城市档不加这条
//   公司规模 = 该 company 字符串在全库 status='active' 的岗位总数（与本 persona 命中数无关，
//              是「这家公司在我们库里整体有多厚」，全局算一次、所有 persona 共用）：
//              大 ≥500 / 中 100~499 / 小 <100。
//   央国企判据（创始人原话「sources.segment='soe' 或公司名含 中国/集团/国 等——写明判据」）：
//     ① Supabase sources 表 segment='soe' 的公司名，与 jobs.company 做双向子串匹配 —— 权威但覆盖有限
//        （sources 是抓取源清单，不是全部命中公司都在里面）；
//     ② 名字以 中国/国家/中央/中远/中核/中化/中粮/中煤/中铝/中建/中铁/中交/中冶/华能/大唐/华电/
//        国家电网/南方电网 开头 —— 启发式，会有假阳性/假阴性，仅当①查不到时作为补充信号，
//        报告里两个口径分开写，不合并成一个数字冒充精确统计。
//   必投交集 = lib/must-apply-list.json 该行业下的 pattern（去掉 % 后子串），命中 persona 结果里
//              任意一家 company 即算「通」，不看命中岗位数门槛。
//
// ⚠️ 已知局限（如实写不藏）：
//   - company 字段未做归属合并，同一家公司的分公司/子品牌可能被算成两行，规模桶因此可能偏保守。
//   - 央国企②号启发式对「XX集团」这类泛用词故意不收（会把美的集团、小米集团这类私企集团也算进去），
//     宁可漏判几家真央企，也不要把「集团」当判据制造假阳性——这是本文件唯一不照抄创始人原话的地方，
//     原因写在这条注释里，不是偷偷改。
//   - 必投交集只做「pattern 去 % 子串」匹配，没有实现 lib/must-apply-list.ts 的 parentPattern/brandTokens
//     精细归属逻辑，边界案例（如「网商银行」母公司是蚂蚁）可能被判成两家或漏判一家。
//
// 跑法（需要能访问 JOBS_DATABASE_URL 与 SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY 的会话执行，
// 本脚本自身不读取 .env.local，由调用方的 shell 先 source 好）：
//   cd <项目根>
//   set -a; source .env.local; set +a
//   node scripts/ux-walkthrough/campus-persona-coverage.js                # 跑全量、打印 + 写 md 报告
//   node scripts/ux-walkthrough/campus-persona-coverage.js --dry-run      # 不连库，只打印生成的 SQL/tsquery，供 review
//   CAMPUS_COVERAGE_OUT=/path/to/report.md node scripts/ux-walkthrough/campus-persona-coverage.js
"use strict";
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = path.join(__dirname, "..", "..");
const { loadTs } = require(path.join(ROOT, "tests/_load-ts.js"));
const { ftsCandidateTerms } = require(path.join(ROOT, "lib/china-keyword-expansion.js"));
const { buildTsquery } = loadTs(path.join(ROOT, "lib/job-search.ts"));
const MUST_APPLY = require(path.join(ROOT, "lib/must-apply-list.json"));

const OUT_PATH = process.env.CAMPUS_COVERAGE_OUT ||
  path.join(__dirname, "campus-persona-coverage-raw.json");
const DRY_RUN = process.argv.includes("--dry-run");

// 10 个行业 × 2~3 个典型校招方向（创始人在任务里给的例子，逐字照抄，不自行发挥换词）。
// 键必须与 lib/must-apply-list.json 的行业键完全一致（教育行业创始人没给方向例子，本轮不跑）。
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

// 央国企②号启发式：只收明确的央企品牌前缀，不收「集团」这种泛用词（原因见文件头注释）。
const SOE_NAME_PREFIX_RE = /^(中国|国家电网|南方电网|国家能源|国家开发|中央|中远|中核|中化|中粮|中煤|中铝|中建|中铁|中交|中冶|华能|大唐|华电|中投)/;

function escSqlLiteral(s) {
  return String(s).replace(/'/g, "''");
}

function buildDirectionTsquery(direction) {
  // PERSONA_NARROW=1：只用方向短语本身（不做词表扩展）。扩展版会把「工程师」这类泛词一并算进来，
  // 机械/工艺/设备/化工/电气/土木工程师在同一城市档会得到几乎相同的岗数与公司数（2026-09-18 实测），
  // 看覆盖时两列都要看：宽 = 产品实际召回口径，窄 = 该方向真实存在的岗。
  const terms = process.env.PERSONA_NARROW ? [direction] : ftsCandidateTerms(direction);
  return buildTsquery(terms, [], []);
}

function buildPersonaSql(tsquery, cities) {
  const where = [
    "status = 'active'",
    "recruitment_category = '校招'",
    `search_doc @@ to_tsquery('simple', '${escSqlLiteral(tsquery)}')`,
  ];
  if (cities.length) {
    const orList = cities.map((c) => `location ilike '%${escSqlLiteral(c)}%'`).join(" or ");
    where.push(`(${orList})`);
  }
  return `select company, count(*) as cnt from jobs where ${where.join(" and ")} group by company order by cnt desc;`;
}

function psqlRows(sql) {
  const raw = execFileSync(
    "psql",
    [process.env.JOBS_DATABASE_URL, "-Atc", sql, "-F", "\t"],
    { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );
  return raw
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const [company, cnt] = l.split("\t");
      return { company, cnt: Number(cnt) };
    });
}

// 全库公司规模（一次性）：company -> 该公司 status='active' 的总岗位数（不分职能/城市）。
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

// Supabase sources.segment='soe' 名单（① 号权威口径）。用 supabase-js，与 walkthrough.js 同法。
async function loadSoeSourceNames() {
  const { createClient } = require("@supabase/supabase-js");
  const client = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY, { auth: { persistSession: false } });
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

async function main() {
  const personas = [];
  for (const [industry, directions] of Object.entries(INDUSTRY_PERSONAS)) {
    for (const direction of directions) {
      const tsquery = buildDirectionTsquery(direction);
      for (const tier of CITY_TIERS) {
        personas.push({ industry, direction, tier: tier.label, cities: tier.cities, tsquery });
      }
    }
  }

  if (DRY_RUN) {
    console.log(`共 ${personas.length} 个画像组合。逐个打印 tsquery + SQL（不连库）：\n`);
    for (const p of personas) {
      if (!p.tsquery) { console.log(`[跳过：ftsCandidateTerms("${p.direction}") 没展开出候选词] ${p.industry} / ${p.direction} / ${p.tier}`); continue; }
      console.log(`-- ${p.industry} / ${p.direction} / ${p.tier}\n${buildPersonaSql(p.tsquery, p.cities)}\n`);
    }
    return;
  }

  if (!process.env.JOBS_DATABASE_URL) {
    console.error("[campus-persona-coverage] 缺 JOBS_DATABASE_URL：先 `set -a; source .env.local; set +a` 再跑本脚本。");
    process.exit(1);
  }

  console.error(`[campus-persona-coverage] 加载全库公司规模映射（一次性 group by）…`);
  const sizeMap = loadCompanySizeMap();
  console.error(`[campus-persona-coverage] 公司规模映射：${sizeMap.size} 家公司。`);

  let soeNames = [];
  try {
    console.error(`[campus-persona-coverage] 加载 Supabase sources.segment='soe' 名单…`);
    soeNames = await loadSoeSourceNames();
    console.error(`[campus-persona-coverage] soe 源名单：${soeNames.length} 家。`);
  } catch (e) {
    console.error(`[campus-persona-coverage] Supabase sources 读取失败，央国企①号口径本轮跳过：${e.message}`);
  }

  const results = [];
  for (const p of personas) {
    if (!p.tsquery) { results.push({ ...p, error: "ftsCandidateTerms 没展开出候选词" }); continue; }
    const sql = buildPersonaSql(p.tsquery, p.cities);
    let rows;
    try {
      rows = psqlRows(sql);
    } catch (e) {
      results.push({ ...p, error: `psql 失败: ${e.message}` });
      continue;
    }
    const totalJobs = rows.reduce((s, r) => s + r.cnt, 0);
    const companies = rows.map((r) => r.company);
    let large = 0, medium = 0, small = 0, unknown = 0;
    let soeBySources = 0, soeByHeuristicOnly = 0;
    for (const c of companies) {
      const t = sizeTier(sizeMap.get(c));
      if (t === "大") large++; else if (t === "中") medium++; else if (t === "小") small++; else unknown++;
      if (isSoeBySources(c, soeNames)) soeBySources++;
      else if (isSoeByHeuristic(c)) soeByHeuristicOnly++;
    }
    const patterns = mustApplyPatterns(p.industry);
    const hits = mustApplyHits(companies, patterns);
    results.push({
      ...p,
      totalJobs,
      companyCount: companies.length,
      large, medium, small, unknown,
      soeBySources, soeByHeuristicOnly,
      mustApplyTotal: new Set(patterns.map((x) => x.name)).size,
      mustApplyHit: hits.size,
      mustApplyHitNames: Array.from(hits),
      top10: rows.slice(0, 10),
    });
  }

  fs.writeFileSync(OUT_PATH, JSON.stringify({ generated_at: new Date().toISOString(), results }, null, 2));
  console.error(`[campus-persona-coverage] 原始结果已写 ${OUT_PATH}`);

  console.log("\n行业 | 方向 | 城市档 | 校招岗数 | 公司数(大/中/小/未知) | 央国企(source/heuristic) | 必投命中/共");
  for (const r of results) {
    if (r.error) { console.log(`${r.industry} | ${r.direction} | ${r.tier} | ERROR ${r.error}`); continue; }
    console.log(`${r.industry} | ${r.direction} | ${r.tier} | ${r.totalJobs} | ${r.companyCount}(${r.large}/${r.medium}/${r.small}/${r.unknown}) | ${r.soeBySources}/${r.soeByHeuristicOnly} | ${r.mustApplyHit}/${r.mustApplyTotal}`);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });

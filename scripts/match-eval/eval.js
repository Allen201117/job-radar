#!/usr/bin/env node
// 岗位推荐「方向准确性」端到端评测器 —— stage-1 真实召回 SQL + stage-2 真实匹配引擎。
//
// 为什么要有它：匹配准确性是本产品的核心指标，而**单测发现不了这类问题**。
// 本轮六个根因（技能词当方向词、AI 领域词混进算法组、移动端混进前端组、研发巨桶内互串、
// 残差把职级后缀当硬条件、召回池被泛词稀释）全部是靠真实库对拍抓到的，单测一个都没报警——
// 因为每条规则单独看都"符合预期"，只有喂真实岗位才看得出组合起来把方向带偏了。
//
// 跑法（需要 JOBS_DATABASE_URL 与本机 psql）：
//   set -a; source .env.local; set +a
//   node scripts/match-eval/eval.js                 # 只跑匹配，输出各画像展示岗位与职能分布
//   node scripts/match-eval/judge.js                # 再跑 LLM 裁判，输出方向准确率（需 SILICONFLOW_API_KEY）
//
// 两个维度是刻意分开的（对应两类真实输入）：
//   A = 后端/结构化输入：只给干净的目标岗位 + 城市。反映「匹配器本身」的能力上限。
//   B = 前端/简历画像输入：完全等同用户传简历后真实落库的 user_preferences + candidate_profiles
//       （含 LLM 解析出的十几个技能词）。反映「用户真实体验到」的准确率。
//   B 明显低于 A = 简历解析产出的画像在污染匹配（本轮修复前差 5.3 个点，修复后 0.7 个点）。
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = process.env.EVAL_ROOT || path.join(__dirname, "..", "..");
const { loadTs } = require(path.join(ROOT, "tests/_load-ts.js"));
const L = (rel) => loadTs(path.join(ROOT, rel));

const { buildRecallSql, stripTierColumns, RECALL_BUDGET } = L("lib/jobs-store/opportunities.ts");
const { buildRadarProfile } = L("lib/opportunities/profile.ts");
const { computeMatchFacts, checkEligibility } = L("lib/opportunities/eligibility.ts");
const { scoreOpportunity } = L("lib/opportunities/scoring.ts");
const { classifyJobFunction } = require(path.join(ROOT, "lib/china-keyword-expansion.js"));

// buildRecallSql 产出的是参数化 SQL，psql 不方便传数组参数 → 内联成字面量。
// 只在本地评测脚本里这么干，生产路径永远走参数化（见 lib/jobs-store/client.ts）。
function lit(v) {
  if (v === null || v === undefined) return "null";
  if (typeof v === "number") return String(v);
  if (Array.isArray(v)) {
    if (!v.length) return "'{}'";
    if (typeof v[0] === "number") return `array[${v.map(String).join(",")}]::float[]`;
    return `array[${v.map((x) => "'" + String(x).replace(/'/g, "''") + "'").join(",")}]`;
  }
  return "'" + String(v).replace(/'/g, "''") + "'";
}

function inlineParams(sql, params) {
  // 从大到小替换，否则 $1 会先吃掉 $10 的前缀
  let out = sql;
  for (let i = params.length; i >= 1; i--) out = out.split("$" + i).join(lit(params[i - 1]));
  return out;
}

function psqlJson(sql) {
  const url = process.env.JOBS_DATABASE_URL;
  if (!url) throw new Error("JOBS_DATABASE_URL 未配置（先 source .env.local）");
  const wrapped = `select coalesce(json_agg(t), '[]'::json)::text from (${sql}) t`;
  const raw = execFileSync("psql", [url, "-t", "-A", "-c", wrapped], {
    maxBuffer: 512 * 1024 * 1024,
    encoding: "utf8",
  });
  return JSON.parse(raw.trim());
}

function runOne(label, prefs, candidate, opts = {}) {
  const profile = buildRadarProfile("eval-user", prefs, candidate);
  const now = new Date();
  const since = new Date(now.getTime() - 30 * 86400000).toISOString();
  const built = buildRecallSql(profile, since, RECALL_BUDGET, []);
  if (!built) return { label, error: "no_recall" };

  const rows = stripTierColumns(psqlJson(inlineParams(built.sql, built.params)));
  const filtered = {};
  const shown = [];
  for (const job of rows) {
    // sources 元信息在 Supabase，本地评测取不到 → 传 undefined（freshness 按无 crawl_method 判）。
    let facts = computeMatchFacts(job, profile, undefined, { primary: null, viewed: false }, now);
    if (opts.ignoreFreshness && (facts.freshness === "stale" || facts.freshness === "unknown")) {
      facts = { ...facts, freshness: "fresh" };
    }
    const elig = checkEligibility(facts);
    if (!elig.eligible) {
      filtered[elig.reason] = (filtered[elig.reason] || 0) + 1;
      continue;
    }
    const { score, tier } = scoreOpportunity(facts, elig.degraded);
    if (tier === null) {
      filtered.low_score = (filtered.low_score || 0) + 1;
      continue;
    }
    shown.push({
      id: job.id,
      title: job.title,
      company: job.company,
      location: job.location,
      score,
      tier,
      roleTier: facts.roleTier,
      roleMatchLabel: facts.roleMatchLabel,
      jobFn: classifyJobFunction(job),
      skillsHit: facts.skillsHit,
      summary: String(job.summary || "").slice(0, 200),
    });
  }
  shown.sort((a, b) => b.score - a.score);

  return {
    label,
    profile: {
      targetRoles: profile.targetRoles,
      targetKeywords: profile.targetKeywords,
      targetLocations: profile.targetLocations,
      targetIndustries: profile.targetIndustries,
      experienceStage: profile.experienceStage,
    },
    recalled: rows.length,
    filtered,
    shownCount: shown.length,
    shown,
  };
}

module.exports = { runOne };

if (require.main === module) {
  const profilesFile = process.env.PROFILES || path.join(__dirname, "parsed-profiles.json");
  if (!fs.existsSync(profilesFile)) {
    console.error(`缺少画像文件 ${profilesFile}\n先跑：node scripts/match-eval/parse-resumes.js`);
    process.exit(1);
  }
  const parsed = JSON.parse(fs.readFileSync(profilesFile, "utf8"));
  const ignoreFreshness = process.argv.includes("--ignore-freshness");
  const results = [];

  for (const r of parsed) {
    const p = r.profile;
    const pr = r.prefs;
    // 维度 A：后端 / 结构化输入 —— 只有干净的目标岗位 + 城市，不带简历技能词
    results.push(
      runOne(
        `A:${r.file}`,
        {
          target_roles: pr.target_roles,
          target_keywords: [],
          target_locations: pr.target_locations,
          target_companies: [],
          target_industries: [],
          exclude_keywords: [],
          daily_limit: 20,
        },
        null,
        { ignoreFreshness },
      ),
    );
    // 维度 B：前端 / 真实简历画像 —— 逐字等同简历上传后落库的偏好 + 档案
    results.push(
      runOne(
        `B:${r.file}`,
        {
          target_roles: pr.target_roles,
          target_keywords: pr.target_keywords,
          target_locations: pr.target_locations,
          target_companies: [],
          target_industries: pr.industries,
          exclude_keywords: [],
          experience_stage: p.experience_stage || null,
          daily_limit: 20,
        },
        {
          target_roles: p.target_roles,
          skills: p.skills,
          industries: p.industries,
          target_locations: p.target_locations,
          education: [],
          education_summary: p.education_summary,
          experience_stage: p.experience_stage,
          seniority: p.seniority,
        },
        { ignoreFreshness },
      ),
    );
  }

  fs.writeFileSync(path.join(__dirname, "eval-raw.json"), JSON.stringify(results, null, 2));
  for (const r of results) {
    if (r.error) {
      console.log(r.label, "ERROR", r.error);
      continue;
    }
    console.log(`\n### ${r.label}  召回=${r.recalled} 展示=${r.shownCount}`);
    console.log("   roles=", JSON.stringify(r.profile.targetRoles), " kw=", r.profile.targetKeywords.length);
    console.log("   filtered=", JSON.stringify(r.filtered));
    const fnDist = {};
    for (const s of r.shown) fnDist[s.jobFn] = (fnDist[s.jobFn] || 0) + 1;
    console.log("   展示岗位职能分布=", JSON.stringify(fnDist));
    console.log("   TOP10:");
    for (const s of r.shown.slice(0, 10)) {
      console.log(`     [${s.score}|${s.tier}|${s.jobFn}|${s.roleTier}] ${s.title} @ ${s.company}`);
    }
  }
  console.log(`\n结果已写入 ${path.join(__dirname, "eval-raw.json")}，跑 judge.js 得方向准确率。`);
}

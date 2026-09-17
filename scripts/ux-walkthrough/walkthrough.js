#!/usr/bin/env node
// 用户体验走查（2026-09-17 创始人定调）：**拿真实用户画像逐个模拟**，回答五个问题——
//   ① 推荐页有没有岗（召回 / 展示条数）
//   ② 方向准不准（展示岗职能 ∈ 用户职能 的占比；粗尺子，精尺子是 scripts/match-eval 的 LLM 裁判）
//   ③ 洞察库对他有没有用（他会看到的公司里，多少家有已发布洞察）
//   ④ 校招专区能不能用（校招/实习阶段用户：他行业的必投公司里，多少家校招渠道是通的）
//   ⑤ 接口卡不卡（匿名可测的 /api/jobs/search 冷路径 TTFB）
// 只读：不写任何用户数据；`--record` 时把汇总写进 ops_runs（module=ux_walkthrough）。
//
// 跑法（本机需 psql + JOBS_DATABASE_URL + SUPABASE_URL/SERVICE_ROLE_KEY）：
//   set -a; source .env.local; set +a
//   node scripts/ux-walkthrough/walkthrough.js            # 打印逐用户表 + 汇总，写 walkthrough-raw.json
//   node scripts/ux-walkthrough/walkthrough.js --record   # 同上 + 写 ops_runs
//   UX_WALK_LIMIT=10 …                                    # 只跑前 N 个用户
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { createClient } = require("@supabase/supabase-js");

const ROOT = path.join(__dirname, "..", "..");
const { runOne } = require(path.join(ROOT, "scripts/match-eval/eval.js"));
const { loadTs } = require(path.join(ROOT, "tests/_load-ts.js"));
const L = (rel) => loadTs(path.join(ROOT, rel));
const { classifyJobFunction } = require(path.join(ROOT, "lib/china-keyword-expansion.js"));
const { findCompanyProfile } = L("lib/insight-match.ts");
const { resolveMustApplyIndustries, MUST_APPLY_BY_INDUSTRY } = L("lib/must-apply-list.ts");

const SITE = process.env.UX_WALK_SITE || "https://www.myjobradar.top";
const CAMPUS_STAGES = new Set(["校招", "实习", "campus", "intern", "internship", "应届"]);
const TTFB_BAD_S = 8;      // 超过就算卡点
const DIRECTION_BAD = 0.7; // 前 20 张里方向命中低于 70% 算卡点

// 与 lib/campus-user-industries.companiesForIndustries 同口径（那个模块带 server-only，脚本里内联一份）
function companiesForIndustries(industries) {
  return Array.from(new Map(industries.flatMap((ind) => MUST_APPLY_BY_INDUSTRY[ind] || []).map((c) => [c.pattern, c])).values());
}

function sb() {
  return createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY, { auth: { persistSession: false } });
}

async function fetchAll(query, pageSize = 1000) {
  const out = [];
  for (let from = 0; ; from += pageSize) {
    const { data, error } = await query.range(from, from + pageSize - 1);
    if (error) throw new Error(error.message);
    out.push(...(data || []));
    if (!data || data.length < pageSize) break;
  }
  return out;
}

function ttfb(url) {
  try {
    const raw = execFileSync("curl", ["-s", "-o", "/dev/null", "-m", "60", "-w", "%{time_starttransfer} %{http_code}", url], { encoding: "utf8" });
    const [t, code] = raw.trim().split(" ");
    return { seconds: Number(t), http: Number(code) };
  } catch {
    return { seconds: null, http: null };
  }
}

function userFunctions(roles) {
  const set = new Set();
  for (const role of roles || []) {
    const fn = classifyJobFunction({ title: role });
    if (fn && fn !== "其他") set.add(fn);
  }
  return set;
}

const mask = (id) => String(id || "").slice(0, 8);
function median(xs) { const a = xs.filter(Number.isFinite).sort((x, y) => x - y); return a.length ? a[Math.floor(a.length / 2)] : null; }
function avg(xs) { const a = xs.filter(Number.isFinite); return a.length ? Number((a.reduce((s, x) => s + x, 0) / a.length).toFixed(3)) : null; }

async function main() {
  const client = sb();
  const limit = Number(process.env.UX_WALK_LIMIT || 0);
  const prefsRows = await fetchAll(client.from("user_preferences").select("*").order("updated_at", { ascending: false }));
  const profiles = await fetchAll(client.from("candidate_profiles").select("*"));
  const profileByUser = new Map(profiles.map((p) => [p.user_id, p]));
  const companyProfiles = await fetchAll(client.from("company_profiles").select("id,company,display_name,aliases"));
  const activeItems = await fetchAll(client.from("insight_items").select("company_id").eq("status", "active"));
  const insightCountByCompany = new Map();
  for (const it of activeItems) insightCountByCompany.set(it.company_id, (insightCountByCompany.get(it.company_id) || 0) + 1);
  const ledger = await fetchAll(client.from("must_apply_gap_attempts").select("company,pattern,campus_channel").eq("scope", "domestic"));
  const channelByPattern = new Map(ledger.map((r) => [r.pattern, r.campus_channel]));

  const users = prefsRows.filter((p) => Array.isArray(p.target_roles) && p.target_roles.length).slice(0, limit || undefined);
  const results = [];
  const startedAt = new Date().toISOString();
  for (const prefs of users) {
    const cand = profileByUser.get(prefs.user_id) || null;
    const label = mask(prefs.user_id);
    let rec;
    try { rec = runOne(label, prefs, cand); } catch (e) { results.push({ user: label, error: String(e.message || e) }); continue; }
    if (rec.error) { results.push({ user: label, error: rec.error, roles: prefs.target_roles }); continue; }
    const fns = userFunctions(prefs.target_roles);
    const shown = rec.shown || [];
    const top = shown.slice(0, 20);
    // 方向命中：只在「用户职能判得出 且 岗位职能判得出」的样本上算，判不出的（其他）不进分母——
    // 把「其他」算命中会把 100% 刷出来（第一版就是这么骗自己的）。
    const judged = fns.size ? top.filter((j) => j.jobFn && j.jobFn !== "其他") : [];
    const inFn = fns.size ? judged.filter((j) => fns.has(j.jobFn)).length : null;
    const companies = [...new Set(top.map((j) => j.company).filter(Boolean))];
    let withInsight = 0;
    for (const c of companies) {
      const prof = findCompanyProfile(companyProfiles, c);
      if (prof && (insightCountByCompany.get(prof.id) || 0) > 0) withInsight += 1;
    }
    const stage = String(prefs.experience_stage || (cand && cand.experience_stage) || "");
    let campus = null;
    if (CAMPUS_STAGES.has(stage)) {
      const industries = resolveMustApplyIndustries(prefs.target_industries || (cand && cand.industries) || []);
      const list = companiesForIndustries(industries);
      campus = { industries, listed: list.length, healthy: list.filter((c) => channelByPattern.get(c.pattern) === "healthy").length };
    }
    results.push({
      user: label, stage, roles: prefs.target_roles, cities: prefs.target_locations,
      recalled: rec.recalled, shown: shown.length,
      directionOk: inFn === null || !judged.length ? null : Number((inFn / judged.length).toFixed(2)),
      directionJudged: judged.length,
      filtered: rec.filtered,
      insightCompanies: companies.length, insightCovered: withInsight, campus,
      top3: top.slice(0, 3).map((j) => `${j.title} @ ${j.company}`),
    });
  }

  const latency = {
    search_match_default: ttfb(`${SITE}/api/jobs/search?sortBy=match&limit=10`),
    search_city: ttfb(`${SITE}/api/jobs/search?sortBy=match&limit=10&city=${encodeURIComponent("北京")}`),
    stats: ttfb(`${SITE}/api/jobs/stats`),
  };

  const ok = results.filter((r) => !r.error);
  const issues = [];
  for (const r of ok) {
    if (r.shown === 0) issues.push(`${r.user}：推荐页 0 岗（召回 ${r.recalled}，被拦原因 ${JSON.stringify(r.filtered)}）roles=${JSON.stringify(r.roles)}`);
    if (r.directionOk !== null && r.directionOk < DIRECTION_BAD) issues.push(`${r.user}：方向命中 ${Math.round(r.directionOk * 100)}%（roles=${JSON.stringify(r.roles)}）`);
    if (r.insightCompanies > 0 && r.insightCovered === 0) issues.push(`${r.user}：前 20 张卡的 ${r.insightCompanies} 家公司都没有洞察`);
    if (r.campus && r.campus.healthy === 0) issues.push(`${r.user}：校招用户，${r.campus.industries.join("/")} 必投 ${r.campus.listed} 家校招渠道全不通`);
  }
  for (const [k, v] of Object.entries(latency)) {
    if (v.seconds == null || v.http !== 200) issues.push(`接口 ${k} 失败（http=${v.http}）`);
    else if (v.seconds > TTFB_BAD_S) issues.push(`接口 ${k} TTFB ${v.seconds.toFixed(1)}s > ${TTFB_BAD_S}s`);
  }
  const campusUsers = ok.filter((r) => r.campus);
  const summary = {
    users: ok.length, errors: results.length - ok.length,
    zero_shown: ok.filter((r) => r.shown === 0).length,
    median_shown: median(ok.map((r) => r.shown)),
    direction_ok_avg: avg(ok.map((r) => r.directionOk).filter((x) => x !== null)),
    insight_coverage_avg: avg(ok.filter((r) => r.insightCompanies > 0).map((r) => r.insightCovered / r.insightCompanies)),
    campus_users: campusUsers.length,
    campus_zero_healthy: campusUsers.filter((r) => r.campus.healthy === 0).length,
    campus_healthy_ratio_avg: avg(campusUsers.map((r) => r.campus.healthy / Math.max(1, r.campus.listed))),
    latency, issues: issues.length,
  };

  console.log("\n用户 | 阶段 | 召回 | 展示 | 方向命中 | 洞察覆盖 | 校招通/必投 | TOP1");
  for (const r of results) {
    if (r.error) { console.log(`${r.user} | ERROR ${r.error} roles=${JSON.stringify(r.roles)}`); continue; }
    console.log(`${r.user} | ${r.stage || "-"} | ${r.recalled} | ${r.shown} | ${r.directionOk === null ? "-" : Math.round(r.directionOk * 100) + "%"} | ${r.insightCovered}/${r.insightCompanies} | ${r.campus ? r.campus.healthy + "/" + r.campus.listed : "-"} | ${r.top3[0] || "-"}`);
  }
  console.log("\n汇总:", JSON.stringify(summary, null, 1));
  console.log("\n卡点（" + issues.length + "）:");
  for (const i of issues) console.log("  - " + i);
  fs.writeFileSync(path.join(__dirname, "walkthrough-raw.json"), JSON.stringify({ started_at: startedAt, summary, results, issues }, null, 2));

  if (process.argv.includes("--record")) {
    const { error } = await client.from("ops_runs").insert({
      module: "ux_walkthrough", run_date: startedAt.slice(0, 10),
      status: issues.length ? "partial" : "success",
      started_at: startedAt, finished_at: new Date().toISOString(),
      metrics: { ...summary, issue_samples: issues.slice(0, 20) },
    });
    if (error) console.error("[ux-walkthrough] ops_runs 写入失败:", error.message); else console.log("[ux-walkthrough] ops_runs 已记录");
  }
}

main().catch((e) => { console.error(e); process.exit(1); });

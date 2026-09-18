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
const ROLE_MISMATCH_RATIO_BAD = 0.5; // 候选里因方向不符被拦的占比超过它算卡点（待校准，2026-09-18 首次引入）

// ⚠️ 有限枚举：每个 type 必须对应代码里真实存在的判定（不是发明的假设）。metrics.issues_by_type
// 恒含全部键（含 0），"真的是 0" 与 "这轮没测到" 分得开——阈值/判定逻辑变了，先改这里的注释再改代码。
const ISSUE_TYPES = {
  zero_shown: { label: "推荐页零岗（非求职范围错配）" },
  scope_mismatch: { label: "求职范围错配：选了海外但城市全国内又没有英文简历" },
  direction_low: { label: "展示岗位方向命中率偏低" },
  role_input_format: { label: "用户填的岗位方向写法没被识别（一栏里塞了多个岗位名）" },
  role_mismatch_high: { label: "候选里因方向不符被拦掉的占比偏高" },
  insight_uncovered: { label: "他会看到的公司里，一家有职业洞察的都没有" },
  campus_channel_broken: { label: "校招/实习用户，所属行业必投公司的校招渠道全不通" },
  api_latency: { label: "接口响应慢或失败" },
};

// user=null 用于非按用户归因的 issue（如接口延迟——它归因于某个接口，不是某个用户）；
// 这类 issue 用 extra.metric 标出真正的归因对象，text 不拼 "null：" 前缀。
function mkIssue(type, user, detail, extra) {
  const meta = ISSUE_TYPES[type];
  if (!meta) throw new Error(`未登记的 issue type: ${type}`);
  const text = user == null ? detail : `${user}：${detail}`;
  return { type, user, detail, text, ...(extra || {}) };
}

// 用户手填岗位方向时常见的写法坑：一个 role 字符串里塞了多个岗位名，用中文/英文分隔符或
// 空格隔开（如 "销售；采购"、"销售 管培 运营"）。分词/匹配逻辑本身不归这个脚本管，这里只做
// 检测与归类，供后续统一算一次「有多少用户受影响」。
// 2026-09-18 返工：初版「空白/斜杠恒切」在全量真实 target_roles 上实测 30 条里 21 条误报
// （"AI 产品经理" "Spring Boot" "UI/UX设计师"…全被判成多岗位）。全量对拍出的规律——
// 真问题全是「汉字—分隔符—汉字」，误报全是英文/缩写紧邻分隔符。所以：
// ① ；;，,、 这几个硬分隔符恒切（不含歧义，从不出现在正常职位名里）；
// ② 空白 / 斜杠 只在分隔符**两侧紧邻字符都是汉字**时才切——紧邻一侧是英文/数字/缩写就不切。
const HAN = "\\p{Script=Han}";
const ROLE_SEPARATOR_RE = new RegExp(`[;；,，、]+|(?<=${HAN})[ \\t\\u3000/]+(?=${HAN})`, "gu");

function splitRoleTokens(role) {
  return String(role || "")
    .split(ROLE_SEPARATOR_RE)
    .map((s) => s.trim())
    .filter(Boolean);
}

function findMixedSeparatorRoles(roles) {
  return (Array.isArray(roles) ? roles : []).filter((r) => splitRoleTokens(r).length > 1);
}

// 同一用户同一根因只计一次：所有 mixed 写法合并成一条 issue，而不是一个 role 一条。
function buildUserIssues(r) {
  const issues = [];
  if (r.shown === 0 && r.scopeMismatch) {
    issues.push(mkIssue("scope_mismatch", r.user,
      `求职范围=${r.jobScope} 但目标城市全是国内且无英文简历 → 海外池 0 岗（roles=${JSON.stringify(r.roles)}）`,
      { shown: r.shown, jobScope: r.jobScope }));
  } else if (r.shown === 0) {
    issues.push(mkIssue("zero_shown", r.user,
      `推荐页 0 岗（召回 ${r.recalled}，被拦原因 ${JSON.stringify(r.filtered)}）roles=${JSON.stringify(r.roles)}`,
      { shown: r.shown, recalled: r.recalled }));
  }
  if (r.directionOk !== null && r.directionOk < DIRECTION_BAD) {
    issues.push(mkIssue("direction_low", r.user,
      `方向命中 ${Math.round(r.directionOk * 100)}%（roles=${JSON.stringify(r.roles)}）`,
      { directionOk: r.directionOk }));
  }
  const mixedRoles = findMixedSeparatorRoles(r.roles);
  if (mixedRoles.length) {
    issues.push(mkIssue("role_input_format", r.user,
      `岗位方向填写里混了分隔符，未必被正确识别：${JSON.stringify(mixedRoles)}`,
      { mixedRoles }));
  }
  const roleMismatchCount = (r.filtered && r.filtered.role_mismatch) || 0;
  const denom = r.recalled || 0;
  if (denom > 0 && roleMismatchCount / denom > ROLE_MISMATCH_RATIO_BAD) {
    issues.push(mkIssue("role_mismatch_high", r.user,
      `候选里 ${roleMismatchCount}/${denom}（${Math.round((roleMismatchCount / denom) * 100)}%）因方向不符被拦，占比偏高（roles=${JSON.stringify(r.roles)}）`,
      { roleMismatchCount, recalled: denom, ratio: Number((roleMismatchCount / denom).toFixed(3)) }));
  }
  if (r.insightCompanies > 0 && r.insightCovered === 0) {
    issues.push(mkIssue("insight_uncovered", r.user,
      `前 20 张卡的 ${r.insightCompanies} 家公司都没有洞察`,
      { insightCompanies: r.insightCompanies }));
  }
  if (r.campus && r.campus.healthy === 0) {
    issues.push(mkIssue("campus_channel_broken", r.user,
      `校招用户，${r.campus.industries.join("/")} 必投 ${r.campus.listed} 家校招渠道全不通`,
      { listed: r.campus.listed }));
  }
  return issues;
}

function buildLatencyIssues(latency) {
  const issues = [];
  for (const [k, v] of Object.entries(latency || {})) {
    if (v.seconds == null || v.http !== 200) {
      issues.push(mkIssue("api_latency", null, `接口 ${k} 失败（http=${v.http}）`, { metric: k, seconds: v.seconds, http: v.http }));
    } else if (v.seconds > TTFB_BAD_S) {
      issues.push(mkIssue("api_latency", null, `接口 ${k} TTFB ${v.seconds.toFixed(1)}s > ${TTFB_BAD_S}s`, { metric: k, seconds: v.seconds }));
    }
  }
  return issues;
}

// metrics.issues_by_type 恒含全部枚举键（0 也写）——"真的是 0" 与 "没测到" 分得开。
function computeIssuesByType(issues) {
  const out = {};
  for (const type of Object.keys(ISSUE_TYPES)) out[type] = 0;
  for (const issue of issues || []) {
    if (!(issue.type in out)) out[issue.type] = 0;
    out[issue.type] += 1;
  }
  return out;
}

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
    // 求职范围错配：选了海外/全都要、目标城市却全是国内、又没有英文简历 → 海外池里当然找不到「行政/美工」。
    // 页面侧（app/today）会回落国内并提示；这里单独标出来，别和「词库召不回」混成一种 0。
    const CN_CITY_RE = /^(北京|上海|深圳|广州|杭州|成都|武汉|南京|西安|天津|长春|苏州|重庆|长沙|郑州|青岛|合肥|宁波|厦门|济南|大连|沈阳|福州|昆明|无锡|佛山|东莞)/;
    const cities = prefs.target_locations || [];
    const scopeMismatch = String(prefs.job_scope || "domestic") !== "domestic" && cities.length > 0
      && cities.every((c) => CN_CITY_RE.test(String(c))) && !(cand && cand.has_en_resume) && !prefs.has_en_resume;
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
      insightCompanies: companies.length, insightCovered: withInsight, campus, scopeMismatch, jobScope: prefs.job_scope || "domestic",
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
  for (const r of ok) issues.push(...buildUserIssues(r));
  issues.push(...buildLatencyIssues(latency));
  const issuesByType = computeIssuesByType(issues);

  const campusUsers = ok.filter((r) => r.campus);
  const summary = {
    users: ok.length, errors: results.length - ok.length,
    zero_shown: ok.filter((r) => r.shown === 0).length,
    scope_mismatch: ok.filter((r) => r.scopeMismatch).length,
    median_shown: median(ok.map((r) => r.shown)),
    direction_ok_avg: avg(ok.map((r) => r.directionOk).filter((x) => x !== null)),
    insight_coverage_avg: avg(ok.filter((r) => r.insightCompanies > 0).map((r) => r.insightCovered / r.insightCompanies)),
    campus_users: campusUsers.length,
    campus_zero_healthy: campusUsers.filter((r) => r.campus.healthy === 0).length,
    campus_healthy_ratio_avg: avg(campusUsers.map((r) => r.campus.healthy / Math.max(1, r.campus.listed))),
    latency, issues: issues.length, issues_by_type: issuesByType,
  };

  console.log("\n用户 | 阶段 | 召回 | 展示 | 方向命中 | 洞察覆盖 | 校招通/必投 | TOP1");
  for (const r of results) {
    if (r.error) { console.log(`${r.user} | ERROR ${r.error} roles=${JSON.stringify(r.roles)}`); continue; }
    console.log(`${r.user} | ${r.stage || "-"} | ${r.recalled} | ${r.shown} | ${r.directionOk === null ? "-" : Math.round(r.directionOk * 100) + "%"} | ${r.insightCovered}/${r.insightCompanies} | ${r.campus ? r.campus.healthy + "/" + r.campus.listed : "-"} | ${r.top3[0] || "-"}`);
  }
  console.log("\n汇总:", JSON.stringify(summary, null, 1));
  console.log("\n卡点（" + issues.length + "，按类型 " + JSON.stringify(issuesByType) + "）:");
  for (const i of issues) console.log("  - " + i.text);
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

module.exports = {
  ISSUE_TYPES, mkIssue, splitRoleTokens, findMixedSeparatorRoles,
  buildUserIssues, buildLatencyIssues, computeIssuesByType,
};

if (require.main === module) {
  main().catch((e) => { console.error(e); process.exit(1); });
}

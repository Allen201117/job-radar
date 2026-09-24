#!/usr/bin/env node
// /today 与 /campus 两条取数链的「分段账本 + 改前改后等价性对拍」离线探针（先量后改）。
//
// 为什么要有它：这两个页面都**要登录**才能看，线上只能用创始人自己的 Chrome 打开，
// 我们从外面 curl 不到、也拿不到服务端的分段耗时。于是把服务端那几段在本机重放一遍：
// 同一份 `buildRecallSql` / 同一套 stage-2 引擎 / 同一条校招看板 SQL，真库真画像。
// 改前形态与改后形态在**同一次运行里**各跑一遍，避免爬虫一直在写库造成的时间漂移。
//
// ⚠️ 诚实边界：本机 → 香港库的**绝对**毫秒数不等于线上（线上函数在 hkg1、同区；本机要跨公网，
// 空连接握手就 ~1.6s）。**行数与字节数是精确的**，耗时只用于同口径的改前/改后对拍。
//
// 跑法（需要本机 psql + .env.local 里的 JOBS_DATABASE_URL / SUPABASE_*）：
//   set -a; source .env.local; set +a
//   node scripts/perf-probe/today-campus.js                 # 打印账本 + 等价性，写 perf-probe-raw.json
//   node scripts/perf-probe/today-campus.js --out a.json    # 指定输出
//   PERF_PROBE_USERS=7 …                                    # 取几个真实画像（默认 7）
//
// 只读：不写任何用户数据、不写库。输出里的 user_id 只保留前 8 位。
const fs = require("fs");
const path = require("path");
const { createClient } = require("@supabase/supabase-js");

const ROOT = path.join(__dirname, "..", "..");
const { loadTs } = require(path.join(ROOT, "tests/_load-ts.js"));
const { runPsql } = require("../lib/psql.js");
const L = (rel) => loadTs(path.join(ROOT, rel));

const { buildRecallSql, stripTierColumns, RECALL_BUDGET } = L("lib/jobs-store/opportunities.ts");
const { buildRadarProfile, isProfileReady } = L("lib/opportunities/profile.ts");
const { computeMatchFacts, checkEligibility } = L("lib/opportunities/eligibility.ts");
const { scoreOpportunity } = L("lib/opportunities/scoring.ts");
const { deriveOpportunitySignals } = L("lib/opportunities/signals.ts");
const { groupOpportunities, resolveNoveltySince } = L("lib/opportunities/grouping.ts");
const { parseDeadline } = L("lib/opportunities/deadline.ts");
const { collapseBulkStoreJobs } = L("lib/bulk-store-dedup.ts");
const { MUST_APPLY_BY_INDUSTRY, resolveMustApplyIndustries, mustApplyUnion, mustApplyPatterns } = L("lib/must-apply-list.ts");
const { CAMPUS_PREFILTER_SQL, CAMPUS_ZONE_AGGREGATE_SQL, CAMPUS_ZONE_ROW_LEVEL_SQL } = L("lib/jobs-store/read.ts");
const { foldCampusZone, campusAdmission } = L("lib/campus-zone.ts");
const { buildCampusFacets, buildCampusFacetsFromGroups } = L("lib/campus-facets.ts");
const { isCurrentSeasonGradClass } = require(path.join(ROOT, "lib/grad-class.js"));

const OUT = (() => {
  const i = process.argv.indexOf("--out");
  return i > 0 && process.argv[i + 1] ? path.resolve(process.argv[i + 1]) : path.join(__dirname, "perf-probe-raw.json");
})();
const USER_LIMIT = Number(process.env.PERF_PROBE_USERS || 7);

// ── psql 执行层（与 scripts/match-eval/eval.js 同款：参数内联成字面量，只在离线脚本里这么干）──
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
  let out = sql;
  for (let i = params.length; i >= 1; i--) out = out.split("$" + i).join(lit(params[i - 1]));
  return out;
}
// 连接串经环境变量传给 psql、不进命令行（见 scripts/lib/psql.js 顶部注释）。
function psql(args, encoding = "utf8") {
  return runPsql(["-X", "-q", ...args], { maxBuffer: 1024 * 1024 * 1024, encoding });
}
/** 行数 / 线上字节（COPY 文本协议的真实输出）/ 墙钟耗时。 */
function sizeOf(sql) {
  const t0 = Date.now();
  const buf = psql(["-t", "-A", "-c", `copy (${sql}) to stdout`], "buffer");
  const ms = Date.now() - t0;
  let rows = 0;
  for (let i = 0; i < buf.length; i++) if (buf[i] === 10) rows++;
  return { rows, bytes: buf.length, ms };
}
/** 同一条 SQL 的行内容（JSON）；字节数请用 sizeOf，别拿 json 的膨胀值当传输量。 */
function rowsOf(sql) {
  const text = psql(["-t", "-A", "-c", `copy (select row_to_json(t) from (${sql}) t) to stdout`]);
  return text.split("\n").filter((l) => l.length).map((l) => JSON.parse(l.replace(/\\\\/g, "\\")));
}
const kb = (n) => Math.round((n / 1024) * 10) / 10;

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

function companiesForIndustries(industries) {
  return Array.from(
    new Map(industries.flatMap((ind) => MUST_APPLY_BY_INDUSTRY[ind] || []).map((c) => [c.pattern, c])).values(),
  );
}

// ── /campus 改前形态（2026-09-18 下线，保留作等价性基线）───────────────────────────
// 整段逐行拉回，含 jd_url / apply_url 两列长 URL，在 JS 里逐条判桶。
const CAMPUS_ZONE_LEGACY_SQL = `
      select
        j.id, j.company, j.title, j.job_type, j.jd_url, j.apply_url,
        case when j.recruitment_category is null then j.summary end as summary,
        j.experience, j.deadline, j.first_seen_at, j.last_seen_at, j.location as city, j.education, j.status,
        j.grad_class, j.recruitment_category, j.job_function
      from jobs j
      where j.status = 'active'
        and j.company = any($1::text[])
        and ${CAMPUS_PREFILTER_SQL}
      `;

/** 改前的 JS 折叠（逐行入桶），一比一照抄下线前的 getCampusZone 循环体。 */
function foldCampusZoneLegacy(list, rows) {
  const byName = new Map();
  for (const c of list) {
    byName.set(c.name, {
      company: c.name, pattern: c.pattern, campusJobs: [], internJobs: [],
      hasAnyActiveJob: false, lastSeenAtMs: null, pastClassJobCount: 0,
    });
  }
  for (const r of rows) {
    if (!r.id || !r.company) continue;
    const companyLower = String(r.company).toLowerCase();
    const owner = list.find((c) => companyLower.includes(c.pattern.replace(/%/g, "").toLowerCase()));
    if (!owner) continue;
    const agg = byName.get(owner.name);
    if (!agg) continue;
    agg.hasAnyActiveJob = true;
    const seen = r.last_seen_at ? Date.parse(r.last_seen_at) : NaN;
    if (!Number.isNaN(seen)) agg.lastSeenAtMs = Math.max(agg.lastSeenAtMs || 0, seen);
    const bucket = campusAdmission(r);
    if (bucket === "reject") continue;
    if (!isCurrentSeasonGradClass(r.grad_class)) { agg.pastClassJobCount += 1; continue; }
    if (bucket === "campus") agg.campusJobs.push(r);
    else agg.internJobs.push(r);
  }
  return list.map((c) => byName.get(c.name));
}

// ── /today：跑一遍完整的 stage-1 + stage-2 + 分区，返回账本与主清单 ──────────────
function runTodayOnce(profile, now, sourceMetaFetcher) {
  const sinceIso = new Date(now.getTime() - 7 * 86400000).toISOString();
  const built = buildRecallSql(profile, sinceIso, RECALL_BUDGET, []);
  if (!built) return null;
  const sql = inlineParams(built.sql, built.params);
  const size = sizeOf(sql);
  const jobs = collapseBulkStoreJobs(stripTierColumns(rowsOf(sql), built.tiers));
  return { built, size, jobs, sourceMetaFetcher };
}

async function scoreToday(profile, now, jobs, sourceMeta) {
  const filtered = {};
  const opps = [];
  const t0 = Date.now();
  for (const job of jobs) {
    const facts = computeMatchFacts(job, profile, job.source_id ? sourceMeta.get(job.source_id) : undefined, { primary: null, viewed: false }, now);
    const elig = checkEligibility(facts);
    if (!elig.eligible) { filtered[elig.reason] = (filtered[elig.reason] || 0) + 1; continue; }
    const { score, tier, reasons } = scoreOpportunity(facts, elig.degraded);
    if (tier === null) { filtered.low_score = (filtered.low_score || 0) + 1; continue; }
    const parsed = parseDeadline(job.deadline ?? null, now);
    opps.push({
      job, score, tier, reasons,
      freshness: facts.freshness,
      firstSeenAt: job.first_seen_at ?? null,
      lastSeenAt: job.last_seen_at ?? null,
      userAction: facts.userAction,
      viewed: facts.viewed,
      isNew: false,
      exploreEligible: facts.roleTier === "related" || facts.companyHit || Boolean(job.recall_function_only),
      functionOnly: Boolean(job.recall_function_only) && facts.roleTier !== "exact",
      signals: deriveOpportunitySignals(job, facts, profile, now, { isWatched: false, parsedDeadline: parsed }),
      intensity: "active",
      lastCheckedAt: job.enrich_checked_at ?? null,
      officialPostedAt: job.posted_at ?? null,
      deadlineAt: parsed?.date ?? null,
    });
  }
  const { sections } = groupOpportunities(opps, {
    dailyLimit: profile.dailyLimit, intensity: "active",
    noveltySince: resolveNoveltySince(null, now), now,
  });
  return { sections, filtered, scoreMs: Date.now() - t0 };
}

function overlap(a, b) {
  const sb = new Set(b);
  const hit = a.filter((x) => sb.has(x)).length;
  return a.length ? Math.round((hit / a.length) * 100) : 100;
}

async function main() {
  const client = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false },
  });
  const prefsRows = await fetchAll(client.from("user_preferences").select("*").order("updated_at", { ascending: false }));
  const candRows = await fetchAll(client.from("candidate_profiles").select("*"));
  const candByUser = new Map(candRows.map((c) => [c.user_id, c]));

  // 取数口径：job_scope=domestic；有 target_roles 的最近 N-2 个 + 无 target_roles 的 2 个
  // （后者是「方向层出不来、只剩城市层」的那一类，必须一起量）。
  const domestic = prefsRows.filter((p) => String(p.job_scope || "domestic") === "domestic");
  const withRoles = domestic.filter((p) => Array.isArray(p.target_roles) && p.target_roles.length);
  const noRoles = domestic.filter((p) => !Array.isArray(p.target_roles) || !p.target_roles.length);
  const picked = [...withRoles.slice(0, Math.max(0, USER_LIMIT - 2)), ...noRoles.slice(0, 2)];

  const now = new Date();
  const today = [];
  for (const prefs of picked) {
    const label = String(prefs.user_id).slice(0, 8);
    const candidate = candByUser.get(prefs.user_id) || null;
    const profile = buildRadarProfile("probe", prefs, candidate);
    if (!isProfileReady(profile)) { today.push({ user: label, skip: "profile_not_ready" }); continue; }

    const variants = {};
    for (const mode of ["before", "after"]) {
      // before = 正文全传（改前形态）；after = 正文按需传。同一次运行里各跑一遍。
      // ⚠️ A/A 自检（PERF_PROBE_AA=1）：两轮都用改前形态。爬虫一直在写库，两轮之间**本来就会漂**，
      // 不先量一遍「尺子自己抖多少」，就没法把差异归因给代码改动（match-eval 的 LLM 裁判栽过同一个坑）。
      process.env.RECALL_SUMMARY_GATE = process.env.PERF_PROBE_AA === "1" || mode === "before" ? "off" : "on";
      const run = runTodayOnce(profile, now, null);
      if (!run) { variants[mode] = { skip: "no_recall" }; continue; }

      const sourceIds = Array.from(new Set(run.jobs.map((j) => j.source_id).filter(Boolean)));
      const tSrc = Date.now();
      const srcRows = [];
      for (let i = 0; i < sourceIds.length; i += 100) {
        const { data } = await client
          .from("sources")
          .select("id, company, adapter_name, crawl_method, last_checked_at, enabled")
          .in("id", sourceIds.slice(i, i + 100));
        srcRows.push(...(data || []));
      }
      const sourceMetaMs = Date.now() - tSrc;
      const sourceMeta = new Map(srcRows.map((s) => [s.id, s]));

      const scored = await scoreToday(profile, now, run.jobs, sourceMeta);
      const displayIds = Object.values(scored.sections).flat().map((o) => o.job.id);
      const hydrate = displayIds.length
        ? sizeOf(`select * from jobs where id = any(${lit(displayIds)}::uuid[])`)
        : { rows: 0, bytes: 0, ms: 0 };

      variants[mode] = {
        tiers: run.built.tiers,
        recall: { rows: run.size.rows, kb: kb(run.size.bytes), ms: run.size.ms },
        sourceMeta: { sources: sourceIds.length, ms: sourceMetaMs },
        score: { ms: scored.scoreMs },
        hydrate: { rows: hydrate.rows, kb: kb(hydrate.bytes), ms: hydrate.ms },
        crossDbKb: kb(run.size.bytes + hydrate.bytes),
        filtered: scored.filtered,
        mainCount: scored.sections.main.length,
        exploreCount: scored.sections.explore.length,
        mainTop20: scored.sections.main.slice(0, 20).map((o) => o.job.id),
        mainTop20Titles: scored.sections.main.slice(0, 20).map((o) => `${o.job.title} @ ${o.job.company}`),
        // 候选集本身的漂移：爬虫一直在写库，两轮之间新插入的岗会把撞预算的窗口挤动一格。
        // 不记它就没法把「拒绝原因差了 1」归因清楚——那到底是代码改动还是库在动。
        candidateIds: run.jobs.map((j) => j.id),
      };
    }
    delete process.env.RECALL_SUMMARY_GATE;

    const b = variants.before, a = variants.after;
    if (b && a && b.candidateIds && a.candidateIds) {
      const sb = new Set(b.candidateIds), sa = new Set(a.candidateIds);
      b.candidateDrift = { onlyBefore: b.candidateIds.filter((x) => !sa.has(x)).length, onlyAfter: a.candidateIds.filter((x) => !sb.has(x)).length };
      a.candidateDrift = b.candidateDrift;
      delete b.candidateIds;
      delete a.candidateIds;
    }
    const rec = {
      user: label, roles: profile.targetRoles, cities: profile.targetLocations,
      before: b, after: a,
      equivalence: b && a && b.mainTop20 && a.mainTop20
        ? {
            overlapPct: overlap(b.mainTop20, a.mainTop20),
            samePosition: b.mainTop20.filter((id, i) => a.mainTop20[i] === id).length,
            onlyBefore: b.mainTop20.filter((id) => !a.mainTop20.includes(id)),
            onlyAfter: a.mainTop20.filter((id) => !b.mainTop20.includes(id)),
            filteredSame: JSON.stringify(b.filtered) === JSON.stringify(a.filtered),
          }
        : null,
    };
    today.push(rec);
    if (b && a && b.recall) {
      console.log(
        `[today] ${label} roles=${JSON.stringify(profile.targetRoles)} tiers=${(a.tiers || []).join("+")} | ` +
          `改前 rows=${b.recall.rows} kb=${b.recall.kb} ms=${b.recall.ms} → 改后 rows=${a.recall.rows} kb=${a.recall.kb} ms=${a.recall.ms} | ` +
          `src ${a.sourceMeta.sources}个源 ${a.sourceMeta.ms}ms | score ${a.score.ms}ms | hydrate rows=${a.hydrate.rows} kb=${a.hydrate.kb} ms=${a.hydrate.ms} | ` +
          `main ${b.mainCount}→${a.mainCount} | top20 重合 ${rec.equivalence.overlapPct}% 同位 ${rec.equivalence.samePosition}/20 | ` +
          `拒绝原因一致=${rec.equivalence.filteredSame} | 候选集漂移 ${JSON.stringify(b.candidateDrift)}`,
      );
    }
  }

  // ── 全部 active 公司名（resolveActiveCompanyNames 的第一跳，/campus 与「热门在招」共用）──
  const tNames = Date.now();
  const allNames = psql(["-t", "-A", "-c", "select distinct company from jobs where status='active'"])
    .split("\n").map((s) => s.trim()).filter(Boolean);
  const namesMs = Date.now() - tNames;
  const namesBytes = allNames.reduce((n, s) => n + Buffer.byteLength(s) + 1, 0);
  console.log(`[names] active 公司名 rows=${allNames.length} kb=${kb(namesBytes)} ms=${namesMs}（5 分钟进程内缓存）`);
  const resolveNames = (patterns) => {
    const needles = patterns.map((p) => p.replace(/%/g, "").toLowerCase()).filter(Boolean);
    return allNames.filter((c) => { const lo = c.toLowerCase(); return needles.some((n) => lo.includes(n)); });
  };

  // ── 画像未就绪的用户：/today 不发个人召回，走「热门在招」兜底（lib/popular-feed）──
  const popularNames = resolveNames(mustApplyUnion("domestic").flatMap((c) => mustApplyPatterns(c)));
  const popularSql = `
    select t.id, t.company, t.title, t.location, t.job_type, t.jd_url, t.posted_at, t.last_seen_at
    from unnest(${lit(popularNames)}::text[]) as c(company)
    cross join lateral (
      select j.id, j.company, j.title, j.location, j.job_type, j.jd_url, j.posted_at, j.last_seen_at
      from jobs j
      where j.company = c.company and j.status = 'active' and j.job_scope = 'domestic' and j.jd_url <> ''
        and char_length(btrim(coalesce(j.summary, ''))) >= 60
        and j.last_seen_at > now() - interval '30 hours'
      limit 3
    ) t`;
  const popular = sizeOf(popularSql);
  console.log(`[popular] 候选 rows=${popular.rows} kb=${kb(popular.bytes)} ms=${popular.ms}（10 分钟 unstable_cache 共享，不按用户重算）`);

  // ── /campus：看板取数 ──────────────────────────────────────
  const scopes = new Map();
  scopes.set("互联网/科技", resolveMustApplyIndustries(["互联网/科技"]));
  for (const prefs of picked) {
    const cand = candByUser.get(prefs.user_id) || null;
    const inds = resolveMustApplyIndustries(prefs.target_industries || (cand && cand.industries) || []);
    if (inds.length) scopes.set(inds.join("/"), inds);
  }

  const campus = [];
  for (const [label, industries] of scopes) {
    const list = companiesForIndustries(industries);
    const names = resolveNames(list.map((c) => c.pattern));
    const p = [names];

    const legacySql = inlineParams(CAMPUS_ZONE_LEGACY_SQL, p);
    const aggSql = inlineParams(CAMPUS_ZONE_AGGREGATE_SQL, p);
    const rowSql = inlineParams(CAMPUS_ZONE_ROW_LEVEL_SQL, p);
    const legacy = sizeOf(legacySql);
    const agg = sizeOf(aggSql);
    const rowLevel = sizeOf(rowSql);

    // 等价性：同一批库里数据，改前逐行折叠 vs 改后聚合折叠，逐家比计数与分面。
    const zoneBefore = foldCampusZoneLegacy(list, rowsOf(legacySql));
    const zoneAfter = foldCampusZone(list, rowsOf(aggSql), rowsOf(rowSql), now);
    const fBefore = buildCampusFacets(zoneBefore.map((z) => ({ pattern: z.pattern, jobs: z.campusJobs })));
    const fAfter = buildCampusFacetsFromGroups(zoneAfter.map((z) => ({ pattern: z.pattern, groups: z.campusGroups })));
    const iBefore = buildCampusFacets(zoneBefore.map((z) => ({ pattern: z.pattern, jobs: z.internJobs })));
    const iAfter = buildCampusFacetsFromGroups(zoneAfter.map((z) => ({ pattern: z.pattern, groups: z.internGroups })));

    const diffs = [];
    for (let i = 0; i < list.length; i++) {
      const zb = zoneBefore[i], za = zoneAfter[i];
      const pat = list[i].pattern;
      const cmp = {
        campusTotal: [fBefore.totals.get(pat) ?? 0, fAfter.totals.get(pat) ?? 0],
        internTotal: [iBefore.totals.get(pat) ?? 0, iAfter.totals.get(pat) ?? 0],
        pastClass: [zb.pastClassJobCount, za.pastClassJobCount],
        lastSeen: [zb.lastSeenAtMs, za.lastSeenAtMs],
        hasAny: [zb.hasAnyActiveJob, za.hasAnyActiveJob],
      };
      const bad = Object.entries(cmp).filter(([, [x, y]]) => String(x) !== String(y));
      if (bad.length) diffs.push({ company: list[i].name, bad });
    }
    const optionsSame =
      JSON.stringify(fBefore.options) === JSON.stringify(fAfter.options) &&
      JSON.stringify(iBefore.options) === JSON.stringify(iAfter.options);

    const rec = {
      scope: label, patterns: list.length, companies: names.length, namesMs,
      before: { rows: legacy.rows, kb: kb(legacy.bytes), ms: legacy.ms },
      after: {
        rows: agg.rows + rowLevel.rows, kb: kb(agg.bytes + rowLevel.bytes), ms: Math.max(agg.ms, rowLevel.ms),
        aggRows: agg.rows, aggKb: kb(agg.bytes), aggMs: agg.ms,
        rowLevelRows: rowLevel.rows, rowLevelKb: kb(rowLevel.bytes), rowLevelMs: rowLevel.ms,
      },
      equivalence: { companiesCompared: list.length, mismatches: diffs, filterOptionsIdentical: optionsSame },
    };
    campus.push(rec);
    console.log(
      `[campus] ${label} 清单${list.length}家/库里${names.length}个公司名 | ` +
        `改前 rows=${legacy.rows} kb=${kb(legacy.bytes)} ms=${legacy.ms} → ` +
        `改后 rows=${agg.rows + rowLevel.rows} kb=${kb(agg.bytes + rowLevel.bytes)} ms=${Math.max(agg.ms, rowLevel.ms)}（并行两条）` +
        ` [聚合 ${agg.rows}行/${kb(agg.bytes)}kb/${agg.ms}ms + 逐行兜底 ${rowLevel.rows}行/${kb(rowLevel.bytes)}kb/${rowLevel.ms}ms] | ` +
        `逐家对拍 ${list.length} 家，不一致 ${diffs.length} 家，筛选选项完全相同=${optionsSame}`,
    );
    for (const d of diffs) console.log(`         ⚠ ${d.company}: ${JSON.stringify(d.bad)}`);
  }

  fs.writeFileSync(OUT, JSON.stringify({ generated_at: now.toISOString(), today, campus }, null, 1));
  console.log(`\n写入 ${OUT}`);
}

main().catch((e) => { console.error(e); process.exit(1); });

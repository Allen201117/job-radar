#!/usr/bin/env node
// /today **页面级**分段账本的离线探针（第二棒「先量后改」）。
//
// 为什么不是 today-campus.js 就够了：那一份量的是 `buildOpportunityFeed` **内部**四段
// （recall / sourcemeta / compute / hydrate）。线上 02:35 实测 `[today-feed] total=1,880ms`，
// 而整页流完要 6.5s —— 也就是说 **2/3 的时间不在 feed 账本里**。这一份把 feed **之外**的段
// 也量出来：画像读取（4 条 Supabase 悉尼查询，逐表字节）、序列化给浏览器的 props 字节
// （HTML 里它出现两次：JobCard 渲染出的markup + RSC payload），以及 sources 元信息两种取法的对拍。
//
// ⚠️ 诚实边界（和 today-campus.js 同）：
//   · **行数与字节数是精确的**（COPY 文本协议真实输出 / UTF-8 逐字符）；
//   · **毫秒数只在同一次运行内做改前/改后对拍**——本机到香港/悉尼要跨公网，绝对值不等于线上
//     （线上函数在 hkg1，与 jobs 库同区；Supabase 在悉尼两边都要跨洋，但 RTT 不同）；
//   · **函数冷启动本机模拟不了**，报告里必须单独说明哪几段会随冷启动放大。
//
// 跑法（需要本机 psql + .env.local 的 JOBS_DATABASE_URL / SUPABASE_*）：
//   set -a; source .env.local; set +a
//   node scripts/perf-probe/today-page.js               # 打印账本，写 today-page-raw.json
//   node scripts/perf-probe/today-page.js --out a.json
//   TODAY_PROBE_USERS=5 …                               # 取几个真实画像（默认 5）
//
// 只读：不写任何用户数据、不写库。输出里的 user_id 只保留前 8 位，不打印任何连接串/密钥。
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { createClient } = require("@supabase/supabase-js");

const ROOT = path.join(__dirname, "..", "..");
const { loadTs } = require(path.join(ROOT, "tests/_load-ts.js"));
const L = (rel) => loadTs(path.join(ROOT, rel));

const { buildRecallSql, stripTierColumns, RECALL_BUDGET } = L("lib/jobs-store/opportunities.ts");
const { buildRadarProfile, isProfileReady } = L("lib/opportunities/profile.ts");
const { computeMatchFacts, checkEligibility } = L("lib/opportunities/eligibility.ts");
const { scoreOpportunity } = L("lib/opportunities/scoring.ts");
const { deriveOpportunitySignals } = L("lib/opportunities/signals.ts");
const { groupOpportunities, resolveNoveltySince } = L("lib/opportunities/grouping.ts");
const { parseDeadline } = L("lib/opportunities/deadline.ts");
const { resolveIntensityForUser } = L("lib/opportunities/intensity.ts");
const { collapseBulkStoreJobs } = L("lib/bulk-store-dedup.ts");
const { JOB_COLUMNS } = L("lib/jobs-store/types.ts");
const { RADAR_ACTION_COLUMNS } = L("lib/opportunities/context.ts");
const { SOURCE_META_COLUMNS } = L("lib/opportunities/source-meta.ts");

const OUT = (() => {
  const i = process.argv.indexOf("--out");
  return i > 0 && process.argv[i + 1] ? path.resolve(process.argv[i + 1]) : path.join(__dirname, "today-page-raw.json");
})();
const USER_LIMIT = Number(process.env.TODAY_PROBE_USERS || 5);

// ── psql 执行层（与 today-campus.js 同款：参数内联成字面量，只在离线脚本里这么干）──
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
function psql(args, encoding = "utf8") {
  const url = process.env.JOBS_DATABASE_URL;
  if (!url) throw new Error("JOBS_DATABASE_URL 未配置（先 source .env.local）");
  const r = spawnSync("psql", [url, "-X", "-q", ...args], { maxBuffer: 1024 * 1024 * 1024, encoding });
  if (r.status !== 0) throw new Error(String(r.stderr || "psql failed").slice(0, 500));
  return r.stdout;
}
function sizeOf(sql) {
  const t0 = Date.now();
  const buf = psql(["-t", "-A", "-c", `copy (${sql}) to stdout`], "buffer");
  const ms = Date.now() - t0;
  let rows = 0;
  for (let i = 0; i < buf.length; i++) if (buf[i] === 10) rows++;
  return { rows, bytes: buf.length, ms };
}
function rowsOf(sql) {
  const text = psql(["-t", "-A", "-c", `copy (select row_to_json(t) from (${sql}) t) to stdout`]);
  return text.split("\n").filter((l) => l.length).map((l) => JSON.parse(l.replace(/\\\\/g, "\\")));
}
const kb = (n) => Math.round((n / 1024) * 10) / 10;

// 交付到 JS 之后的近似 UTF-8 字节（与 lib/jobs-store/row-bytes.ts 同口径，但这里不抽样、逐行算准）。
function valueBytes(v) {
  if (v === null || v === undefined) return 0;
  if (typeof v === "number" || typeof v === "boolean") return 8;
  const s = typeof v === "string" ? v : JSON.stringify(v);
  let n = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    n += c < 0x80 ? 1 : c < 0x800 ? 2 : 3;
  }
  return n;
}
const rowsBytes = (rows) => (rows || []).reduce((n, r) => n + Object.values(r || {}).reduce((m, v) => m + valueBytes(v), 0), 0);
function columnBytes(rows) {
  const out = new Map();
  for (const r of rows || []) for (const [k, v] of Object.entries(r || {})) out.set(k, (out.get(k) || 0) + valueBytes(v));
  return [...out.entries()].sort((a, b) => b[1] - a[1]);
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

/** 复刻 service.ts 的 stage-2：逐岗算事实 → 硬门 → 打分 → 信号。 */
function computeStage2(profile, now, jobs, sourceMeta, actionMap, intensity) {
  const filtered = { inactive: 0, mismatch: 0, low_score: 0, thin: 0 };
  const opps = [];
  const t0 = Date.now();
  for (const job of jobs) {
    const action = actionMap.get(job.id) || { primary: null, viewed: false };
    const facts = computeMatchFacts(job, profile, job.source_id ? sourceMeta.get(job.source_id) : undefined, action, now);
    const elig = checkEligibility(facts);
    if (!elig.eligible) {
      if (elig.reason === "inactive" || elig.reason === "stale" || elig.reason === "source_disabled") filtered.inactive += 1;
      else if (elig.reason === "thin_summary") filtered.thin += 1;
      else if (elig.reason !== "already_actioned") filtered.mismatch += 1;
      continue;
    }
    const { score, tier, reasons } = scoreOpportunity(facts, elig.degraded);
    if (tier === null) { filtered.low_score += 1; continue; }
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
      intensity,
      lastCheckedAt: job.enrich_checked_at ?? null,
      officialPostedAt: job.posted_at ?? null,
      deadlineAt: parsed?.date ?? null,
    });
  }
  return { opps, filtered, computeMs: Date.now() - t0 };
}

function buildActionMap(actions) {
  const map = new Map();
  for (const a of actions || []) {
    const cur = map.get(a.job_id) || { primary: null, viewed: false };
    if (a.action === "viewed") cur.viewed = true;
    else if (a.action === "saved" || a.action === "ignored" || a.action === "applied") cur.primary = a.action;
    map.set(a.job_id, cur);
  }
  return map;
}

async function main() {
  const sb = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false },
  });
  const now = new Date();

  // ── 段 S：sources 元信息两种取法的对拍（改前=按 id 分块 .in()，改后=全表一次 + 跨实例缓存）──
  const tFull = Date.now();
  const allSources = await fetchAll(sb.from("sources").select(SOURCE_META_COLUMNS));
  const fullMs = Date.now() - tFull;
  const fullBytes = rowsBytes(allSources);
  console.log(
    `[sourcemeta-full] rows=${allSources.length} kb=${kb(fullBytes)} json_kb=${kb(Buffer.byteLength(JSON.stringify(allSources)))} ` +
      `ms=${fullMs} pages=${Math.ceil(allSources.length / 1000)}（unstable_cache 单条上限约 2MB，放得下 → 可跨实例共享）`,
  );

  const prefsRows = await fetchAll(sb.from("user_preferences").select("*").order("updated_at", { ascending: false }));
  const candRows = await fetchAll(sb.from("candidate_profiles").select("*"));
  const candByUser = new Map(candRows.map((c) => [c.user_id, c]));

  // 取真实用户：优先「动作多 + 有目标方向」的（他们的 ctx 载荷最大、最能暴露问题）
  const actionCounts = new Map();
  for (const a of await fetchAll(sb.from("job_actions").select("user_id"))) {
    actionCounts.set(a.user_id, (actionCounts.get(a.user_id) || 0) + 1);
  }
  const picked = prefsRows
    .filter((p) => String(p.job_scope || "domestic") === "domestic")
    .map((p) => ({ p, n: actionCounts.get(p.user_id) || 0 }))
    .sort((x, y) => y.n - x.n)
    .map(({ p }) => p);

  const users = [];
  for (const prefs of picked) {
    if (users.length >= USER_LIMIT) break;
    const label = String(prefs.user_id).slice(0, 8);
    const candidate = candByUser.get(prefs.user_id) || null;
    const profile = buildRadarProfile("probe", prefs, candidate);
    if (!isProfileReady(profile)) continue;

    // ── 段 A：画像读取（4 条 Supabase 悉尼查询并行）。before=select("*")，after=只取被读的列 ──
    const ctx = {};
    for (const mode of ["before", "after"]) {
      const actSel = mode === "before" ? "*" : RADAR_ACTION_COLUMNS;
      const t = Date.now();
      const [p, c, a, s] = await Promise.all([
        sb.from("user_preferences").select("*").eq("user_id", prefs.user_id).maybeSingle(),
        sb.from("candidate_profiles").select("*").eq("user_id", prefs.user_id).maybeSingle(),
        sb.from("job_actions").select(actSel).eq("user_id", prefs.user_id),
        sb.from("user_radar_state").select("last_opened_at").eq("user_id", prefs.user_id).maybeSingle(),
      ]);
      ctx[mode] = {
        ms: Date.now() - t,
        actions: (a.data || []).length,
        bytes:
          rowsBytes(p.data ? [p.data] : []) +
          rowsBytes(c.data ? [c.data] : []) +
          rowsBytes(a.data || []) +
          rowsBytes(s.data ? [s.data] : []),
        actionBytes: rowsBytes(a.data || []),
        raw: mode === "before" ? { actions: a.data || [], radarState: s.data || null } : null,
      };
    }
    const actions = ctx.before.raw.actions;
    const radarState = ctx.before.raw.radarState;
    delete ctx.before.raw;
    delete ctx.after.raw;

    const { intensity } = resolveIntensityForUser(prefs, radarState, actions, profile.targetCompanies.length > 0, now);
    const actionMap = buildActionMap(actions);
    const actionedIds = [...actionMap.entries()].filter(([, s]) => s.primary !== null).map(([id]) => id);

    // ── 段 B：召回（香港库）──
    const built = buildRecallSql(profile, new Date(now.getTime() - 7 * 86400000).toISOString(), RECALL_BUDGET, actionedIds);
    if (!built) continue;
    const recallSql = inlineParams(built.sql, built.params);
    const recallSize = sizeOf(recallSql);
    const recallJobs = collapseBulkStoreJobs(stripTierColumns(rowsOf(recallSql), built.tiers));

    // ── 段 C：关键提醒（香港库，按 saved/applied 岗）——与召回并行，账本分开记 ──
    const watched = Array.from(
      new Set(actions.filter((a) => a.action === "saved" || a.action === "applied").map((a) => a.job_id).filter(Boolean)),
    ).slice(0, 50);
    const criticalSize = watched.length
      ? sizeOf(`select ${JOB_COLUMNS} from jobs where id = any(${lit(watched)}::uuid[])`)
      : { rows: 0, bytes: 0, ms: 0 };

    // ── 段 D：source 元信息（改前=按 id 分块；改后=全表缓存，命中即 0 次往返）──
    const sourceIds = Array.from(new Set(recallJobs.map((j) => j.source_id).filter(Boolean)));
    const tById = Date.now();
    const byIdRows = [];
    for (let i = 0; i < sourceIds.length; i += 100) {
      const { data } = await sb.from("sources").select(SOURCE_META_COLUMNS).in("id", sourceIds.slice(i, i + 100));
      byIdRows.push(...(data || []));
    }
    const byIdMs = Date.now() - tById;
    const metaById = new Map(byIdRows.map((s) => [s.id, s]));
    const metaFull = new Map(allSources.filter((s) => sourceIds.includes(s.id)).map((s) => [s.id, s]));
    // 等价性：两种取法拿到的 SourceMeta 要逐个相同。**并且要分清差在哪一列**——
    // `computeMatchFacts` 只读 `enabled`（source_disabled 硬门）与 `crawl_method`（freshness），
    // 这两列差一个就是真回归；`last_checked_at` 是爬虫每分钟都在改的时间戳，快照差它无害。
    let metaMismatch = 0;
    const mismatchFields = new Map();
    for (const id of sourceIds) {
      const a = metaById.get(id) ?? null;
      const b = metaFull.get(id) ?? null;
      if (JSON.stringify(a) === JSON.stringify(b)) continue;
      metaMismatch += 1;
      for (const k of new Set([...Object.keys(a || {}), ...Object.keys(b || {})])) {
        if (JSON.stringify(a?.[k]) !== JSON.stringify(b?.[k])) mismatchFields.set(k, (mismatchFields.get(k) || 0) + 1);
      }
    }
    const behaviourFields = ["enabled", "crawl_method"].filter((f) => mismatchFields.has(f));

    // ── 段 E：逐岗计算 + 分区。**改前（按 id 取元信息）与改后（全表快照）各跑一遍**，
    //     用同一批召回候选，差异只可能来自 sourceMeta 这一个输入 → 直接对拍主清单前 20 条 id。
    const groupOpts = {
      dailyLimit: profile.dailyLimit,
      intensity,
      noveltySince: resolveNoveltySince(radarState?.last_opened_at ?? null, now),
      now,
    };
    const stage2Before = computeStage2(profile, now, recallJobs, metaById, actionMap, intensity);
    const beforeSections = groupOpportunities(stage2Before.opps, groupOpts).sections;
    const stage2 = computeStage2(profile, now, recallJobs, metaFull, actionMap, intensity);
    const tGroup = Date.now();
    const { sections } = groupOpportunities(stage2.opps, groupOpts);
    const groupMs = Date.now() - tGroup;
    const beforeTop20 = beforeSections.main.slice(0, 20).map((o) => o.job.id);
    const afterTop20 = sections.main.slice(0, 20).map((o) => o.job.id);
    const equivalence = {
      top20Identical: JSON.stringify(beforeTop20) === JSON.stringify(afterTop20),
      top20Before: beforeTop20.length,
      top20After: afterTop20.length,
      filteredIdentical: JSON.stringify(stage2Before.filtered) === JSON.stringify(stage2.filtered),
      displayedBefore: Object.values(beforeSections).reduce((n, a) => n + a.length, 0),
      displayedAfter: Object.values(sections).reduce((n, a) => n + a.length, 0),
    };

    // ── 段 F：展示行回填 + 序列化给浏览器的载荷 ──
    const displayIds = Object.values(sections).flat().map((o) => o.job.id).filter(Boolean);
    const hydrateSize = displayIds.length
      ? sizeOf(`select ${JOB_COLUMNS} from jobs where id = any(${lit(displayIds)}::uuid[])`)
      : { rows: 0, bytes: 0, ms: 0 };
    const hydrateRows = displayIds.length
      ? rowsOf(`select ${JOB_COLUMNS} from jobs where id = any(${lit(displayIds)}::uuid[])`)
      : [];
    const byId = new Map(hydrateRows.map((r) => [r.id, r]));
    for (const o of Object.values(sections).flat()) {
      const full = byId.get(o.job.id);
      if (full) o.job = full;
    }
    const feedForClient = {
      generated_at: now.toISOString(),
      profile_ready: true,
      candidate_capped: recallSize.rows >= RECALL_BUDGET,
      last_opened_at: radarState?.last_opened_at ?? null,
      stage: profile.experienceStage,
      intensity,
      counts: { total: displayIds.length, screened: recallJobs.length, filtered: stage2.filtered },
      sections,
    };
    const propsBytes = Buffer.byteLength(JSON.stringify(feedForClient));
    const colBytes = columnBytes(hydrateRows);
    const colTotal = colBytes.reduce((n, [, b]) => n + b, 0);
    const top = colBytes.slice(0, 6).map(([k, b]) => `${k}=${kb(b)}kb(${Math.round((b / Math.max(1, colTotal)) * 100)}%)`);

    const rec = {
      user: label,
      roles: profile.targetRoles,
      cities: profile.targetLocations,
      intensity,
      ctx,
      recall: { rows: recallSize.rows, kb: kb(recallSize.bytes), ms: recallSize.ms, deduped: recallJobs.length, tiers: built.tiers },
      critical: { ids: watched.length, rows: criticalSize.rows, kb: kb(criticalSize.bytes), ms: criticalSize.ms },
      sourcemeta: { sources: sourceIds.length, byIdMs, byIdRows: byIdRows.length, fullMs, fullKb: kb(fullBytes), mismatch: metaMismatch, mismatchFields: Object.fromEntries(mismatchFields), behaviourFields },
      compute: { ms: stage2.computeMs, perJobUs: Math.round((stage2.computeMs * 1000) / Math.max(1, recallJobs.length)), filtered: stage2.filtered },
      group: { ms: groupMs },
      hydrate: { rows: hydrateSize.rows, kb: kb(hydrateSize.bytes), ms: hydrateSize.ms },
      props: { cards: displayIds.length, kb: kb(propsBytes), topColumns: top },
      equivalence,
      mainTop20: afterTop20,
    };
    users.push(rec);

    console.log(
      `\n[today-page] ${label} roles=${JSON.stringify(profile.targetRoles)} cities=${JSON.stringify(profile.targetLocations)} intensity=${intensity}\n` +
        `  ctx(悉尼4条并行)  改前 ${ctx.before.ms}ms/${kb(ctx.before.bytes)}kb（其中 job_actions ${ctx.before.actions}行 ${kb(ctx.before.actionBytes)}kb）` +
        ` → 改后 ${ctx.after.ms}ms/${kb(ctx.after.bytes)}kb（job_actions ${kb(ctx.after.actionBytes)}kb）\n` +
        `  recall(香港)      ${recallSize.rows}行 ${kb(recallSize.bytes)}kb ${recallSize.ms}ms tiers=${built.tiers.join("+")} 去重后 ${recallJobs.length}\n` +
        `  critical(香港)    ${watched.length}个关注岗 → ${criticalSize.rows}行 ${kb(criticalSize.bytes)}kb ${criticalSize.ms}ms（与 recall 并行）\n` +
        `  sourcemeta(悉尼)  按id ${sourceIds.length}源/${byIdRows.length}行 ${byIdMs}ms（串行在 recall 之后） vs 全表 ${allSources.length}行 ${kb(fullBytes)}kb ${fullMs}ms（可缓存·可并行） 快照与按id差异=${metaMismatch}源 差在[${[...mismatchFields.keys()].join(",") || "无"}] 影响行为的列(enabled/crawl_method)差异=${behaviourFields.length}\n` +
        `  compute(纯JS)     ${stage2.computeMs}ms（${rec.compute.perJobUs}µs/岗 × ${recallJobs.length} 岗） filtered=${JSON.stringify(stage2.filtered)}\n` +
        `  group(纯JS)       ${groupMs}ms\n` +
        `  hydrate(香港)     ${hydrateSize.rows}行 ${kb(hydrateSize.bytes)}kb ${hydrateSize.ms}ms\n` +
        `  props→浏览器      ${displayIds.length} 张卡 ${kb(propsBytes)}kb（HTML 里出现两次：markup + RSC payload）\n` +
        `  展示行逐列字节    ${top.join(" ")}\n` +
        `  等价性            主清单前20条逐条一致=${equivalence.top20Identical}（${equivalence.top20Before}/${equivalence.top20After} 条）` +
        ` 拒绝原因一致=${equivalence.filteredIdentical} 展示条数 ${equivalence.displayedBefore}→${equivalence.displayedAfter}`,
    );
  }

  fs.writeFileSync(OUT, JSON.stringify({ generated_at: now.toISOString(), sources: { rows: allSources.length, kb: kb(fullBytes), ms: fullMs }, users }, null, 1));
  console.log(`\n写入 ${OUT}`);
}

main().catch((e) => { console.error(e); process.exit(1); });

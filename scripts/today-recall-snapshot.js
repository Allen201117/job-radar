#!/usr/bin/env node
// /today 召回快照的后台刷新（.github/workflows/today-recall-snapshot.yml，每 6 小时一轮）。
//
// 为什么：/today 的召回 SQL 冷态要回表几万个堆块（库内 0.04~6s），挪出请求路径后页面只在
// 「快照选中的 id ∪ 快照之后才首见的岗」里重跑同一条 SQL（lib/jobs-store/opportunities.ts RecallRestriction）。
// 快照由两处写：这里（给所有画像就绪的用户定时刷新），以及用户打开页面后的 after()（现跑后回写 / 超 1 小时顺手刷新）。
// 两处调的是**同一个** refreshRecallSnapshot，写出来的快照口径逐字相同。
//
// 台账：ops_runs(module=today_recall_snapshot)，每轮一行；期望写在 crawler/audit_contract.yaml。
// 只写 today_recall_snapshots 一张表；不改任何用户数据、不碰 jobs。
//
// 跑法（本地需要 .env.local 的 JOBS_DATABASE_URL / SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY）：
//   node scripts/today-recall-snapshot.js            # 全部画像就绪的用户
//   node scripts/today-recall-snapshot.js --dry-run  # 只列出会刷新谁，不跑召回、不写库、不记台账
"use strict";
const path = require("path");
const { createClient } = require("@supabase/supabase-js");

const ROOT = path.join(__dirname, "..");
const { loadTs } = require(path.join(ROOT, "tests/_load-ts.js"));
const L = (rel) => loadTs(path.join(ROOT, rel));
const { recordOpsRun, statusFromCounts } = require(path.join(__dirname, "lib", "record-ops-run.js"));

const DRY_RUN = process.argv.includes("--dry-run");
// saved / ignored / applied 过的岗不占召回名额——与 lib/opportunities/service.ts 的 SQL 下推同一口径
const ACTIONED = new Set(["saved", "ignored", "applied"]);

async function fetchAll(query) {
  const out = [];
  for (let from = 0; ; from += 1000) {
    const { data, error } = await query().range(from, from + 999);
    if (error) throw new Error(error.message);
    out.push(...(data || []));
    if (!data || data.length < 1000) break;
  }
  return out;
}

const mask = (id) => String(id || "").slice(0, 8);
const quantile = (xs, q) => {
  const a = xs.filter(Number.isFinite).sort((x, y) => x - y);
  return a.length ? a[Math.min(a.length - 1, Math.floor(q * a.length))] : null;
};

async function main() {
  const startedAt = new Date();
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) throw new Error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 未配置");
  if (!DRY_RUN && !process.env.JOBS_DATABASE_URL) throw new Error("JOBS_DATABASE_URL 未配置");
  const sb = createClient(url, key, { auth: { persistSession: false } });

  const { buildRadarProfile, profileReadiness } = L("lib/opportunities/profile.ts");
  const prefs = await fetchAll(() => sb.from("user_preferences").select("*").order("user_id"));
  const cands = await fetchAll(() => sb.from("candidate_profiles").select("*").order("user_id"));
  const candBy = new Map(cands.map((c) => [c.user_id, c]));

  const ready = [];
  for (const p of prefs) {
    const profile = buildRadarProfile(p.user_id, p, candBy.get(p.user_id) || null);
    if (profileReadiness(profile).ready) ready.push({ userId: p.user_id, profile });
  }
  console.log(`[today-recall-snapshot] 画像就绪 ${ready.length} / 偏好行 ${prefs.length}`);
  if (DRY_RUN) {
    for (const u of ready) console.log(`  would refresh ${mask(u.userId)}`);
    return;
  }

  // 只取「占召回名额」的那三种动作；viewed 不参与 SQL 下推
  const actionRows = await fetchAll(() =>
    sb.from("job_actions").select("user_id, job_id, action").in("action", [...ACTIONED]).order("id"),
  );
  const actionedBy = new Map();
  for (const a of actionRows) {
    if (!ACTIONED.has(a.action)) continue;
    if (!actionedBy.has(a.user_id)) actionedBy.set(a.user_id, new Set());
    actionedBy.get(a.user_id).add(a.job_id);
  }

  const { refreshRecallSnapshot } = L("lib/jobs-store/opportunities.ts");
  const fetchMs = [];
  let refreshed = 0;
  let failed = 0;
  let rowsTotal = 0;
  let empty = 0;
  for (const u of ready) {
    try {
      const r = await refreshRecallSnapshot(u.userId, u.profile, new Date(), [...(actionedBy.get(u.userId) || [])], "cron");
      if (!r) {
        empty += 1; // 画像就绪但召回 SQL 建不出来（理论上不会发生，单独计数别混进成功）
        continue;
      }
      refreshed += 1;
      rowsTotal += r.rows;
      fetchMs.push(r.fetchMs);
      console.log(`  ${mask(u.userId)} rows=${r.rows} fetch_ms=${r.fetchMs}${r.capped ? " capped" : ""}`);
    } catch (e) {
      failed += 1;
      // 只打错误首行，并抹掉任何连接串（node-pg 的报错可能带主机名）
      const msg = String(e && e.message ? e.message : e).split("\n")[0].replace(/postgres(ql)?:\/\/\S+/g, "<url>");
      console.error(`  ${mask(u.userId)} 失败：${msg}`);
    }
  }

  const metrics = {
    users_ready: ready.length,
    refreshed,
    failed,
    no_recall: empty,
    rows_total: rowsTotal,
    fetch_ms_p50: quantile(fetchMs, 0.5),
    fetch_ms_p90: quantile(fetchMs, 0.9),
    fetch_ms_max: fetchMs.length ? Math.max(...fetchMs) : null,
    wall_ms: Date.now() - startedAt.getTime(),
  };
  console.log(`[today-recall-snapshot] ${JSON.stringify(metrics)}`);
  await recordOpsRun("today_recall_snapshot", metrics, statusFromCounts(ready.length, failed + empty), {
    startedAt,
    finishedAt: new Date(),
  });
  // 一个都没刷成功却有就绪用户 = 整条链坏了，让 workflow 红掉（台账已经写了 failed 状态）
  if (ready.length > 0 && refreshed === 0) process.exitCode = 1;
}

main()
  .catch((e) => {
    console.error("[today-recall-snapshot] 失败：", String(e && e.message ? e.message : e).replace(/postgres(ql)?:\/\/\S+/g, "<url>"));
    process.exitCode = 1;
  })
  .finally(async () => {
    // 连接池不关进程不会退出
    try {
      const { jobsPool } = L("lib/jobs-store/client.ts");
      if (typeof jobsPool === "function" && process.env.JOBS_DATABASE_URL) await jobsPool().end();
    } catch {
      /* 没建过池 / 已关 */
    }
  });

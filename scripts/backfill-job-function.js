#!/usr/bin/env node
/**
 * 职能物化：把 JS 侧的权威裁决（classifyJobFunction，**带 summary**）写进 jobs.job_function。
 *
 * 为什么要有这个脚本：判「产品/研发/设计…」的权威实现只有一份，在 JS
 * （lib/china-keyword-expansion.js 的 classifyJobFunction：标题权威优先 + 歧义标题看正文精修 + 完整单测）。
 * 校招看板过去在**渲染期**把几万条岗位的 JD 正文拖回函数现算职能分面 —— 又重又慢、撑不过
 * unstable_cache 后台重算超时 → 快照静默冻死（2026-09-15「全部数据待更新」的病根）。物化之后，
 * 看板读列不再拉正文、展开公司按职能筛全部岗位翻页也便宜。
 *
 * ⚠️ 计算口径**带 summary**（classifyJobFunction({title, summary})），与校招现有读路径逐字一致 ——
 *    这与 scripts/classify-job-function.js（只喂 title、服务于 insight 分布统计、宁可多判「其他」）
 *    是两种口径。物化到 jobs.job_function 用的是**这里带 summary 的口径**，别混。
 * ⚠️ 这里**只 UPDATE job_function 一列**：不碰 status / enrich_checked_at / last_seen_at
 *    （jobs 表有「upsert 不得抹掉富化簿记」的既有不变量，见 CLAUDE.md）。
 *
 * 用法（与 backfill-recruitment-category 一致）：
 *   node scripts/backfill-job-function.js --check          只读对拍，报告差异，绝不写库
 *   node scripts/backfill-job-function.js --apply          只填 NULL 的行
 *   node scripts/backfill-job-function.js --apply --all    重算并覆盖全部行
 *   可选 --limit N（只处理前 N 行，用于小样本试跑）  --batch N（默认 2000）
 */
"use strict";

const { Pool } = require("pg");
const path = require("path");
const { buildJobsDatabaseSsl } = require(path.join(__dirname, "..", "lib", "jobs-store", "tls-options.js"));
const { classifyJobFunction } = require(path.join(__dirname, "..", "lib", "china-keyword-expansion.js"));
const { recordOpsRun, statusFromCounts } = require(path.join(__dirname, "lib", "record-ops-run.js"));

const argv = process.argv.slice(2);
const has = (f) => argv.includes(f);
const num = (f, d) => {
  const i = argv.indexOf(f);
  return i >= 0 && argv[i + 1] ? Number(argv[i + 1]) : d;
};

const CHECK = has("--check");
const APPLY = has("--apply");
const ALL = has("--all");
const LIMIT = num("--limit", Infinity);
const BATCH = num("--batch", 2000);

if (CHECK === APPLY) {
  console.error("必须且只能指定一个模式：--check（只读对拍）或 --apply（写库）");
  process.exit(2);
}

// classifyJobFunction 只读 title + summary（刻意不含 job_type，见其注释）。多读一列都是白传（39 万行很可观）。
const COLS = "id, title, summary";

function makePool() {
  const url = process.env.JOBS_DATABASE_URL;
  if (!url) {
    console.error("JOBS_DATABASE_URL 未配置");
    process.exit(2);
  }
  const u = new URL(url);
  return new Pool({
    host: u.hostname,
    port: u.port ? Number(u.port) : 5432,
    user: decodeURIComponent(u.username),
    password: decodeURIComponent(u.password),
    database: u.pathname.replace(/^\//, "") || "jobradar_jobs",
    ssl: buildJobsDatabaseSsl(process.env, u.hostname),
    max: 2,
    connectionTimeoutMillis: 15_000,
    statement_timeout: 120_000,
  });
}

async function main() {
  const pool = makePool();
  // 全程用同一条连接，并在会话上打「重算任务」的身份标记。
  // 库里的触发器 jobs_guard_job_function（jobs-db/schema.sql）替这一列把门：分类输入(title/summary)没变时
  // 任何人想改它都会被驳回（因为写入方算分类用「本次瘦 payload」、落库走 COALESCE 保留旧富字段，会对不上）。
  // 本脚本是唯一例外：它读的就是库里最终那一行，结论必然自洽。
  // ⚠️ 不打这个标记 = 写库静默变成空操作（不报错，只是「跑完了但一行没改」）。
  const client = await pool.connect();
  await client.query("set jobradar.reclassify = 'on'");
  const t0 = Date.now();
  // keyset 翻页：按 id 顺序推进，避免大 offset 在 42 万行上退化成全扫。
  let cursor = "00000000-0000-0000-0000-000000000000";
  let seen = 0, changed = 0, written = 0;
  const mismatch = { total: 0, byPair: new Map(), samples: [] };

  for (;;) {
    if (seen >= LIMIT) break;
    const take = Math.min(BATCH, LIMIT - seen);
    // --all 或 --check 看全部行；默认 --apply 只补没算过的（NULL）。
    const onlyNull = APPLY && !ALL;
    const { rows } = await client.query(
      `select ${COLS}, job_function as _fn
         from jobs
        where id > $1 ${onlyNull ? "and job_function is null" : ""}
        order by id
        limit $2`,
      [cursor, take],
    );
    if (!rows.length) break;
    cursor = rows[rows.length - 1].id;
    seen += rows.length;

    const updates = [];
    for (const r of rows) {
      const fn = classifyJobFunction(r);
      if (r._fn === fn) continue;
      changed++;
      // 只有「已经存过值、却和现算的不一致」才算真差异（NULL 是「还没算」，不是分歧）。
      if (r._fn !== null) {
        mismatch.total++;
        const key = `存的 ${r._fn} → 现算 ${fn}`;
        mismatch.byPair.set(key, (mismatch.byPair.get(key) || 0) + 1);
        if (mismatch.samples.length < 10) {
          mismatch.samples.push(`${key}  «${String(r.title || "").slice(0, 34)}»`);
        }
      }
      updates.push([r.id, fn]);
    }

    if (APPLY && updates.length) {
      // 一次 UPDATE ... FROM (VALUES ...) 批量写回；只动这一列。
      const vals = updates
        .map((_, i) => `($${i * 2 + 1}::uuid, $${i * 2 + 2}::text)`)
        .join(",");
      await client.query(
        `update jobs set job_function = v.fn
           from (values ${vals}) as v(id, fn)
          where jobs.id = v.id`,
        updates.flat(),
      );
      written += updates.length;
    }

    if (seen % 20000 < BATCH) {
      process.stdout.write(`  已处理 ${seen} 行（${((Date.now() - t0) / 1000).toFixed(0)}s）\n`);
    }
  }

  console.log(`\n模式：${CHECK ? "只读对拍" : ALL ? "全量重算写入" : "只补 NULL"}`);
  console.log(`扫描 ${seen} 行，需要变更 ${changed} 行${APPLY ? `，已写入 ${written} 行` : ""}`);
  if (mismatch.total > 0) {
    console.log(`\n⚠️ 已存值与现算值不一致：${mismatch.total} 行`);
    [...mismatch.byPair.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10)
      .forEach(([k, v]) => console.log(`   ${String(v).padStart(6)}  ${k}`));
    console.log("  抽样：");
    mismatch.samples.forEach((s) => console.log(`   · ${s}`));
  } else {
    console.log("已存值与现算值：0 处不一致 ✅");
  }
  console.log(`耗时 ${((Date.now() - t0) / 1000).toFixed(1)}s`);
  client.release();
  await pool.end();

  await recordOpsRun(
    "backfill_job_function",
    { mode: CHECK ? "check" : ALL ? "apply_all" : "apply_null", scanned: seen, changed, written, mismatch: mismatch.total },
    statusFromCounts(seen, 0),
    { startedAt: new Date(t0) },
  );
}

main().catch(async (e) => {
  console.error("失败：", e.message);
  await recordOpsRun("backfill_job_function", { error: String(e.message || e).slice(0, 200) }, "failed");
  process.exit(1);
});

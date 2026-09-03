#!/usr/bin/env node
/**
 * 招聘类型物化：把 JS 侧的权威裁决（recruitmentCategory / hasExplicitRecruitmentType）
 * 写进 jobs.recruitment_category / jobs.recruitment_explicit。
 *
 * 为什么要有这个脚本：判「社招/校招/实习」的权威实现只有一份，在 JS
 * （lib/china-keyword-expansion.js 的七层裁决 + 完整单测）。检索侧（SQL）过去只能用
 * 「正向信号并集」去近似，两套判据结构不同 → 必然捞进大量注定被否决的岗。物化之后，
 * 检索与筛选查同一个字段，结构上不可能再不一致。
 *
 * ⚠️ 两列必须同时写：job-filter.jobFilterMatch 同时用到「是什么类型」和「有没有明确依据」
 *    （无依据时：选社招放行降级、选校招/实习淘汰）。只写一个 = SQL 仍然表达不了这条规则。
 * ⚠️ 这里**不做任何 UPDATE 以外的事**：不碰 status、不碰 enrich_checked_at、不碰 last_seen_at。
 *    （jobs 表有「upsert 不得抹掉富化簿记」的既有不变量，见 CLAUDE.md。）
 *
 * 用法：
 *   node scripts/backfill-recruitment-category.js --check            只读对拍，报告差异，绝不写库
 *   node scripts/backfill-recruitment-category.js --apply            只填 NULL 的行
 *   node scripts/backfill-recruitment-category.js --apply --all      重算并覆盖全部行
 *   可选 --limit N（只处理前 N 行，用于小样本试跑）  --batch N（默认 2000）
 */
"use strict";

const { Pool } = require("pg");
const path = require("path");
const { buildJobsDatabaseSsl } = require(path.join(__dirname, "..", "lib", "jobs-store", "tls-options.js"));
const {
  recruitmentCategory,
  hasExplicitRecruitmentType,
} = require(path.join(__dirname, "..", "lib", "china-keyword-expansion.js"));

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

// 打分只读这些列 —— 与 recruitmentCategory / hasExplicitRecruitmentType 的输入完全一致。
// 多读一列都是白传（39 万行 × 一列很可观）；少读一列会静默算错。
const COLS = "id, title, summary, jd_url, apply_url, job_type, company, experience";

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

const classify = (row) => ({
  cat: recruitmentCategory(row),
  exp: hasExplicitRecruitmentType(row),
});

async function main() {
  const pool = makePool();
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
    const { rows } = await pool.query(
      `select ${COLS}, recruitment_category as _cat, recruitment_explicit as _exp
         from jobs
        where id > $1 ${onlyNull ? "and recruitment_category is null" : ""}
        order by id
        limit $2`,
      [cursor, take],
    );
    if (!rows.length) break;
    cursor = rows[rows.length - 1].id;
    seen += rows.length;

    const updates = [];
    for (const r of rows) {
      const { cat, exp } = classify(r);
      const same = r._cat === cat && r._exp === exp;
      if (same) continue;
      changed++;
      // 只有「已经存过值、却和现算的不一致」才算真差异（NULL 是「还没算」，不是分歧）。
      if (r._cat !== null) {
        mismatch.total++;
        const key = `存的 ${r._cat}/${r._exp} → 现算 ${cat}/${exp}`;
        mismatch.byPair.set(key, (mismatch.byPair.get(key) || 0) + 1);
        if (mismatch.samples.length < 10) {
          mismatch.samples.push(`${key}  «${String(r.title || "").slice(0, 34)}»`);
        }
      }
      updates.push([r.id, cat, exp]);
    }

    if (APPLY && updates.length) {
      // 一次 UPDATE ... FROM (VALUES ...) 批量写回；只动这两列。
      const vals = updates
        .map((_, i) => `($${i * 3 + 1}::uuid, $${i * 3 + 2}::text, $${i * 3 + 3}::boolean)`)
        .join(",");
      await pool.query(
        `update jobs set recruitment_category = v.cat, recruitment_explicit = v.exp
           from (values ${vals}) as v(id, cat, exp)
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
  await pool.end();
}

main().catch((e) => {
  console.error("失败：", e.message);
  process.exit(1);
});

#!/usr/bin/env node
// 画像卫生体检（**只读**，没有也不会有 --apply）。
//
// 用途：报出「脏画像」的真实规模与成因占比，给创始人拍板存量怎么处置提供数字。
// 判据全部复用 lib/profile-hygiene.auditProfile —— 与线上落库归一同一份代码，
// 体检说脏的写法，保存时真的能收拾它；两边漂了这张表就没意义。
//
// 🚫 绝不改用户数据：改存量画像 = 改用户自己填的求职意图，必须创始人拍板（见 CLAUDE.md）。
// 🚫 不打印邮箱 / 姓名 / 完整 user_id（只取前 8 位）。
//
//   node scripts/profile-hygiene/audit.mjs            # 汇总表
//   node scripts/profile-hygiene/audit.mjs --detail   # 逐个用户的问题清单（脱敏）
//   node scripts/profile-hygiene/audit.mjs --json     # 机器可读
//
// 需要 .env.local 里的 SUPABASE_DB_URL（user_preferences / candidate_profiles 都在 Supabase）。
import { createRequire } from "node:module";
import pg from "pg";

const require = createRequire(import.meta.url);
const { auditProfile } = require("../../lib/profile-hygiene.js");

const args = new Set(process.argv.slice(2));
const wantDetail = args.has("--detail");
const wantJson = args.has("--json");

const CONNECTION = process.env.SUPABASE_DB_URL || process.env.DATABASE_URL;
if (!CONNECTION) {
  console.error("缺 SUPABASE_DB_URL（先 `set -a; source .env.local; set +a`）");
  process.exit(1);
}

// 来源归因：radar_intensity_source 只记强度是谁改的，跟画像字段无关，不能当来源判据。
// 能拿到的第一手证据只有「有没有简历档案」+「偏好与档案的字段是否逐字相同」：
//   · 没有 candidate_profiles 行，或档案里这一项是空   → 只可能是手填（hand）
//   · 档案里这一项非空、且与偏好逐字相同               → 大概率是简历解析写进去的（resume）
//   · 档案里这一项非空、但与偏好不同                   → 用户在偏好页改过（hand_edited）
// 这是**观测**不是结论：简历解析写进去后用户原样保留，也会落进 resume 桶。报数时照此口径说。
function attributeSource(prefValues, candValues, hasProfile) {
  const cand = candValues || [];
  if (!hasProfile || cand.length === 0) return "hand";
  return JSON.stringify(prefValues || []) === JSON.stringify(cand) ? "resume" : "hand_edited";
}

const SQL = `
  select
    left(p.user_id::text, 8) as uid,
    p.target_roles, p.target_keywords, p.target_locations, p.target_industries,
    p.experience_stage, p.job_scope, p.has_en_resume,
    c.user_id is not null as has_profile,
    c.target_roles as c_target_roles,
    c.target_locations as c_target_locations,
    c.industries as c_industries,
    c.experience_stage as c_experience_stage,
    c.has_en_resume as c_has_en_resume
  from user_preferences p
  left join candidate_profiles c on c.user_id = p.user_id
  order by p.updated_at desc
`;

const client = new pg.Client({ connectionString: CONNECTION });
await client.connect();
const { rows } = await client.query(SQL);
await client.end();

const issueCounts = new Map();
const sourceCounts = { roles: {}, locations: {}, industries: {} };
const details = [];
const dirtyValueSource = {
  roles: { resume: [], hand: [] },
  locations: { resume: [], hand: [] },
};

for (const row of rows) {
  const preferences = {
    target_roles: row.target_roles,
    target_keywords: row.target_keywords,
    target_locations: row.target_locations,
    target_industries: row.target_industries,
    experience_stage: row.experience_stage,
    job_scope: row.job_scope,
    has_en_resume: row.has_en_resume,
  };
  const candidate = row.has_profile
    ? { experience_stage: row.c_experience_stage, has_en_resume: row.c_has_en_resume }
    : null;
  const { issues, details: d } = auditProfile({ preferences, candidate });
  for (const code of issues) issueCounts.set(code, (issueCounts.get(code) || 0) + 1);

  for (const [field, prefV, candV] of [
    ["roles", row.target_roles, row.c_target_roles],
    ["locations", row.target_locations, row.c_target_locations],
    ["industries", row.target_industries, row.c_industries],
  ]) {
    const src = attributeSource(prefV, candV, row.has_profile);
    sourceCounts[field][src] = (sourceCounts[field][src] || 0) + 1;
  }

  // 逐个**脏值**归因（比逐用户归因有用：要知道该去修 prompt 还是修手填入口，
  // 得看脏值本身是不是简历解析写进去的）。判据：这个值是否逐字出现在 candidate_profiles 里。
  const candRoleSet = new Set(row.c_target_roles || []);
  const candCitySet = new Set(row.c_target_locations || []);
  for (const v of d.roles.dirty) dirtyValueSource.roles[candRoleSet.has(v) ? "resume" : "hand"].push(v);
  for (const v of d.locations.multiValue)
    dirtyValueSource.locations[candCitySet.has(v) ? "resume" : "hand"].push(v);

  if (issues.length) details.push({ uid: row.uid, issues, detail: d });
}

const total = rows.length;
const summary = {
  total_profiles: total,
  with_resume_profile: rows.filter((r) => r.has_profile).length,
  issues: Object.fromEntries(
    [...issueCounts.entries()].sort((a, b) => b[1] - a[1]).map(([k, v]) => [k, v]),
  ),
  source_attribution: sourceCounts,
  dirty_value_source: dirtyValueSource,
  clean_profiles: total - details.length,
};

if (wantJson) {
  console.log(JSON.stringify({ summary, details: wantDetail ? details : undefined }, null, 2));
} else {
  console.log(`画像总数 ${total}（其中有简历档案 ${summary.with_resume_profile}）；完全干净 ${summary.clean_profiles}`);
  console.log("");
  console.log("问题码".padEnd(28) + "命中画像数".padStart(10) + "占比".padStart(9));
  console.log("-".repeat(47));
  for (const [code, n] of Object.entries(summary.issues)) {
    console.log(code.padEnd(28) + String(n).padStart(10) + `${((n / total) * 100).toFixed(1)}%`.padStart(9));
  }
  console.log("");
  console.log("来源归因 · 逐画像（观测口径见文件头注释）：");
  for (const [field, counts] of Object.entries(sourceCounts)) {
    console.log(`  ${field.padEnd(12)} ${JSON.stringify(counts)}`);
  }
  console.log("\n来源归因 · 逐个脏值（该去修 prompt 还是修手填入口）：");
  for (const [field, buckets] of Object.entries(dirtyValueSource)) {
    console.log(
      `  ${field.padEnd(12)} 简历解析 ${buckets.resume.length} / 手填 ${buckets.hand.length}`,
    );
    if (buckets.resume.length) console.log(`    简历：${JSON.stringify(buckets.resume)}`);
    if (buckets.hand.length) console.log(`    手填：${JSON.stringify(buckets.hand)}`);
  }
  if (wantDetail) {
    console.log("\n逐画像明细（user_id 仅前 8 位）：");
    for (const d of details) console.log(`  ${d.uid}  ${d.issues.join(", ")}`);
  }
}

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

// 脚本读 jobs 一律走香港库（2026-09-24 立）：Supabase 的 jobs 自 Phase 1（2026-06-19）起不是真数据（09-24 实测 0 行），
// scripts/ 里三个脚本照旧 `sb.from("jobs")`，对着空表恒报「无重复 / 库为空」两个半月——
// audit-job-duplicates 还是 CLAUDE.md 让人在上唯一约束迁移前跑的那一个。
const ROOT = path.join(__dirname, "..");
const SCRIPTS = path.join(ROOT, "scripts");

function scriptFiles(dir, out = []) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "node_modules" || ent.name.startsWith(".")) continue;
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) scriptFiles(p, out);
    else if (/\.(ts|tsx|js|jsx|mjs|cjs)$/.test(ent.name)) out.push(p);
  }
  return out;
}

test("scripts/ 不许用 supabase-js 读 jobs 表（该读 JOBS_DATABASE_URL）", () => {
  const offenders = [];
  for (const file of scriptFiles(SCRIPTS)) {
    const src = fs.readFileSync(file, "utf8");
    if (/\.from\(\s*["'`]jobs["'`]\s*\)/.test(src)) offenders.push(path.relative(ROOT, file));
  }
  assert.deepEqual(offenders, [], `这些脚本读的是 Supabase 的 jobs（空表）：\n${offenders.join("\n")}`);
});

test("audit-job-duplicates：读香港库、keyset 翻页以 id 收尾、不用 offset", () => {
  const src = fs.readFileSync(path.join(SCRIPTS, "audit-job-duplicates.js"), "utf8");
  assert.match(src, /require\("\.\/lib\/psql\.js"\)/, "必须经 runPsql 读香港库（连接串走环境变量）");
  assert.doesNotMatch(src, /@supabase\/supabase-js/);
  assert.match(src, /\(first_seen_at, id\) < \(/, "翻页必须是 (first_seen_at, id) keyset");
  assert.match(src, /order by first_seen_at desc, id desc limit/);
  assert.doesNotMatch(src, /\boffset\b\s*\$?\d|\.range\(/i, "不许 offset / range 翻页");
  assert.match(src, /default_transaction_read_only=on/, "会话必须只读");
});

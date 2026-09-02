// 契约测试：确保 insight 相关路由对大表（company_profiles / insight_items 等）的
// .from("表").select( 调用必须携带分页或精确过滤，防止 PostgREST 1000 行静默截断。
//
// 判据：.from("表").select( 出现后 8 行内须有以下之一：
//   .range(          — fetchAllPages 分页
//   fetchAllPages    — 分页 helper
//   .in(             — 按 id 列表过滤（精确集合，行数已知）
//   .eq("id"         — 单行精确查询
//   .eq("company_id" — 按外键过滤（单公司）
//   .eq("user_id"    — 按用户 id 过滤（个人数据）
//   .eq("status"     — 按 status 过滤（有界集合，搭配其他条件使用）
//   maybeSingle      — 0-1 行
//   single()         — 恰好 1 行
//   head: true       — 只取 count，不取行

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const ROOT = path.resolve(__dirname, "..");

function read(rel) {
  return fs.readFileSync(path.resolve(ROOT, rel), "utf8");
}

// 被审查的表（超过或接近 1000 行的表）
const LARGE_TABLES = [
  "company_profiles",
  "insight_items",
  "insight_sources",
  "insight_item_sources",
  "company_watch_requests",
  "sources",
];

// 允许的分页/过滤模式
const SAFE_PATTERNS = [
  /\.range\s*\(/,
  /fetchAllPages/,
  /\.in\s*\(/,
  /\.eq\s*\(\s*["']id["']/,
  /\.eq\s*\(\s*["']company_id["']/,
  /\.eq\s*\(\s*["']user_id["']/,
  /\.eq\s*\(\s*["']status["']/,
  /\.eq\s*\(\s*["']item_id["']/,
  /\.eq\s*\(\s*["']normalized_company["']/,
  /maybeSingle/,
  /single\s*\(\s*\)/,
  /head\s*:\s*true/,
  /\.upsert\s*\(/,    // upsert 是写操作不是读
  /\.insert\s*\(/,    // insert 是写操作
  /\.update\s*\(/,    // update 是写操作
  /\.delete\s*\(/,    // delete 是写操作
];

// 被审查的文件列表
const FILES = [
  "app/api/insights/availability/route.ts",
  "app/api/insights/route.ts",
  "app/api/insights/submit/route.ts",
  "app/api/career-path/route.ts",
  "app/api/insights/admin/route.ts",
  "app/api/insights/admin/cycles/route.ts",
  "app/api/insights/admin/submissions/route.ts",
  "app/api/company-watch/admin/route.ts",
  "app/api/sources/route.ts",
];

/**
 * 给定文件源码，返回所有对大表的 .from("TABLE").select( 调用，并检查其后 8 行内是否有安全模式。
 * 返回违规条目：{ file, lineNo, table, snippet }。
 */
function findViolations(src, filePath) {
  const lines = src.split("\n");
  const violations = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    for (const table of LARGE_TABLES) {
      // 检测 .from("TABLE") 后接 .select( 的模式（同行或隔行）
      const fromPattern = new RegExp(`\\.from\\(\\s*["']${table}["']\\s*\\)`);
      if (!fromPattern.test(line)) continue;

      // 取当前行 + 后 8 行作为检查窗口
      const window = lines.slice(i, i + 9).join("\n");

      // 检查窗口内是否有 .select(
      if (!/\.select\s*\(/.test(window)) continue;

      // 检查是否有安全模式
      const isSafe = SAFE_PATTERNS.some((p) => p.test(window));
      if (!isSafe) {
        violations.push({
          file: filePath,
          lineNo: i + 1,
          table,
          snippet: window.split("\n").slice(0, 4).join(" ↵ ").trim(),
        });
      }
    }
  }
  return violations;
}

test("insight 路由对大表的 select 必须携带分页或精确过滤", () => {
  const allViolations = [];
  for (const file of FILES) {
    const src = read(file);
    const violations = findViolations(src, file);
    allViolations.push(...violations);
  }

  if (allViolations.length > 0) {
    const msg = allViolations
      .map((v) => `  ${v.file}:${v.lineNo} [${v.table}] → ${v.snippet}`)
      .join("\n");
    assert.fail(
      `发现 ${allViolations.length} 处对大表的整表读（缺少 .range / fetchAllPages / .in / .eq 等）：\n${msg}`,
    );
  }
});

test("availability/route.ts 不再对 company_profiles 做整表 select *", () => {
  const src = read("app/api/insights/availability/route.ts");
  const hasRawSelect = /from\s*\(\s*["']company_profiles["']\s*\)\s*\n?\s*\.select\s*\(\s*["']\*["']/.test(src);
  assert.ok(!hasRawSelect, "availability route 不应再做 company_profiles select('*') 整表读");
});

test("availability/route.ts 引用 getCachedCompanyProfilesLight 和 getCachedActiveJobCounts", () => {
  const src = read("app/api/insights/availability/route.ts");
  assert.ok(src.includes("getCachedCompanyProfilesLight"), "应引用 getCachedCompanyProfilesLight");
  assert.ok(src.includes("getCachedActiveJobCounts"), "应引用 getCachedActiveJobCounts");
});

test("career-path/route.ts 不再直接调 activeJobCountsByCompany，改走缓存", () => {
  const src = read("app/api/career-path/route.ts");
  assert.ok(!src.includes("activeJobCountsByCompany"), "career-path 应改走 getCachedActiveJobCounts，不直接调 activeJobCountsByCompany");
  assert.ok(src.includes("getCachedActiveJobCounts"), "应引用 getCachedActiveJobCounts");
});

test("insight-availability-cache.ts 存在且包含 unstable_cache 和两个导出", () => {
  const src = read("lib/insight-availability-cache.ts");
  assert.ok(src.includes("unstable_cache"), "缓存文件应使用 unstable_cache");
  assert.ok(src.includes("getCachedCompanyProfilesLight"), "应导出 getCachedCompanyProfilesLight");
  assert.ok(src.includes("getCachedActiveJobCounts"), "应导出 getCachedActiveJobCounts");
  // 缓存函数体内应使用 createServiceClient，不能调用 cookies()/headers()（排除注释行）
  assert.ok(src.includes("createServiceClient"), "缓存函数内应使用 service-role 客户端");
  const codeLines = src.split("\n").filter((l) => !l.trim().startsWith("//") && !l.trim().startsWith("*"));
  const codeOnly = codeLines.join("\n");
  assert.ok(!/\bcookies\s*\(\s*\)/.test(codeOnly), "缓存函数体内不能调用 cookies()");
  assert.ok(!/\bheaders\s*\(\s*\)/.test(codeOnly), "缓存函数体内不能调用 headers()");
});

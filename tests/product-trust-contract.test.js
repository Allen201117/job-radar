const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const jobCardSource = fs.readFileSync(path.join(__dirname, "..", "components", "JobCard.tsx"), "utf8");
const schemaSource = fs.readFileSync(path.join(__dirname, "..", "jobs-db", "schema.sql"), "utf8");

function sqlFunctionBody(name) {
  const escapedName = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = schemaSource.match(
    new RegExp(
      `create\\s+or\\s+replace\\s+function\\s+${escapedName}\\s*\\(\\s*\\)[\\s\\S]*?as\\s+\\$function\\$([\\s\\S]*?)\\$function\\$\\s*;`,
      "i",
    ),
  );
  assert.ok(match, `expected to find SQL body for ${name}()`);
  return match[1];
}

test("posted_at 元数据明确标注为官网发布日期", () => {
  assert.match(jobCardSource, /\{\s*key:\s*"posted"\s*,[^}]*\blabel:\s*"官网发布"[^}]*\}/);
});

test("active_job_counts_by_company 排除 summary 为 null 的薄卡", () => {
  assert.match(sqlFunctionBody("active_job_counts_by_company"), /j\.summary\s+is\s+not\s+null/i);
});

test("active_job_counts_by_company 只计算去空白后正文不少于 60 字的岗位", () => {
  assert.match(
    sqlFunctionBody("active_job_counts_by_company"),
    /char_length\s*\(\s*btrim\s*\(\s*j\.summary\s*\)\s*\)\s*>=\s*60/i,
  );
});

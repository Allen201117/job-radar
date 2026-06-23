const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.resolve(__dirname, "../lib/jobs-store/opportunities.ts"),
  "utf8",
);

// 召回只传硬门 + 打分必需列（截断 summary）；展示用列由 service 对最终少量卡片回填（hydration）。
test("opportunity recall transfers only engine-required candidate fields", () => {
  const start = source.indexOf("const RECALL_COLUMNS");
  const end = source.indexOf("\n\nfunction roleTsquery", start);
  const columns = source.slice(start, end);

  for (const required of [
    "id",
    "source_id",
    "company",
    "title",
    "location",
    "job_type",
    "summary",
    "jd_url",
    "salary_text",
    "first_seen_at",
    "last_seen_at",
    "status",
    "education",
  ]) {
    assert.ok(columns.includes(required), `missing engine field: ${required}`);
  }

  for (const displayOnly of [
    "apply_url",
    "posted_at",
    "content_hash",
    "created_at",
    "experience",
    "deadline",
    "enrich_fail_count",
    "enrich_checked_at",
    "canonical_jd_url",
  ]) {
    assert.ok(!columns.includes(displayOnly), `recall still transfers display field: ${displayOnly}`);
  }
});

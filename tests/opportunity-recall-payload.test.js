const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.resolve(__dirname, "../lib/jobs-store/opportunities.ts"),
  "utf8",
);

// 召回只传硬门 + 打分 + **分层核验/信号派生**必需列（截断 summary）；纯展示用列由 service 回填（hydration）。
// v3：enrich_checked_at（today 24h 硬门）、posted_at/deadline（STILL_OPEN/DEADLINE_SOON 在回填前派生）必须带回——
// 均为短字段/时间戳，载荷可忽略（P0-1 的重载荷是长 summary，已截断）。
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
    "country_code",
    "job_scope",
    "job_type",
    "summary",
    "jd_url",
    "salary_text",
    "first_seen_at",
    "last_seen_at",
    "status",
    "education",
    // v3 引擎必需（非纯展示）：
    "enrich_checked_at",
    "posted_at",
    "deadline",
  ]) {
    assert.ok(columns.includes(required), `missing engine field: ${required}`);
  }

  // 纯展示列仍不得进召回（长正文 / 重字段 / 引擎不读）。
  for (const displayOnly of [
    "apply_url",
    "content_hash",
    "created_at",
    "experience",
    "enrich_fail_count",
    "canonical_jd_url",
  ]) {
    assert.ok(!columns.includes(displayOnly), `recall still transfers display field: ${displayOnly}`);
  }
});

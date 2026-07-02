const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildInsightEnrichRunRecord,
  buildInsightWorkflowInputs,
  evaluateInsightEnrichDispatch,
  normalizeInsightCompany,
} = require("../lib/insight-enrich-now");

const NOW = Date.parse("2026-06-22T12:00:00.000Z");

test("normalizeInsightCompany trims and folds simple case without changing Chinese names", () => {
  assert.equal(normalizeInsightCompany("  Apple  "), "apple");
  assert.equal(normalizeInsightCompany(" 比亚迪 "), "比亚迪");
});

test("evaluateInsightEnrichDispatch reuses in-flight same-company run", () => {
  const decision = evaluateInsightEnrichDispatch(
    [
      {
        id: "run-1",
        status: "queued",
        created_at: "2026-06-22T11:59:00.000Z",
        diagnostics: { company: "Apple" },
      },
    ],
    "apple",
    NOW,
    { cooldownHours: 6, hourlyCap: 5 },
  );
  assert.equal(decision.action, "reuse");
  assert.equal(decision.run.id, "run-1");
});

test("evaluateInsightEnrichDispatch blocks repeated same-company dispatch during cooldown", () => {
  const decision = evaluateInsightEnrichDispatch(
    [
      {
        id: "run-2",
        status: "success",
        created_at: "2026-06-22T10:00:00.000Z",
        diagnostics: { company: "Apple" },
      },
    ],
    "Apple",
    NOW,
    { cooldownHours: 6, hourlyCap: 5 },
  );
  assert.equal(decision.action, "cooldown");
  assert.ok(decision.retryAfterSec > 0);
});

test("evaluateInsightEnrichDispatch enforces global hourly cap", () => {
  const recentRuns = [1, 2, 3].map((i) => ({
    id: `run-${i}`,
    status: "success",
    created_at: `2026-06-22T11:${50 + i}:00.000Z`,
    diagnostics: { company: `Company ${i}` },
  }));
  const decision = evaluateInsightEnrichDispatch(recentRuns, "ByteDance", NOW, {
    cooldownHours: 6,
    hourlyCap: 3,
  });
  assert.equal(decision.action, "global_cap");
  assert.ok(decision.retryAfterSec > 0);
});

test("evaluateInsightEnrichDispatch allows dispatch when neither cooldown nor cap applies", () => {
  const decision = evaluateInsightEnrichDispatch(
    [
      {
        id: "old",
        status: "success",
        created_at: "2026-06-22T01:00:00.000Z",
        diagnostics: { company: "Apple" },
      },
    ],
    "ByteDance",
    NOW,
    { cooldownHours: 6, hourlyCap: 5 },
  );
  assert.equal(decision.action, "dispatch");
});

test("buildInsightEnrichRunRecord records queued insight_enrich run", () => {
  const record = buildInsightEnrichRunRecord({
    runId: "run-9",
    userId: "user-1",
    company: "Apple",
    startedAt: "2026-06-22T12:00:00.000Z",
  });
  assert.equal(record.id, "run-9");
  assert.equal(record.user_id, "user-1");
  assert.equal(record.mode, "insight_enrich");
  assert.equal(record.status, "queued");
  assert.equal(record.provider_name, "insight_enrich");
  assert.equal(record.query, "Apple");
  assert.deepEqual(record.diagnostics.company, "Apple");
});

test("buildInsightWorkflowInputs passes a single company to the workflow", () => {
  assert.deepEqual(buildInsightWorkflowInputs({ company: "  Apple  ", runId: "run-9" }), {
    company: "Apple",
    limit: "1",
    run_id: "run-9",
  });
});

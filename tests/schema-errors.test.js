const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { isMissingRelation, isMissingFunction } = loadOpp("schema-errors");

test("isMissingRelation: PostgREST 缺表 PGRST205（不含 'does not exist'）", () => {
  assert.equal(
    isMissingRelation({
      code: "PGRST205",
      message: "Could not find the table 'public.company_watch_requests' in the schema cache",
    }),
    true,
  );
});

test("isMissingRelation: 直连 PG 42P01 / 文本兜底", () => {
  assert.equal(isMissingRelation({ code: "42P01", message: 'relation "x" does not exist' }), true);
  assert.equal(isMissingRelation({ message: "relation does not exist" }), true);
});

test("isMissingRelation: 普通错误 / 空 → false", () => {
  assert.equal(isMissingRelation({ code: "23505", message: "duplicate key" }), false);
  assert.equal(isMissingRelation(null), false);
  assert.equal(isMissingRelation(undefined), false);
});

test("isMissingFunction: 缺 RPC PGRST202 / 42883 / 文本", () => {
  assert.equal(isMissingFunction({ code: "PGRST202", message: "Could not find the function set_job_primary_action" }), true);
  assert.equal(isMissingFunction({ code: "42883", message: "function foo() does not exist" }), true);
  assert.equal(isMissingFunction({ message: "could not find the function" }), true);
});

test("isMissingFunction: 普通错误 → false", () => {
  assert.equal(isMissingFunction({ code: "P0001", message: "not authenticated" }), false);
  assert.equal(isMissingFunction(null), false);
});

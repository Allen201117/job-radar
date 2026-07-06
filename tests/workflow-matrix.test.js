const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

function workflow(name) {
  return fs.readFileSync(path.join(__dirname, "..", ".github", "workflows", name), "utf8");
}

function matrixAdapters(text) {
  const match = text.match(/adapter:\s*\[([^\]]+)\]/m);
  assert.ok(match, "adapter matrix not found");
  return new Set(
    match[1]
      .split(",")
      .map((adapter) => adapter.trim())
      .filter(Boolean),
  );
}

function maxParallel(text) {
  const match = text.match(/max-parallel:\s*(\d+)/m);
  return match ? Number(match[1]) : null;
}

test("enrich-backlog drains supported overseas httpx detail adapters", () => {
  const adapters = matrixAdapters(workflow("enrich-backlog.yml"));

  for (const adapter of [
    "workday",
    "oracle",
    "eightfold",
    "smartrecruiters",
    "greenhouse",
    "lever",
    "amazon",
    "microsoft",
  ]) {
    assert.equal(adapters.has(adapter), true, adapter);
  }

  assert.equal(adapters.has("phenom"), false);
  assert.equal(adapters.has("google"), false);
});

test("enrich-backlog caps adapter fan-out after overseas matrix expansion", () => {
  assert.equal(maxParallel(workflow("enrich-backlog.yml")), 5);
});

test("liveness-sweep covers overseas httpx closure-capable adapters", () => {
  const adapters = matrixAdapters(workflow("liveness-sweep.yml"));

  for (const adapter of [
    "workday",
    "oracle",
    "eightfold",
    "smartrecruiters",
    "greenhouse",
    "lever",
    "amazon",
    "microsoft",
  ]) {
    assert.equal(adapters.has(adapter), true, adapter);
  }

  assert.equal(adapters.has("phenom"), false);
  assert.equal(adapters.has("google"), false);
});

test("dead-link-audit main rotation reserves capacity for must-apply companies", () => {
  const text = workflow("dead-link-audit.yml");

  assert.match(text, /--must-apply-first/);
});

// 只断言结构性事实（job 存在 + 用了 --must-apply-only + 有并发上限），
// 不锁死 cron 时间/分片数/limit 具体值——那些是运维可调参数，调参不该报红。
test("dead-link-audit has lightweight must-apply-only schedule", () => {
  const text = workflow("dead-link-audit.yml");

  assert.match(text, /must_apply_audit:/);
  assert.match(text, /--must-apply-only/);
  assert.match(text, /max-parallel:\s*\d+/);
});

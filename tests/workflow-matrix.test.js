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

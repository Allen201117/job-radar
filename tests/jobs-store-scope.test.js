const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const {
  appendJobScopeWhere,
  effectiveTargetRegions,
  jobMatchesRegion,
  jobMatchesScope,
  normalizeJobRegion,
} = loadTs(path.join(__dirname, "..", "lib", "job-scope.ts"));

test("job scope defaults to domestic and treats missing job_scope as domestic", () => {
  assert.equal(jobMatchesScope({ job_scope: "domestic" }, null), true);
  assert.equal(jobMatchesScope({ job_scope: null }, null), true);
  assert.equal(jobMatchesScope({ job_scope: "overseas", country_code: "US" }, null), false);
});

test("overseas scope filters by supported target regions", () => {
  const prefs = { job_scope: "overseas", target_regions: ["SG"] };

  assert.equal(jobMatchesScope({ job_scope: "overseas", country_code: "SG" }, prefs), true);
  assert.equal(jobMatchesScope({ job_scope: "overseas", country_code: "US" }, prefs), false);
  assert.equal(jobMatchesScope({ job_scope: "domestic", country_code: "CN" }, prefs), false);
});

test("overseas scope defaults to US, SG and Remote when target regions are empty", () => {
  assert.deepEqual(effectiveTargetRegions({ job_scope: "overseas", target_regions: [] }), ["US", "SG", "Remote"]);
  assert.equal(jobMatchesScope({ job_scope: "overseas", country_code: "US" }, { job_scope: "overseas" }), true);
});

test("all scope does not filter unless a region filter is selected", () => {
  const prefs = { job_scope: "all", target_regions: ["US"] };

  assert.equal(jobMatchesScope({ job_scope: "domestic", country_code: "CN" }, prefs), true);
  assert.equal(jobMatchesScope({ job_scope: "overseas", country_code: "SG" }, prefs), true);
  assert.equal(jobMatchesScope({ job_scope: "overseas", country_code: "SG" }, prefs, "US"), false);
});

test("region filter normalizes aliases and never accepts Taiwan", () => {
  assert.equal(normalizeJobRegion("us"), "US");
  assert.equal(normalizeJobRegion("新加坡"), "SG");
  assert.equal(normalizeJobRegion("remote"), "Remote");
  assert.equal(normalizeJobRegion("TW"), "");
  assert.equal(normalizeJobRegion("台湾"), "");
});

test("remote region matches global remote overseas jobs", () => {
  assert.equal(jobMatchesRegion({ job_scope: "overseas", country_code: null, location: "Remote" }, "Remote"), true);
  assert.equal(jobMatchesRegion({ job_scope: "overseas", country_code: "US", location: "Remote - US" }, "Remote"), false);
});

test("appendJobScopeWhere builds SQL conditions and params", () => {
  const conds = ["status = 'active'"];
  const params = [];
  appendJobScopeWhere(conds, params, { job_scope: "overseas", target_regions: ["US", "Remote"] }, {});

  assert.equal(conds[1], "job_scope = 'overseas'");
  assert.match(conds[2], /country_code = any\(\$1::text\[\]\)/);
  assert.deepEqual(params, [["US"]]);
});

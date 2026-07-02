const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const {
  parsePreferenceScopeInput,
  parsePreferencesInput,
} = loadOpp("preferences-input");

test("preference scope accepts domestic, overseas and all", () => {
  assert.equal(parsePreferenceScopeInput({ job_scope: "domestic" }).value.job_scope, "domestic");
  assert.equal(parsePreferenceScopeInput({ job_scope: "overseas" }).value.job_scope, "overseas");
  assert.equal(parsePreferenceScopeInput({ job_scope: "all" }).value.job_scope, "all");
});

test("invalid preference scope falls back to domestic", () => {
  const parsed = parsePreferenceScopeInput({ job_scope: "taiwan" });

  assert.equal(parsed.ok, true);
  assert.equal(parsed.value.job_scope, "domestic");
  assert.deepEqual(parsed.value.target_regions, []);
});

test("target regions are normalized to overseas whitelist and exclude Taiwan", () => {
  const parsed = parsePreferenceScopeInput({
    job_scope: "overseas",
    target_regions: ["us", "SG", "Remote", "TW", "Taiwan", " HK ", "US"],
  });

  assert.equal(parsed.ok, true);
  assert.deepEqual(parsed.value.target_regions, ["US", "SG", "Remote"]);
});

test("overseas or all scope defaults to all supported overseas target regions", () => {
  assert.deepEqual(parsePreferenceScopeInput({ job_scope: "overseas" }).value.target_regions, ["US", "SG", "Remote"]);
  assert.deepEqual(parsePreferenceScopeInput({ job_scope: "all" }).value.target_regions, ["US", "SG", "Remote"]);
});

test("preferences PUT parser includes scope fields", () => {
  const parsed = parsePreferencesInput({
    job_scope: "all",
    target_regions: ["sg", "remote"],
    target_roles: ["产品经理"],
  });

  assert.equal(parsed.ok, true);
  assert.equal(parsed.value.prefs.job_scope, "all");
  assert.deepEqual(parsed.value.prefs.target_regions, ["SG", "Remote"]);
});

const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const json = require("../lib/must-apply-list.json");
const overseasJson = require("../lib/must-apply-list-overseas.json");
const { INDUSTRY_CATEGORIES, canonicalizeUserIndustry } = require("../lib/company-industry.js");
const M = loadTs(path.join(__dirname, "..", "lib", "must-apply-list.ts"));

test("must-apply JSON follows the canonical industry taxonomy and preserves the north-star list", () => {
  assert.deepEqual(Object.keys(json), INDUSTRY_CATEGORIES);
  for (const [industry, companies] of Object.entries(json)) {
    assert.equal(companies.length, 30, `${industry} must have 30 companies`);
    assert.equal(new Set(companies.map((company) => company.name)).size, 30, `${industry} names must be unique`);
    assert.equal(new Set(companies.map((company) => company.pattern)).size, 30, `${industry} patterns must be unique`);
    for (const company of companies) {
      assert.equal(typeof company.name, "string");
      assert.ok(company.name.trim());
      assert.match(company.pattern, /^%[^%]+%$/);
    }
  }
  assert.equal(json["互联网/科技"][0].name, "字节跳动");
});

test("overseas must-apply JSON follows the domestic industry taxonomy and keeps each industry distinct", () => {
  assert.deepEqual(Object.keys(overseasJson), Object.keys(json));
  for (const [industry, companies] of Object.entries(overseasJson)) {
    assert.equal(companies.length, 30, `${industry} must have 30 overseas companies`);
    assert.equal(new Set(companies.map((company) => company.name)).size, 30, `${industry} names must be unique`);
    assert.equal(new Set(companies.map((company) => company.pattern)).size, 30, `${industry} patterns must be unique`);
    for (const company of companies) assert.match(company.pattern, /^%.+%$/);
  }
});

test("must-apply TypeScript API unions patterns, finds all industries, and resolves user industries", () => {
  assert.deepEqual(M.MUST_APPLY_INDUSTRIES, Object.keys(json));
  assert.deepEqual(M.MUST_APPLY_LIST, json["互联网/科技"]);
  const union = M.mustApplyUnion();
  assert.equal(new Set(union.map((company) => company.pattern)).size, union.length);
  assert.deepEqual(M.industriesForPattern("%蔚来%"), ["互联网/科技", "汽车/出行"]);
  assert.deepEqual(M.resolveMustApplyIndustries(["金融科技"]), [canonicalizeUserIndustry("金融科技")]);
  assert.deepEqual(M.resolveMustApplyIndustries([]), ["互联网/科技"]);
  assert.deepEqual(M.resolveMustApplyIndustries(null), ["互联网/科技"]);
  assert.deepEqual(M.resolveMustApplyIndustries(["不存在行业xyz"]), ["互联网/科技"]);
});

test("must-apply scope APIs select overseas data without changing domestic defaults", () => {
  assert.deepEqual(M.mustApplyByIndustry("domestic"), json);
  assert.deepEqual(M.mustApplyByIndustry("overseas"), overseasJson);
  assert.deepEqual(M.mustApplyUnion("overseas").slice(0, 2), overseasJson["互联网/科技"].slice(0, 2));
  assert.deepEqual(M.industriesForPattern("%Google%", "overseas"), ["互联网/科技"]);
  assert.deepEqual(M.industriesForPattern("%Google%"), []);
  assert.deepEqual(M.resolveMustApplyScopes("overseas"), ["overseas"]);
  assert.deepEqual(M.resolveMustApplyScopes("all"), ["domestic", "overseas"]);
  assert.deepEqual(M.resolveMustApplyScopes("domestic"), ["domestic"]);
  assert.deepEqual(M.resolveMustApplyScopes(null), ["domestic"]);
});

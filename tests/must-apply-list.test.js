const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const json = require("../lib/must-apply-list.json");
const overseasJson = require("../lib/must-apply-list-overseas.json");
const { INDUSTRY_CATEGORIES, canonicalizeUserIndustry } = require("../lib/company-industry.js");
const M = loadTs(path.join(__dirname, "..", "lib", "must-apply-list.ts"));
const R = loadTs(path.join(__dirname, "..", "lib", "ilike-matcher.ts"));

test("ilikeMatcher matches SQL ILIKE wildcards without changing literal matching", () => {
  assert.equal(R.ilikeMatcher("%字节%")("北京字节跳动有限公司"), true);
  assert.equal(R.ilikeMatcher("%BYTE%")("ByteDance"), true);
  assert.equal(R.ilikeMatcher("%字节%")("腾讯"), false);
  assert.equal(R.ilikeMatcher("%字节%")("ByteDance"), false);
  assert.equal(R.ilikeMatcher("甲_公司")("甲乙公司"), true);
  assert.equal(R.ilikeMatcher("甲%公司")("甲科技有限公司"), true);
  assert.equal(R.ilikeMatcher("甲%公司")("乙公司"), false);
});

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
    // 两种合法形态：%子串%（常规），或无通配的精确匹配（UPS/2U 这类短名：%UPS% 会误吞
    // Groups/Startups 等含子串的公司，ILIKE 无通配即等值匹配，专治「名字太短放宽必误伤」）。
    for (const company of companies) assert.match(company.pattern, /^(%[^%]+%|[^%]+)$/);
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

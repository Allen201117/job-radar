const test = require("node:test");
const assert = require("node:assert");

const { deriveCountryCode, deriveJobScope, locationInScope } = require("../lib/geo.js");

test("deriveCountryCode: greater china", () => {
  assert.equal(deriveCountryCode("Beijing, China"), "CN");
  assert.equal(deriveCountryCode("Business Analyst, Beijing"), "CN");
  assert.equal(deriveCountryCode("Focus Group, Shanghai"), "CN");
  assert.equal(deriveCountryCode("Hong Kong"), "HK");
});

test("deriveCountryCode: overseas", () => {
  assert.equal(deriveCountryCode("New York, NY"), "US");
  assert.equal(deriveCountryCode("Singapore"), "SG");
  for (const [location, expected] of [
    ["Remote - US", "US"],
    ["Remote, US", "US"],
    ["US - Remote", "US"],
    ["US Remote", "US"],
    ["Remote (USA)", "US"],
    ["Remote - United States", "US"],
    ["Remote, USA", "US"],
    ["Remote (US)", "US"],
    ["Remote (U.S.)", "US"],
    ["Remote - Singapore", "SG"],
    ["Remote, SG", "SG"],
    ["Singapore - Remote", "SG"],
    ["Remote (Singapore)", "SG"],
  ]) {
    assert.equal(deriveCountryCode(location), expected, location);
  }
});

test("deriveCountryCode: unknown", () => {
  assert.equal(deriveCountryCode("Remote"), null);
  assert.equal(deriveCountryCode("Belarus"), null);
  assert.equal(deriveCountryCode(""), null);
});

test("deriveJobScope: domestic vs overseas", () => {
  assert.equal(deriveJobScope("Beijing, China"), "domestic");
  assert.equal(deriveJobScope("Hong Kong"), "domestic");
  assert.equal(deriveJobScope("New York"), "overseas");
  assert.equal(deriveJobScope("Singapore"), "overseas");
  for (const location of ["Remote - US", "US Remote", "Remote (USA)", "Remote - Singapore"]) {
    assert.equal(deriveJobScope(location), "overseas", location);
  }
  assert.equal(deriveJobScope("Remote"), "domestic");
});

test("locationInScope: Taiwan is not in domestic or overseas launch scopes", () => {
  for (const loc of ["Taiwan", "Taipei, Taiwan", "台北, 台湾"]) {
    assert.equal(locationInScope(loc, ["CN"]), false, loc);
    assert.equal(locationInScope(loc, ["US", "SG", "Remote"]), false, loc);
    assert.equal(locationInScope(loc, ["CN", "US", "SG", "Remote"]), false, loc);
  }
});

// 外企 ATS 给的是小写 ISO 国别码 + 空格分词拼音城市；不认 "cn" 就判不出中国，
// 中国岗会在 locationInScope 处被当成非中国岗丢掉（大陆集团 29 个里丢了 8 个）。
// 串来自 SmartRecruiters 大陆集团中国岗（2026-09-05 live 原样抓取）。
// ⚠️ 必须与 crawler/geo.py 的 CHINA_LOCATION_MARKERS 逐条一致。
test("deriveCountryCode: ISO cn marks China without leaking into other places", () => {
  for (const location of [
    "He Fei Shi, An Hui Sheng, cn",
    "Ning Bo Shi, Zhe Jiang Sheng, cn",
    "Ji Ning Shi, Shan Dong Sheng, cn",
    "Yang Pu Qu, Shang Hai Shi, cn",
    "Zhangjiagang, cn",
  ]) {
    assert.equal(deriveCountryCode(location), "CN", location);
    assert.equal(locationInScope(location, ["CN", "US", "SG", "Remote"]), true, location);
  }
  assert.notEqual(deriveCountryCode("Cincinnati, OH"), "CN");
  assert.notEqual(deriveCountryCode("Chennai, TN, in"), "CN");
  assert.equal(deriveCountryCode("Hong Kong, cn"), "HK");
});

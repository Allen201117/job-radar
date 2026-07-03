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

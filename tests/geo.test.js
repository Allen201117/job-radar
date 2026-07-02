const test = require("node:test");
const assert = require("node:assert");

const { deriveCountryCode, deriveJobScope } = require("../lib/geo.js");

test("deriveCountryCode: greater china", () => {
  assert.equal(deriveCountryCode("Beijing, China"), "CN");
  assert.equal(deriveCountryCode("Hong Kong"), "HK");
});

test("deriveCountryCode: overseas", () => {
  assert.equal(deriveCountryCode("New York, NY"), "US");
  assert.equal(deriveCountryCode("Singapore"), "SG");
  assert.equal(deriveCountryCode("Remote - US"), "US");
});

test("deriveCountryCode: unknown", () => {
  assert.equal(deriveCountryCode("Remote"), null);
  assert.equal(deriveCountryCode(""), null);
});

test("deriveJobScope: domestic vs overseas", () => {
  assert.equal(deriveJobScope("Beijing, China"), "domestic");
  assert.equal(deriveJobScope("Hong Kong"), "domestic");
  assert.equal(deriveJobScope("New York"), "overseas");
  assert.equal(deriveJobScope("Singapore"), "overseas");
  assert.equal(deriveJobScope("Remote"), "domestic");
});

const test = require("node:test");
const assert = require("node:assert/strict");

const { classifyJobFunction } = require("../lib/china-keyword-expansion");

test("job function recognizes English edge titles", () => {
  assert.equal(classifyJobFunction({ title: "Staff Software Engineer" }), "研发");
  assert.equal(classifyJobFunction({ title: "Site Reliability Engineer" }), "研发");
  assert.equal(classifyJobFunction({ title: "SRE" }), "研发");
  assert.equal(classifyJobFunction({ title: "Technical Program Manager" }), "产品");
  assert.equal(classifyJobFunction({ title: "TPM" }), "产品");
});

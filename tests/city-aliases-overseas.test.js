const test = require("node:test");
const assert = require("node:assert/strict");

const { normalizeChinaCity } = require("../lib/china-keyword-expansion");

test("overseas city aliases normalize bidirectionally", () => {
  assert.equal(normalizeChinaCity("Singapore"), normalizeChinaCity("新加坡"));
  assert.equal(normalizeChinaCity("New York"), normalizeChinaCity("纽约"));
  assert.equal(normalizeChinaCity("NYC"), normalizeChinaCity("纽约"));
  assert.equal(normalizeChinaCity("San Francisco"), normalizeChinaCity("旧金山"));
  assert.equal(normalizeChinaCity("SF"), normalizeChinaCity("旧金山"));
  assert.equal(normalizeChinaCity("Seattle"), normalizeChinaCity("西雅图"));
  assert.equal(normalizeChinaCity("Mountain View"), normalizeChinaCity("山景城"));
  assert.equal(normalizeChinaCity("Sunnyvale"), normalizeChinaCity("桑尼维尔"));
  assert.equal(normalizeChinaCity("San Jose"), normalizeChinaCity("圣何塞"));
  assert.equal(normalizeChinaCity("Austin"), normalizeChinaCity("奥斯汀"));
  assert.equal(normalizeChinaCity("Boston"), normalizeChinaCity("波士顿"));
  assert.equal(normalizeChinaCity("London"), normalizeChinaCity("伦敦"));
});

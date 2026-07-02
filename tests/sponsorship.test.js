const test = require("node:test");
const assert = require("node:assert/strict");

const { sponsorshipSignal } = require("../lib/sponsorship.js");

test("sponsorship none", () => {
  assert.equal(sponsorshipSignal("We are unable to provide visa sponsorship"), "none");
  assert.equal(sponsorshipSignal("Must be authorized to work in the US without sponsorship"), "none");
  assert.equal(sponsorshipSignal("US citizens only; security clearance required"), "none");
  assert.equal(sponsorshipSignal("No sponsorship available for this position"), "none");
});

test("sponsorship available", () => {
  assert.equal(sponsorshipSignal("Visa sponsorship available"), "available");
  assert.equal(sponsorshipSignal("We will sponsor H-1B for qualified candidates"), "available");
  assert.equal(sponsorshipSignal("Relocation and visa support provided"), "available");
});

test("sponsorship unknown", () => {
  assert.equal(sponsorshipSignal("Great team, fast growth"), "unknown");
  assert.equal(sponsorshipSignal(""), "unknown");
  assert.equal(sponsorshipSignal(null), "unknown");
});

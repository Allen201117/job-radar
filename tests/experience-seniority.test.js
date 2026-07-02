const test = require("node:test");
const assert = require("node:assert/strict");

const { _minRequiredExperienceYears } = require("../lib/china-keyword-expansion");

test("seniority words provide experience fallback years", () => {
  assert.equal(_minRequiredExperienceYears("Entry Level Analyst"), 0);
  assert.equal(_minRequiredExperienceYears("Junior Software Engineer"), 0);
  assert.equal(_minRequiredExperienceYears("Mid-Level Data Analyst"), 3);
  assert.equal(_minRequiredExperienceYears("Senior Software Engineer"), 5);
  assert.equal(_minRequiredExperienceYears("Staff Engineer"), 8);
  assert.equal(_minRequiredExperienceYears("Lead Engineer"), 8);
  assert.equal(_minRequiredExperienceYears("Principal Engineer"), 12);
  assert.equal(_minRequiredExperienceYears("Distinguished Engineer"), 12);
});

test("explicit numeric years take priority over seniority words", () => {
  assert.equal(_minRequiredExperienceYears("Senior Software Engineer, 3+ years"), 3);
  assert.equal(_minRequiredExperienceYears("Principal Engineer, 5 years experience"), 5);
});

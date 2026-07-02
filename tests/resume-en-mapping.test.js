const assert = require("node:assert/strict");
const test = require("node:test");

const { mapResumeProfileToEnglishProfile } = require("../lib/resume-en-profile.js");

test("maps parsed English resume profile into en_* candidate fields", () => {
  const mapped = mapResumeProfileToEnglishProfile({
    target_roles: ["Machine Learning Engineer", "Machine Learning Engineer", " Backend Engineer "],
    skills: ["Python", "Distributed Systems", "Python", ""],
  });

  assert.deepEqual(mapped.en_target_roles, ["Machine Learning Engineer", "Backend Engineer"]);
  assert.deepEqual(mapped.en_skills, ["Python", "Distributed Systems"]);
  assert.deepEqual(mapped.en_target_keywords, ["Python", "Distributed Systems"]);
  assert.equal(mapped.has_en_resume, true);
});

test("maps empty English resume fields to empty arrays without inventing content", () => {
  const mapped = mapResumeProfileToEnglishProfile({});

  assert.deepEqual(mapped.en_target_roles, []);
  assert.deepEqual(mapped.en_skills, []);
  assert.deepEqual(mapped.en_target_keywords, []);
  assert.equal(mapped.has_en_resume, true);
});

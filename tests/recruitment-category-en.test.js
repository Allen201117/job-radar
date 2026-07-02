const test = require("node:test");
const assert = require("node:assert/strict");

const { recruitmentCategory, hasExplicitRecruitmentType } = require("../lib/china-keyword-expansion");

test("recruitment category recognizes strong English launch signals", () => {
  assert.equal(recruitmentCategory({ title: "Software Engineer Intern" }), "实习");
  assert.equal(recruitmentCategory({ title: "Summer 2026 Internship" }), "实习");
  assert.equal(recruitmentCategory({ title: "New Grad Software Engineer" }), "校招");
  assert.equal(recruitmentCategory({ title: "University Graduate - Engineering" }), "校招");
  assert.equal(recruitmentCategory({ title: "Entry Level Data Analyst" }), "校招");
  assert.equal(recruitmentCategory({ title: "Senior Software Engineer" }), "社招");
  assert.equal(recruitmentCategory({ title: "Staff Engineer" }), "社招");
});

test("English launch signals count as explicit recruitment type evidence", () => {
  assert.equal(hasExplicitRecruitmentType({ title: "University Graduate - Engineering" }), true);
  assert.equal(hasExplicitRecruitmentType({ title: "Entry Level Data Analyst" }), true);
  assert.equal(
    hasExplicitRecruitmentType({
      title: "Data Scientist",
      summary: "Graduate degree in CS or related field.",
    }),
    false,
  );
});

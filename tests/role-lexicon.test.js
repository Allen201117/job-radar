const assert = require("node:assert/strict");
const test = require("node:test");

const lex = require("../lib/role-lexicon-en.js");
const {
  expandChinaKeywordTerms,
  ftsCandidateTerms,
  jobMatchesChinaKeyword,
} = require("../lib/china-keyword-expansion");

test("role lexicon expands common Chinese roles to English equivalents", () => {
  assert.ok(lex.roles["算法"].includes("machine learning"));
  assert.ok(lex.roles["产品经理"].includes("product manager"));
  assert.ok(lex.skills["机器学习"].includes("ml"));
});

test("role lexicon is opt-in so domestic keyword expansion stays unchanged", () => {
  assert.equal(expandChinaKeywordTerms("后端").includes("server-side"), false);

  const terms = expandChinaKeywordTerms("后端", { includeOverseasLexicon: true });
  assert.ok(terms.includes("server-side"));
});

test("role lexicon terms feed FTS and keyword matching only when enabled", () => {
  assert.equal(ftsCandidateTerms("后端").includes("server-side"), false);
  assert.ok(ftsCandidateTerms("后端", { includeOverseasLexicon: true }).includes("server-side"));

  const serverSideJob = { title: "Server-side Engineer", summary: "" };
  assert.equal(jobMatchesChinaKeyword(serverSideJob, "后端"), false);
  assert.equal(
    jobMatchesChinaKeyword(serverSideJob, "后端", { includeOverseasLexicon: true }),
    true,
  );
});

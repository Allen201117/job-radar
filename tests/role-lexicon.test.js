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

// 2026-09-18：词表此前只覆盖互联网技术岗，实测 90 个真实用户 target_roles 里 56 个（62%）
// 一个都对不上。海外范围下方向词不经此表就只剩中文原词，而海外池 15.7 万个岗标题全是英文
// → tsquery `((行政))` 召回恒为 0。下面钉住「非互联网方向也必须有英文对应」这条，
// 免得后来人按「这些词看着不像技术岗」把它们当噪音删掉。
test("lexicon covers non-tech directions real users actually type", () => {
  const cases = [
    ["行政", "administrative"],
    ["文员", "clerk"],
    ["人事", "human resources"],
    ["客服", "customer service"],
    ["采购", "procurement"],
    ["临床", "clinical"],
    ["实验", "laboratory"],
    ["机械", "mechanical engineer"],
    ["质量", "quality engineer"],
    ["外贸", "foreign trade"],
    ["电商", "e-commerce"],
    ["美工", "graphic designer"],
    ["教育", "education"],
    ["造价", "cost estimator"],
  ];
  for (const [cn, en] of cases) {
    assert.ok(lex.roles[cn], `词表缺少方向「${cn}」`);
    assert.ok(lex.roles[cn].includes(en), `方向「${cn}」应扩展出 ${en}`);
    const terms = expandChinaKeywordTerms(cn, { includeOverseasLexicon: true });
    assert.ok(terms.includes(en), `海外扩展没吐出 ${en}（${cn}）`);
  }
});

// 包含匹配：一条「行政」要同时管住「行政专员」「行政/后勤类」这些真实写法，
// 否则每来一种新写法就得补一条，词表迟早失控。
test("lexicon matches by containment so role variants reuse one entry", () => {
  for (const variant of ["行政专员", "行政专员/助理", "行政/后勤类"]) {
    assert.ok(
      expandChinaKeywordTerms(variant, { includeOverseasLexicon: true }).includes("administrative"),
      `「${variant}」应命中「行政」组`,
    );
  }
});

// 刻意不收的泛词：加了会把大片无关岗召回来（"agent" 在英文岗里多是保险/地产经纪），
// 精度损失远大于召回收益。这条是负向断言，防止后来人「顺手补全」。
test("lexicon deliberately omits over-broad terms", () => {
  for (const banned of ["产品", "技术", "管理", "agent"]) {
    assert.equal(Boolean(lex.roles[banned]), false, `「${banned}」太泛，不该进词表`);
  }
});

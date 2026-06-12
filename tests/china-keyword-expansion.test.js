const assert = require("node:assert/strict");
const test = require("node:test");

const {
  expandChinaKeywordTerms,
  ftsCandidateTerms,
  normalizeChinaCity,
  normalizeChinaJobFields,
  normalizeChinaJobType,
  jobMatchesChinaKeyword,
} = require("../lib/china-keyword-expansion");

test("expands Chinese algorithm keywords to English terms", () => {
  const terms = expandChinaKeywordTerms("算法 实习 北京");

  assert.ok(terms.includes("算法"));
  assert.ok(terms.includes("机器学习"));
  assert.ok(terms.includes("machine learning"));
  assert.ok(terms.includes("algorithm"));
  assert.ok(terms.includes("intern"));
});

test("expands English analyst keywords to Chinese terms", () => {
  const terms = expandChinaKeywordTerms("data analyst intern");

  assert.ok(terms.includes("数据分析"));
  assert.ok(terms.includes("商业分析"));
  assert.ok(terms.includes("data analyst"));
  assert.ok(terms.includes("实习"));
});

test("matches English jobs from Chinese user keywords and Chinese jobs from English keywords", () => {
  assert.equal(
    jobMatchesChinaKeyword(
      { title: "Machine Learning Intern", summary: "Build ranking models" },
      "算法",
    ),
    true,
  );

  assert.equal(
    jobMatchesChinaKeyword(
      { title: "商业分析实习生", summary: "SQL 数据分析" },
      "business analyst",
    ),
    true,
  );
});

test("normalizes common China city aliases", () => {
  assert.equal(normalizeChinaCity("北京市"), "北京");
  assert.equal(normalizeChinaCity("Shanghai"), "上海");
  assert.equal(normalizeChinaCity("Hong Kong"), "香港");
  assert.equal(normalizeChinaCity("全国多地"), "全国");
});

test("normalizes China job types from title, source type, URL and summary", () => {
  assert.equal(
    normalizeChinaJobType({ title: "2026校园招聘-算法工程师" }),
    "校招",
  );
  assert.equal(
    normalizeChinaJobType({ title: "暑期实习-数据分析", url: "/campus/intern" }),
    "暑期实习",
  );
  assert.equal(
    normalizeChinaJobType({ title: "管理培训生", summary: "graduate program" }),
    "管培生",
  );
  assert.equal(
    normalizeChinaJobType({ title: "投研研究员", summary: "行业研究" }),
    "研究岗",
  );
});

test("normalizes job fields without dropping original official URLs", () => {
  const job = normalizeChinaJobFields({
    title: "Data Analyst Intern",
    location: "Shanghai",
    summary: "SQL analytics internship",
    jd_url: "https://talent.baidu.com/jobs/detail/INTERN/abc",
  });

  assert.equal(job.location, "上海");
  assert.equal(job.job_type, "实习");
  assert.equal(job.jd_url, "https://talent.baidu.com/jobs/detail/INTERN/abc");
});

test("bilingual: Chinese keyword matches English foreign-company jobs", () => {
  assert.ok(jobMatchesChinaKeyword({ title: "Machine Learning Engineer", location: "Beijing" }, "人工智能"));
  assert.ok(jobMatchesChinaKeyword({ title: "Senior Product Manager" }, "pm"));
  assert.ok(jobMatchesChinaKeyword({ title: "Frontend Engineer" }, "前端"));
  assert.ok(jobMatchesChinaKeyword({ title: "Backend Developer (Golang)" }, "后端"));
  assert.ok(jobMatchesChinaKeyword({ title: "Data Scientist" }, "数据分析"));
});

test("short latin codes use word boundaries (no false positives)", () => {
  // 'ai' should not match inside 'Maintenance'; 'go' not inside 'Google'
  assert.equal(jobMatchesChinaKeyword({ title: "Maintenance Technician" }, "ai"), false);
  assert.equal(jobMatchesChinaKeyword({ title: "Google Product role" }, "go"), false);
  // but real standalone codes still match
  assert.ok(jobMatchesChinaKeyword({ title: "AI Engineer" }, "ai"));
});

test("ftsCandidateTerms: 命中组的跨语言同义词，全部 >=2 字，不并入同职能兄弟组（供 FTS 收窄预筛）", () => {
  const pm = ftsCandidateTerms("产品");
  assert.ok(pm.includes("产品"));
  assert.ok(pm.includes("产品经理"));
  assert.ok(pm.includes("product manager") || pm.includes("product")); // 跨语言：命中英文标题
  assert.ok(pm.every((t) => t.length >= 2)); // 1 字过滤掉
  // 「前端」只取前端组(含跨语言 react/frontend)，**不**拉同职能(研发)的后端/算法等兄弟组 → 候选紧、搜索快且精准
  const fe = ftsCandidateTerms("前端");
  assert.ok(fe.includes("前端"));
  assert.ok(fe.some((t) => ["frontend", "react", "vue", "front end"].includes(t)));
  assert.ok(!fe.includes("后端") && !fe.includes("算法"));
  assert.deepEqual(ftsCandidateTerms(""), []);
});

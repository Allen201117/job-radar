const assert = require("node:assert/strict");
const test = require("node:test");

const {
  expandChinaKeywordTerms,
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

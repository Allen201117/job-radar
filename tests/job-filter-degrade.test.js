const test = require("node:test");
const assert = require("node:assert/strict");
const {
  hasExplicitRecruitmentType,
  recruitmentCategory,
} = require("../lib/china-keyword-expansion");

// 支撑 job-filter「类型」从硬 AND 改为「信息缺失放行」的判断：
// 岗位有明确招聘类型信号才参与类型过滤；无信号(实测库里 job_type ~94% 空)不应被兜底社招误杀。

test("有明确类型信号 → true", () => {
  assert.equal(hasExplicitRecruitmentType({ title: "2024 校招 后端工程师" }), true);
  assert.equal(hasExplicitRecruitmentType({ title: "暑期实习生" }), true);
  assert.equal(hasExplicitRecruitmentType({ title: "数据分析", job_type: "社招" }), true);
  assert.equal(hasExplicitRecruitmentType({ title: "Java 工程师", job_type: "全职" }), true);
});

test("无类型信号 → false（标题看不出、job_type 空）", () => {
  assert.equal(hasExplicitRecruitmentType({ title: "高级软件工程师" }), false);
  assert.equal(hasExplicitRecruitmentType({ title: "产品经理", summary: "负责需求管理" }), false);
  assert.equal(hasExplicitRecruitmentType({}), false);
  assert.equal(hasExplicitRecruitmentType({ title: "", job_type: null }), false);
});

test("根因复现：无信号岗 recruitmentCategory 兜底「社招」，故必须靠 hasExplicit 区分真假社招", () => {
  const job = { title: "高级软件工程师" };
  assert.equal(recruitmentCategory(job), "社招"); // 兜底，并非真信号
  assert.equal(hasExplicitRecruitmentType(job), false); // 实为「类型未知」→ 不该被「校招」筛误杀
});

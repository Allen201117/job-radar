const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");
// 一次性 loadTs 加载 campus-zone.ts；后续任务只需在本行解构补上新函数名。
const { campusAdmission, windowStatus, compareCampusJobs, compareCompanyCards, groupCampusJobs } =
  loadTs(path.join(__dirname, "..", "lib", "campus-zone.ts"));

test("campusAdmission: 强校招信号 → campus", () => {
  assert.equal(campusAdmission({ title: "2027届校园招聘-后端工程师", job_type: "校招" }), "campus");
  assert.equal(campusAdmission({ title: "管培生", jd_url: "https://x.com/campus/1" }), "campus");
});

test("campusAdmission: 实习单独成桶，不混校招", () => {
  assert.equal(campusAdmission({ title: "暑期实习-数据分析", job_type: "实习" }), "intern");
});

test("campusAdmission: 社招/弱词/无信号 → reject（精度优先，宁漏勿误）", () => {
  assert.equal(campusAdmission({ title: "高级后端工程师", job_type: "社招" }), "reject");
  assert.equal(campusAdmission({ title: "后端工程师（毕业生优先）" }), "reject"); // 弱词不判校招
  assert.equal(campusAdmission({ title: "资深架构师", summary: "8年经验", job_type: "校招" }), "reject"); // ≥2年经验强制社招
});

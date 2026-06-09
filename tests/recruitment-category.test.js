const test = require("node:test");
const assert = require("node:assert");
const { recruitmentCategory } = require("../lib/china-keyword-expansion");

test("recruitmentCategory 三桶穷尽分类（实习 / 校招 / 社招）", () => {
  // 实习
  assert.equal(recruitmentCategory({ job_type: "暑期实习" }), "实习");
  assert.equal(recruitmentCategory({ job_type: "日常实习" }), "实习");
  assert.equal(recruitmentCategory({ title: "数据分析实习生" }), "实习");

  // 校招（含管培生 / 留学生专项 / 应届，过去会漏桶）
  assert.equal(recruitmentCategory({ job_type: "校招" }), "校招");
  assert.equal(recruitmentCategory({ job_type: "管培生" }), "校招");
  assert.equal(recruitmentCategory({ job_type: "留学生专项" }), "校招");
  assert.equal(recruitmentCategory({ title: "2025届校园招聘 算法工程师" }), "校招");
  assert.equal(recruitmentCategory({ title: "应届生 后端开发" }), "校招");

  // 社招（含研究岗 / 全职 / 无信号，过去会漏桶）
  assert.equal(recruitmentCategory({ job_type: "研究岗" }), "社招");
  assert.equal(recruitmentCategory({ job_type: "全职", title: "高级工程师" }), "社招");
  assert.equal(recruitmentCategory({ job_type: "社招" }), "社招");
  assert.equal(recruitmentCategory({ title: "产品经理（5年经验）" }), "社招");
  assert.equal(recruitmentCategory({}), "社招");
});

test("recruitmentCategory 实习优先于校园字样", () => {
  assert.equal(recruitmentCategory({ title: "2025 暑期实习 · 校园招聘" }), "实习");
});

test("P1-D: url 拼音路径 + 源名信号补全校招/实习（治 59% 空 job_type 误堆社招）", () => {
  // jd_url 拼音路径（/shixi /xiaozhao），标题本身无招聘类型字样
  assert.equal(recruitmentCategory({ title: "研发工程师", jd_url: "https://x.com/zp/shixi/123" }), "实习");
  assert.equal(recruitmentCategory({ title: "电气工程师", jd_url: "https://x.com/zp/xiaozhao/9" }), "校招");
  // jd_url 英文路径（已支持，回归确认）
  assert.equal(recruitmentCategory({ title: "软件工程师", jd_url: "https://x.com/campus/job/1" }), "校招");
  // 源/公司名显式标注（如库里的"华润电力 CR Power 校招"）
  assert.equal(recruitmentCategory({ title: "电气工程师", company: "华润电力 CR Power 校招" }), "校招");
  // 回归：普通公司/岗位不被误判
  assert.equal(recruitmentCategory({ title: "后端开发", company: "字节跳动" }), "社招");
});

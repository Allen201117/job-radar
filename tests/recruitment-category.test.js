const test = require("node:test");
const assert = require("node:assert");
const {
  recruitmentCategory,
  hasExplicitRecruitmentType,
} = require("../lib/china-keyword-expansion");

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

test("英文 intern/graduate 词边界：internal/international/internet/undergraduate 不误判（治全职岗被标实习/校招）", () => {
  // 本次线上真因：Intel 全职高级工程师 JD 含 "internal" 被标实习
  assert.equal(
    recruitmentCategory({ title: "Senior Gen AI Software Solutions Engineer", summary: "Works with internal engineering teams and external partners to deliver AI." }),
    "社招",
  );
  assert.equal(recruitmentCategory({ title: "Business Manager", summary: "Lead international expansion." }), "社招");
  assert.equal(recruitmentCategory({ title: "Backend Engineer", summary: "Build internet-scale services." }), "社招");
  assert.equal(recruitmentCategory({ title: "Software Engineer", summary: "Undergraduate degree required, 5 yrs experience." }), "社招");
  // 真·实习/校招仍判得出（不过度修正）
  assert.equal(recruitmentCategory({ title: "Software Engineering Intern" }), "实习");
  assert.equal(recruitmentCategory({ title: "Summer Internship Program 2026" }), "实习");
  assert.equal(recruitmentCategory({ title: "Research Interns wanted" }), "实习");
  assert.equal(recruitmentCategory({ title: "Software Engineer", summary: "Open to new grads and recent graduates." }), "校招");
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

test("硬门：明确要求 ≥2 年经验 → 强制社招（治『社招要3年经验却被标校招』）", () => {
  // ① summary/JD 正文里的『毕业生/应届/graduate』字样污染 → 被经验门纠正回社招
  assert.equal(
    recruitmentCategory({
      title: "高级算法工程师",
      summary: "3年以上相关工作经验，985/211高校毕业生优先，硕士学历。",
    }),
    "社招",
  );
  assert.equal(
    recruitmentCategory({
      title: "智慧校园解决方案专家",
      summary: "本科及以上学历，5年以上教育行业、智慧校园 ToB/ToG 工作经验。",
    }),
    "社招",
  );
  assert.equal(
    recruitmentCategory({
      title: "Software Engineer",
      summary: "Graduate degree preferred. 5+ years of experience building services.",
    }),
    "社招",
  );
  // ② 源 job_type 本身把资深岗错标成校招 → 被经验门纠正回社招
  assert.equal(
    recruitmentCategory({
      title: "光刻工艺资深/主任工程师",
      job_type: "校招",
      summary: "负责光刻工艺研发，8年以上半导体制造经验。",
    }),
    "社招",
  );
  // 数字范围写法（3-5年）下限 ≥2 也纠正
  assert.equal(
    recruitmentCategory({ title: "产品经理", summary: "3-5年经验，应届生亦可培养。" }),
    "社招",
  );
});

test("硬门不过度修正：真实校招/实习 + 无 ≥2 年经验硬要求 → 保持原判", () => {
  // 真校招（应届、无年限要求）保持校招
  assert.equal(
    recruitmentCategory({ title: "2025届校园招聘 算法工程师", summary: "面向应届毕业生。" }),
    "校招",
  );
  // “毕业2年内 / 0-2年 / 1-3年” 下限 <2，不触发硬门（不把校招误纠成社招）
  assert.equal(
    recruitmentCategory({ title: "管培生", summary: "面向毕业2年内的应届及往届生。" }),
    "校招",
  );
  assert.equal(
    recruitmentCategory({ title: "校园招聘 后端", summary: "0-2年经验，欢迎应届。" }),
    "校招",
  );
  // 真实习保持实习（哪怕正文提到团队多年经验）
  assert.equal(
    recruitmentCategory({ title: "算法实习生", summary: "在校生，随团队3年+资深工程师学习。" }),
    "实习",
  );
});

test("hasExplicitRecruitmentType：≥2 年经验硬要求算『明确类型』（让校招筛选能真正踢掉它）", () => {
  // 空 job_type + 正文含毕业生字样，但要 3 年经验 → 视为明确（社招），筛校招时应被淘汰
  assert.equal(
    hasExplicitRecruitmentType({ title: "数据工程师", summary: "3年以上经验，重点院校毕业生优先。" }),
    true,
  );
  // 纯信息不足（无类型、无年限）仍是『类型未知』→ 筛选时放行降级，不误杀
  assert.equal(hasExplicitRecruitmentType({ title: "后端开发工程师" }), false);
});

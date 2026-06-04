const test = require("node:test");
const assert = require("node:assert");
const { maskContact, normalizeResumeProfile } = require("../lib/resume-extract");
const { parseJsonLoose } = require("../lib/llm");

test("maskContact 脱敏邮箱与手机号", () => {
  assert.equal(maskContact("zhangsan@gmail.com"), "z***@gmail.com");
  assert.equal(maskContact("13812345678"), "138****5678");
  const both = maskContact("联系：zhangsan@gmail.com / 13812345678");
  assert.match(both, /z\*\*\*@gmail\.com/);
  assert.match(both, /138\*\*\*\*5678/);
  assert.equal(maskContact(""), "");
});

test("normalizeResumeProfile 归一化、裁剪、脱敏", () => {
  const out = normalizeResumeProfile({
    headline: "  数据分析实习生  ",
    basic_info: { name: "张三", city: "上海", contact: "zhangsan@gmail.com 13812345678" },
    target_roles: ["数据分析", "数据分析", "BI"],
    skills: Array.from({ length: 50 }, (_, i) => "skill" + i),
    experience_stage: "实习",
    education: [
      { school: "复旦大学", degree: "本科", major: "统计学", start: "2019.09", end: "2023.06" },
      { irrelevant: 1 },
    ],
    internships: [{ company: "字节跳动", role: "数据分析实习", summary: "搭建增长报表" }],
    projects: [{ name: "用户增长分析", outcome: "转化提升 10%" }, {}],
  });

  assert.equal(out.headline, "数据分析实习生");
  assert.equal(out.basic_info.name, "张三");
  assert.match(out.basic_info.contact, /z\*\*\*@gmail\.com/);
  assert.match(out.basic_info.contact, /138\*\*\*\*5678/);
  assert.deepEqual(out.target_roles, ["数据分析", "BI"]); // 去重
  assert.equal(out.skills.length, 30); // 裁剪到 MAX_SKILLS
  assert.equal(out.experience_stage, "实习");
  assert.equal(out.seniority, "实习");
  assert.equal(out.education.length, 1); // 空对象被丢弃
  assert.equal(out.education[0].school, "复旦大学");
  assert.equal(out.internships.length, 1);
  assert.equal(out.projects.length, 1); // 空对象被丢弃
  assert.equal(out.projects[0].name, "用户增长分析");
});

test("normalizeResumeProfile 拒绝非法阶段与脏输入", () => {
  assert.equal(normalizeResumeProfile({ experience_stage: "高级" }).experience_stage, "");
  const empty = normalizeResumeProfile(null);
  assert.equal(empty.headline, "");
  assert.deepEqual(empty.skills, []);
  assert.deepEqual(empty.education, []);
  assert.equal(empty.basic_info.contact, "");
});

test("parseJsonLoose 解析裸 JSON 与夹带 JSON，脏数据抛错", () => {
  assert.deepEqual(parseJsonLoose('{"a":1}'), { a: 1 });
  assert.deepEqual(parseJsonLoose('解析结果：{"a":2} 多余文字'), { a: 2 });
  assert.throws(() => parseJsonLoose("完全不是 json"), /llm_bad_json/);
});

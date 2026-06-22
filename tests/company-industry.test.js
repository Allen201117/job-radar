const test = require("node:test");
const assert = require("node:assert/strict");
const {
  classifyCompanyIndustry,
  canonicalizeUserIndustry,
  userTargetIndustryCategories,
  jobIndustryAllowed,
} = require("../lib/company-industry");

// 「行业-公司-岗位」三层认知的地基：公司→行业派生 + 跨行业门。
// 治「同职能跨行业误命中」（互联网产品经理 ✗ 生物医药产品经理 / 消费制造产品经理）。

test("大厂名映射：名字不带行业词的品牌也能判对", () => {
  assert.equal(classifyCompanyIndustry("农夫山泉 养生堂"), "消费/零售"); // 用户实锤公司
  assert.equal(classifyCompanyIndustry("字节跳动"), "互联网/科技");
  assert.equal(classifyCompanyIndustry("比亚迪"), "汽车/出行");
  assert.equal(classifyCompanyIndustry("宁德时代"), "能源/化工");
  assert.equal(classifyCompanyIndustry("顺丰速运"), "物流/供应链");
});

test("关键词规则：名字含行业词的公司", () => {
  assert.equal(classifyCompanyIndustry("某某制药股份"), "医疗/医药");
  assert.equal(classifyCompanyIndustry("某某证券"), "金融");
  assert.equal(classifyCompanyIndustry("某某新能源汽车"), "汽车/出行"); // 汽车优先于能源/制造
  assert.equal(classifyCompanyIndustry("某某半导体"), "制造/工业");
  assert.equal(classifyCompanyIndustry("某某网络科技"), "互联网/科技");
  assert.equal(classifyCompanyIndustry("某某食品饮料"), "消费/零售");
});

test("判不出 → null（缺数据放行，不误杀）", () => {
  assert.equal(classifyCompanyIndustry("某某集团"), null);
  assert.equal(classifyCompanyIndustry(""), null);
  assert.equal(classifyCompanyIndustry(null), null);
});

test("用户自填行业归一到规范类目", () => {
  assert.equal(canonicalizeUserIndustry("互联网"), "互联网/科技");
  assert.equal(canonicalizeUserIndustry("快消"), "消费/零售");
  assert.equal(canonicalizeUserIndustry("生物医药"), "医疗/医药");
  assert.equal(canonicalizeUserIndustry("互联网/科技"), "互联网/科技"); // 已规范
  assert.equal(canonicalizeUserIndustry("玄学"), null);

  const set = userTargetIndustryCategories(["互联网", "金融", "玄学"]);
  assert.deepEqual([...set].sort(), ["互联网/科技", "金融"]);
});

test("跨行业门：用户实锤场景（互联网用户 ✗ 消费/医药 同职能岗）", () => {
  // 用户目标行业=互联网/科技 → 农夫山泉(消费)、某药企(医药) 同是产品经理也应被拦。
  const userInds = ["互联网"];
  assert.equal(jobIndustryAllowed("农夫山泉 养生堂", userInds), false, "消费岗对互联网用户应拦截");
  assert.equal(jobIndustryAllowed("某某生物制药", userInds), false, "医药岗对互联网用户应拦截");
  assert.equal(jobIndustryAllowed("字节跳动", userInds), true, "互联网岗放行");
});

test("跨行业门保守放行：用户没填行业 / 岗位行业判不出", () => {
  assert.equal(jobIndustryAllowed("农夫山泉", []), true, "用户没填行业 → 不设门");
  assert.equal(jobIndustryAllowed("农夫山泉", ["玄学"]), true, "用户行业无法识别 → 不设门");
  assert.equal(jobIndustryAllowed("某某集团", ["互联网"]), true, "岗位行业判不出 → 放行不误杀");
});

test("多目标行业：命中其一即放行", () => {
  const userInds = ["互联网", "汽车"];
  assert.equal(jobIndustryAllowed("比亚迪", userInds), true);
  assert.equal(jobIndustryAllowed("字节跳动", userInds), true);
  assert.equal(jobIndustryAllowed("农夫山泉", userInds), false);
});

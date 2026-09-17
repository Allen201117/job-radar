// 画像卫生：归一 + 体检 + 提示的契约。
// 用例全部取自 2026-09-17 线上 64 份真实画像里实际出现的写法（见 scripts/profile-hygiene/audit.mjs），
// 不是编的——编的写法修好了也不代表线上那批脏值被收拾了。
const { test } = require("node:test");
const assert = require("node:assert");

const { normalizeRolePhrases } = require("../lib/china-keyword-expansion.js");
const {
  auditProfile,
  canonicalizeIndustryList,
  cityRecognition,
  normalizeCityPhrases,
  profileHygieneHints,
  HYGIENE_HINTS,
} = require("../lib/profile-hygiene.js");
const { normalizeResumeProfile, buildResumeMessages } = require("../lib/resume-extract.js");

test("normalizeRolePhrases：线上真实脏写法逐条收拾", () => {
  // 分隔符不止斜杠
  assert.deepEqual(normalizeRolePhrases(["销售；采购"]), ["销售", "采购"]);
  assert.deepEqual(normalizeRolePhrases(["文体/影视/写作/媒体类"]), ["文体", "影视", "写作", "媒体"]);
  // 纯中文时空格也是「或」
  assert.deepEqual(normalizeRolePhrases(["测试 后端"]), ["测试", "后端"]);
  assert.deepEqual(normalizeRolePhrases(["销售 管培 运营"]), ["销售", "管培", "运营"]);
  assert.deepEqual(normalizeRolePhrases(["质量工程师 工艺工程师"]), ["质量工程师", "工艺工程师"]);
  // 含拉丁字母时空格是词内空格，**绝不能拆**
  assert.deepEqual(normalizeRolePhrases(["AI 产品经理"]), ["AI 产品经理"]);
  assert.deepEqual(normalizeRolePhrases(["AI 数据产品经理"]), ["AI 数据产品经理"]);
  assert.deepEqual(normalizeRolePhrases(["commercial specialist"]), ["commercial specialist"]);
  // 加号（只在含中文时拆）
  assert.deepEqual(normalizeRolePhrases(["ai算法+雷达"]), ["ai算法", "雷达"]);
  // 后缀要反复剥
  assert.deepEqual(normalizeRolePhrases(["行政/后勤类"]), ["行政", "后勤"]);
  assert.deepEqual(normalizeRolePhrases(["经营管理类"]), ["经营管理"]);
  assert.deepEqual(normalizeRolePhrases(["化学分析岗"]), ["化学分析"]);
  assert.deepEqual(normalizeRolePhrases(["机械设计实习生"]), ["机械设计"]);
  assert.deepEqual(normalizeRolePhrases(["AIGC 内容实习生"]), ["AIGC 内容"]);
  // 括号是修饰不是岗位名
  assert.deepEqual(normalizeRolePhrases(["机械工程师助理（设计方向）"]), ["机械工程师助理"]);
  // 旧契约不许回归
  assert.deepEqual(normalizeRolePhrases(["项目专员/助理"]), ["项目专员", "助理"]);
  assert.deepEqual(normalizeRolePhrases(["英文相关", "技术岗位"]), ["英文", "技术"]);
  assert.deepEqual(normalizeRolePhrases(["办公室文员", "仓库文员"]), ["文员", "仓库文员"]);
  assert.deepEqual(normalizeRolePhrases(["产品经理"]), ["产品经理"]);
  // 剥空了保留原样，绝不丢用户的值
  assert.deepEqual(normalizeRolePhrases(["岗位", "  ", "实习"]), ["岗位", "实习"]);
});

test("normalizeCityPhrases：拆多值 + 归规范名，认不出的原样保留", () => {
  assert.deepEqual(normalizeCityPhrases(["杭州 深圳 无锡 宁波"]), ["杭州", "深圳", "无锡", "宁波"]);
  assert.deepEqual(normalizeCityPhrases(["浙江 江苏 广东"]), ["浙江", "江苏", "广东"]);
  assert.deepEqual(normalizeCityPhrases(["北京市"]), ["北京"]);
  assert.deepEqual(normalizeCityPhrases(["上海", "上海市"]), ["上海"]);
  // 含拉丁字母不按空格拆（否则 "new york" 会碎成两个词，别名表也就认不出它了）
  assert.deepEqual(normalizeCityPhrases(["new york"]), ["纽约"]);
  assert.deepEqual(normalizeCityPhrases(["San Francisco"]), ["旧金山"]);
  // 别名表里没有的真实地级市：原样保留，不丢
  assert.deepEqual(normalizeCityPhrases(["连云港"]), ["连云港"]);
  assert.deepEqual(normalizeCityPhrases(["马来西亚"]), ["马来西亚"]);
});

test("cityRecognition：城市 / 省·城市群 / 未登记 三档", () => {
  assert.equal(cityRecognition("北京"), "city");
  assert.equal(cityRecognition("广东"), "region");
  assert.equal(cityRecognition("长三角"), "region");
  // 原本用「连云港」当未登记样本，2026-09-17 它连同另外 16 个用户真填过的地级市一起进了
  // CITY_ALIASES（见 lib/china-keyword-expansion.js），已升格为 "city"。换一个仍未登记的样本，
  // 保住这一档本身的断言——「未登记」这个返回值还在用（auditProfile 靠它报 location_unregistered_city）。
  assert.equal(cityRecognition("连云港"), "city");
  assert.equal(cityRecognition("石家庄"), "unknown");
});

test("canonicalizeIndustryList：认识的归一，认不出的原样保留（不丢）", () => {
  assert.deepEqual(canonicalizeIndustryList(["互联网"]), ["互联网/科技"]);
  assert.deepEqual(canonicalizeIndustryList(["制造业"]), ["制造/工业"]);
  assert.deepEqual(canonicalizeIndustryList(["互联网", "互联网/科技"]), ["互联网/科技"]);
  // 「前台」根本不是行业：不认识但不能删，否则用户看不到自己填过什么
  assert.deepEqual(canonicalizeIndustryList(["前台"]), ["前台"]);
  // 权威类目自己就带斜杠，不许被当成「一格多填」劈开
  assert.deepEqual(canonicalizeIndustryList(["制造/工业"]), ["制造/工业"]);
  assert.deepEqual(canonicalizeIndustryList(["消费/零售"]), ["消费/零售"]);
  // 一格多填必须两个都留下：canonicalizeUserIndustry 是子串正则，整条去问会吞掉后半截
  assert.deepEqual(canonicalizeIndustryList(["互联网、金融"]), ["互联网/科技", "金融"]);
  assert.deepEqual(canonicalizeIndustryList(["未知甲、未知乙"]), ["未知甲", "未知乙"]);
});

test("auditProfile：海外范围三条件同时成立才报 scope_overseas_mismatch", () => {
  const base = { target_roles: ["行政"], target_locations: ["深圳"], job_scope: "overseas", has_en_resume: false };
  assert.ok(auditProfile({ preferences: base }).issues.includes("scope_overseas_mismatch"));
  // 有英文简历 → 不报
  assert.ok(
    !auditProfile({ preferences: { ...base, has_en_resume: true } }).issues.includes("scope_overseas_mismatch"),
  );
  // 国内范围 → 不报
  assert.ok(
    !auditProfile({ preferences: { ...base, job_scope: "domestic" } }).issues.includes("scope_overseas_mismatch"),
  );
  // 有一个系统认不出的城市（可能是海外城市）→ 不报，宁可漏判不可错杀
  assert.ok(
    !auditProfile({ preferences: { ...base, target_locations: ["深圳", "Berlin"] } }).issues.includes(
      "scope_overseas_mismatch",
    ),
  );
  // 简历档案上的英文简历标记同样算数
  assert.ok(
    !auditProfile({ preferences: base, candidate: { has_en_resume: true } }).issues.includes(
      "scope_overseas_mismatch",
    ),
  );
});

test("auditProfile：脏写法 / 行业不生效 / 证书词 各自报对码", () => {
  const { issues, details } = auditProfile({
    preferences: {
      target_roles: ["项目专员/助理", "产品经理"],
      target_locations: ["杭州 深圳"],
      target_industries: ["前台", "互联网"],
      target_keywords: ["CET-6", "增长产品"],
      experience_stage: "校招",
    },
  });
  assert.ok(issues.includes("role_dirty_phrase"));
  assert.ok(issues.includes("location_multi_value"));
  assert.ok(issues.includes("industry_unrecognized"));
  assert.ok(issues.includes("keyword_certificate"));
  assert.deepEqual(details.industries.unrecognized, ["前台"]);
  assert.deepEqual(details.roles.dirty, ["项目专员/助理"]);
});

test("auditProfile：干净画像零 issue（避免提示对所有人常亮）", () => {
  const { issues } = auditProfile({
    preferences: {
      target_roles: ["产品经理"],
      target_locations: ["上海"],
      target_industries: ["互联网/科技"],
      target_keywords: ["增长产品"],
      experience_stage: "社招",
      job_scope: "domestic",
    },
  });
  assert.deepEqual(issues, []);
});

test("profileHygieneHints：只给「能证明确实有问题」的码配提示", () => {
  // 职能认不出 / 城市没登记是我们自己的词表缺口，故意不弹提示
  for (const code of ["role_all_unclassified", "role_partly_unclassified", "location_unregistered_city", "role_empty", "location_empty"]) {
    assert.equal(HYGIENE_HINTS[code], undefined, `${code} 不该有用户可见提示`);
  }
  const hints = profileHygieneHints({
    preferences: { target_roles: ["有机合成研究员"], target_locations: ["连云港"] },
  });
  assert.deepEqual(hints, []);
  const dirty = profileHygieneHints({
    preferences: { target_roles: ["销售；采购"], target_locations: ["杭州 深圳"], job_scope: "domestic" },
  });
  assert.ok(dirty.some((h) => h.code === "role_dirty_phrase"));
  assert.ok(dirty.length <= 3);
});

test("normalizeResumeProfile：LLM 吐的复合写法在落库前就被收拾（与手填同口径）", () => {
  const profile = normalizeResumeProfile({
    target_roles: ["行政/后勤类", "机械工程师助理（设计方向）", "机械设计实习生"],
    target_locations: ["杭州 深圳", "北京市"],
  });
  assert.deepEqual(profile.target_roles, ["行政", "后勤", "机械工程师助理", "机械设计"]);
  assert.deepEqual(profile.target_locations, ["杭州", "深圳", "北京"]);
});

test("buildResumeMessages：prompt 明说 target_roles 要干净岗位名、一格一个", () => {
  const [, user] = buildResumeMessages("简历正文");
  assert.match(user.content, /必须是干净的岗位名/);
  assert.match(user.content, /不要把求职阶段写进岗位名/);
  assert.match(user.content, /标准城市名/);
});

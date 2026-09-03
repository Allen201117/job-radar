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

// ============================================================
// 2026-09-03 治本：公司→行业判定的两类系统性误判
// 用户实锤「宁德时代不算互联网行业」，查下去发现根因有两层：
//   ① 必投清单自己定义了一套行业归属，与本分类器冲突 20 条（门禁见 must-apply-list.test.js）
//   ② 分类器自身两类误判：override 子串张冠李戴、「科技/智能」后缀当互联网
// 判错的代价是**漏推**（制造业用户看不到该看的岗），比判不出更伤，故一律「拿不准就 null 放行」。
// ============================================================

test("override 取最长命中，不被短子串抢走（治『京东方=京东』类张冠李戴）", () => {
  // ⚠️ 与 crawler/must_apply.resolve_owner 同一个病根：`%京东%` 会把京东方(BOE)算成京东。
  // 那边 2026-08-27 已立碑修过，分类器这边一直没修。
  assert.equal(classifyCompanyIndustry("京东方"), "制造/工业", "京东方是显示面板，不是京东");
  assert.equal(classifyCompanyIndustry("BOE 京东方科技集团"), "制造/工业");
  assert.equal(classifyCompanyIndustry("京东物流"), "物流/供应链");
  assert.equal(classifyCompanyIndustry("网易云音乐"), "传媒/文娱");
  assert.equal(classifyCompanyIndustry("网易有道"), "教育");
  assert.equal(classifyCompanyIndustry("腾讯音乐 TME"), "传媒/文娱");
  // 母公司本身不受影响
  assert.equal(classifyCompanyIndustry("京东"), "互联网/科技");
  assert.equal(classifyCompanyIndustry("网易"), "互联网/科技");
  assert.equal(classifyCompanyIndustry("腾讯"), "互联网/科技");
});

test("英文 override 必须成词，不吃单词内部子串（治『雅培 Abbott ← abb』）", () => {
  // live 实测：雅培 3431 个在招岗被 "abb"(ABB 集团) 吃掉判成制造/工业。
  assert.equal(classifyCompanyIndustry("雅培 Abbott"), "医疗/医药");
  assert.equal(classifyCompanyIndustry("ABB 集团"), "制造/工业", "真 ABB 仍判对");
  assert.equal(classifyCompanyIndustry("ABB"), "制造/工业");
});

test("「科技/智能」是通用后缀，不足以判互联网（判不出好过判错）", () => {
  // live 实测：162 家 / 10,757 个在招岗因名字带「科技」被判互联网，
  // 其中轮胎模具(豪迈)、光伏(晶澳/金风)、锂电材料(容百)、半导体设备(拓荆) 全是制造/能源。
  // 拿不准 → null → jobIndustryAllowed 放行，绝不硬判成互联网把制造业用户的岗拦掉。
  assert.equal(classifyCompanyIndustry("豪迈科技"), "制造/工业", "轮胎模具，已逐条补进 override");
  assert.equal(classifyCompanyIndustry("金风科技"), "能源/化工", "风电整机");
  assert.equal(classifyCompanyIndustry("先导智能"), "制造/工业", "锂电装备");
  // 没进 override 的一律 null —— 判不出走放行，绝不硬判互联网
  assert.equal(classifyCompanyIndustry("某某智能科技"), null, "通用后缀，判不出");
  assert.equal(classifyCompanyIndustry("某某科技股份有限公司"), null, "通用后缀，判不出");
  // 强信号仍要判得出
  assert.equal(classifyCompanyIndustry("某某网络科技"), "互联网/科技");
  assert.equal(classifyCompanyIndustry("某某信息技术"), "互联网/科技");
  assert.equal(classifyCompanyIndustry("某某软件"), "互联网/科技");
  assert.equal(classifyCompanyIndustry("某某人工智能"), "互联网/科技");
  assert.equal(classifyCompanyIndustry("某某网络游戏"), "互联网/科技");
  // 别的行业词 + 科技后缀 → 归到那个行业，不被「科技」抢走
  assert.equal(classifyCompanyIndustry("某某光伏科技"), "能源/化工");
  assert.equal(classifyCompanyIndustry("某某半导体科技"), "制造/工业");
  assert.equal(classifyCompanyIndustry("某某生物科技"), "医疗/医药");
});

test("必投清单里被用户点名的错分公司，分类器给出正确行业", () => {
  assert.equal(classifyCompanyIndustry("宁德时代"), "能源/化工", "用户实锤：宁德时代不是互联网");
  assert.equal(classifyCompanyIndustry("蔚来"), "汽车/出行");
  assert.equal(classifyCompanyIndustry("理想汽车"), "汽车/出行");
  assert.equal(classifyCompanyIndustry("小鹏汽车"), "汽车/出行");
  assert.equal(classifyCompanyIndustry("微众银行"), "金融");
  assert.equal(classifyCompanyIndustry("蚂蚁集团"), "金融");
  assert.equal(classifyCompanyIndustry("SHEIN"), "消费/零售");
});

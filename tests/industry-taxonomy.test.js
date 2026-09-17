const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const json = require("../lib/industry-taxonomy.json");
const { INDUSTRY_CATEGORIES } = require("../lib/company-industry.js");
const T = loadTs(path.join(__dirname, "..", "lib", "industry-taxonomy.ts"));

test("industry-taxonomy.json 的 groups 与 company-industry 的 11 个行业分类同一空间", () => {
  assert.deepEqual(json.groups, INDUSTRY_CATEGORIES);
  assert.equal(json.groups.length, 11);
  assert.equal(json.otherGroup, "other");
});

test("mapping 里每个值要么落在 groups 里，要么是 other，不许出现第三种写法", () => {
  const allowed = new Set([...json.groups, json.otherGroup]);
  const bad = Object.entries(json.mapping).filter(([, group]) => !allowed.has(group));
  assert.deepEqual(bad, [], `mapping 里出现了不在 groups∪{other} 的值：${JSON.stringify(bad)}`);
});

test("mapping 的 key 不含空串/首尾空白（否则迁移里按原始 industry 字面值 join 会漏行）", () => {
  const bad = Object.keys(json.mapping).filter((k) => !k || k !== k.trim());
  assert.deepEqual(bad, []);
});

test("classifyIndustry：空值/未收录返回 null，收录值原样返回", () => {
  assert.equal(T.classifyIndustry(null), null);
  assert.equal(T.classifyIndustry(undefined), null);
  assert.equal(T.classifyIndustry(""), null);
  assert.equal(T.classifyIndustry("   "), null);
  assert.equal(T.classifyIndustry("这是一个从没见过的行业写法·不存在于表里"), null);
  // 任务给出的三个示例口径，逐条钉死
  assert.equal(T.classifyIndustry("半导体"), "制造/工业");
  assert.equal(T.classifyIndustry("锂电"), "制造/工业");
  assert.equal(T.classifyIndustry("储能"), "制造/工业");
  assert.equal(T.classifyIndustry("证券"), "金融");
  assert.equal(T.classifyIndustry("基金"), "金融");
  assert.equal(T.classifyIndustry("游戏"), "互联网/科技");
});

test("classifyIndustry 对表里全部 433 条 key 都有确定输出（无 undefined 漏网）", () => {
  for (const [raw, expected] of Object.entries(json.mapping)) {
    assert.equal(T.classifyIndustry(raw), expected, `raw=${raw}`);
  }
});

test("显式裁决的占位符/无信息量标签落 other，不许被规则误猜成某个行业", () => {
  for (const raw of ["discover", "综合", "综合·央企", "综合·实业·国资", "知名私企"]) {
    assert.equal(json.mapping[raw], "other", `${raw} 应该是 other`);
  }
});

test("INDUSTRY_TAXONOMY_VERSION / INDUSTRY_GROUPS / OTHER_INDUSTRY_GROUP 导出与 json 一致", () => {
  assert.equal(T.INDUSTRY_TAXONOMY_VERSION, json._version);
  assert.deepEqual(T.INDUSTRY_GROUPS, json.groups);
  assert.equal(T.OTHER_INDUSTRY_GROUP, json.otherGroup);
});

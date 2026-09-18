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

// ============================================================
// 2026-09-18 v2 批（迁移 273）：265 之后由 seed 迁移新插入的 48 行 sources 带来 18 种新 industry 写法，
// 17 种按既有先例补录、「生物制药·农牧」刻意不收录（见 JSON _boundaryNotes）。先例逐条写在迁移 273 注释里。
// ============================================================
const V2_ADDED = {
  "锂电池": "制造/工业",
  "乳制品": "消费/零售",
  "工业机器人·电梯控制": "制造/工业",
  "电力电子": "制造/工业",
  "财富管理": "金融",
  "连锁便利店": "消费/零售",
  "办公用品·B2B": "消费/零售",
  "商用车": "汽车/出行",
  "客车": "汽车/出行",
  "房产经纪": "地产/建筑",
  "消费品·零售": "消费/零售",
  "激光控制系统": "制造/工业",
  "电力保护与控制": "能源/化工",
  "电子测量仪器": "制造/工业",
  "红外芯片": "制造/工业",
  "网络通信设备": "制造/工业",
  "酒类·快消": "消费/零售",
};

test("v2 批：17 种新写法已收录且口径与先例一致", () => {
  for (const [raw, expected] of Object.entries(V2_ADDED)) {
    assert.equal(json.mapping[raw], expected, raw);
    assert.equal(T.classifyIndustry(raw), expected, raw);
  }
});

test("v2 批：生物制药·农牧 刻意不收录——改主意要先改 _boundaryNotes 再改这里，并补一条新迁移回填", () => {
  assert.equal(json.mapping["生物制药·农牧"], undefined);
  assert.equal(T.classifyIndustry("生物制药·农牧"), null);
  assert.ok(json._boundaryNotes["生物制药·农牧"], "_boundaryNotes 里应留有不收录的理由");
});

// 迁移 273 的兜底 CASE 是从 JSON 自动生成的，这里断言它与 JSON 逐条同值。
// 若日后有意改某条既有映射，这条会红——那是提醒：已应用的迁移不可改，库里存量行需要一条新迁移重跑回填；
// 补完新迁移后把该 key 加进 RE_DECIDED_AFTER_273 豁免即可。
const RE_DECIDED_AFTER_273 = new Set([]);

test("迁移 273：兜底 CASE ⊆ JSON mapping（逐条同值）、按 id 显式回填 46 行且取值只用 groups∪{other}", () => {
  const fs = require("node:fs");
  const sql = fs.readFileSync(
    path.join(__dirname, "..", "supabase", "migrations", "273_backfill_industry_group_post_265_seeds.sql"),
    "utf8",
  );
  const unq = (s) => s.replace(/''/g, "'");
  const caseRe = /^\s+when '((?:[^']|'')*)' then '((?:[^']|'')*)'$/gm;
  let m;
  let caseCount = 0;
  const bad = [];
  while ((m = caseRe.exec(sql))) {
    caseCount += 1;
    const k = unq(m[1]);
    const v = unq(m[2]);
    if (RE_DECIDED_AFTER_273.has(k)) continue;
    if (json.mapping[k] !== v) bad.push(`${k}: 迁移「${v}」≠ JSON「${json.mapping[k]}」`);
  }
  assert.equal(caseCount, 450, "生成时 JSON 有 450 条，CASE 条目数应与之相同");
  assert.deepEqual(bad, []);

  const allowed = new Set([...json.groups, json.otherGroup]);
  const setRe = /set industry_group = '((?:[^']|'')*)' where id = '/g;
  let s;
  let setCount = 0;
  const badSet = [];
  while ((s = setRe.exec(sql))) {
    setCount += 1;
    if (!allowed.has(unq(s[1]))) badSet.push(s[1]);
  }
  assert.equal(setCount, 46, "按 id 显式回填应为 46 行（enabled 44 + disabled 2；天康生物 2 行刻意不回填）");
  assert.deepEqual(badSet, []);
});

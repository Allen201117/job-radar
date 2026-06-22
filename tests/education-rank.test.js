const test = require("node:test");
const assert = require("node:assert/strict");
const { educationRank, educationMatch } = require("../lib/education-rank");

// 学历筛选「准确遵循」的核心守护：用例直接取自香港库 active 岗位 education 字段的真实分布
// （本科/本科及以上/大学本科/硕士研究生及以上/大专(含高职)/统招本科/中专… 几十种变体 + ~43% 空），
// 证明面对真实脏数据仍按学历层级正确判定，而非被原始文本差异一刀切误杀。

test("educationRank：干净档位", () => {
  assert.equal(educationRank("博士"), 6);
  assert.equal(educationRank("硕士"), 5);
  assert.equal(educationRank("本科"), 4);
  assert.equal(educationRank("大专"), 3);
  assert.equal(educationRank("不限"), 0);
});

test("educationRank：真实脏变体归到正确档位（取自 DB 实测分布）", () => {
  // 本科档
  for (const v of ["本科及以上", "大学本科", "大学本科及以上", "统招本科", "统招本科及以上"]) {
    assert.equal(educationRank(v), 4, v);
  }
  // 硕士档（含「研究生」字样但不是博士）
  for (const v of ["硕士研究生", "硕士研究生及以上", "硕士及以上"]) {
    assert.equal(educationRank(v), 5, v);
  }
  // 博士档（「博士研究生」必须判博士=6，不能被「研究生」误判成硕士）
  for (const v of ["博士研究生", "博士研究生及以上", "博士及以上"]) {
    assert.equal(educationRank(v), 6, v);
  }
  // 大专档
  for (const v of ["大专及以上", "专科及以上", "专科", "大专(含高职)", "大专(含高职)及以上", "大学专科及以上"]) {
    assert.equal(educationRank(v), 3, v);
  }
  // 高中/中专档
  for (const v of ["中专", "中专及以上", "高中", "高中及以上", "中专/中技及以上", "技校/职高及以上", "中技及以上"]) {
    assert.equal(educationRank(v), 2, v);
  }
  // 初中档
  for (const v of ["初中", "初中及以下"]) {
    assert.equal(educationRank(v), 1, v);
  }
});

test("educationRank：英文学历", () => {
  assert.equal(educationRank("Bachelor degree required"), 4);
  assert.equal(educationRank("Master"), 5);
  assert.equal(educationRank("PhD"), 6);
  assert.equal(educationRank("Ph.D. preferred"), 6);
});

test("educationRank：无学历语义 → null（交给调用方降级，不当成不限误放精确层）", () => {
  assert.equal(educationRank("其他"), null);
  assert.equal(educationRank("其它"), null);
  assert.equal(educationRank(""), null);
  assert.equal(educationRank(null), null);
  assert.equal(educationRank(undefined), null);
});

test("educationMatch：学历不限（空）→ 不筛，恒 pass", () => {
  assert.equal(educationMatch("硕士及以上", ""), "pass");
  assert.equal(educationMatch(null, ""), "pass");
});

test("educationMatch：用户本科 → 要求≤本科够格 / 要求更高淘汰 / 缺失降级", () => {
  // 够格（精确放行）
  assert.equal(educationMatch("本科", "本科"), "pass");
  assert.equal(educationMatch("本科及以上", "本科"), "pass");
  assert.equal(educationMatch("大专", "本科"), "pass"); // 本科生够格投大专岗
  assert.equal(educationMatch("高中及以上", "本科"), "pass");
  assert.equal(educationMatch("不限", "本科"), "pass");
  // 够不着（淘汰）
  assert.equal(educationMatch("硕士及以上", "本科"), "reject");
  assert.equal(educationMatch("硕士研究生", "本科"), "reject");
  assert.equal(educationMatch("博士", "本科"), "reject");
  // 信息缺失/解析不出 → 降级不淘汰（产品铁律：缺字段不一刀切）
  assert.equal(educationMatch(null, "本科"), "degrade");
  assert.equal(educationMatch("", "本科"), "degrade");
  assert.equal(educationMatch("其他", "本科"), "degrade");
});

test("educationMatch：用户大专 → 只够大专及以下，本科/硕士岗淘汰", () => {
  assert.equal(educationMatch("大专", "大专"), "pass");
  assert.equal(educationMatch("大专及以上", "大专"), "pass");
  assert.equal(educationMatch("中专及以上", "大专"), "pass");
  assert.equal(educationMatch("不限", "大专"), "pass");
  assert.equal(educationMatch("本科", "大专"), "reject");
  assert.equal(educationMatch("本科及以上", "大专"), "reject");
  assert.equal(educationMatch("硕士", "大专"), "reject");
});

test("educationMatch：用户硕士 → 博士岗淘汰，本科/大专岗够格", () => {
  assert.equal(educationMatch("硕士研究生及以上", "硕士"), "pass");
  assert.equal(educationMatch("本科", "硕士"), "pass");
  assert.equal(educationMatch("大专", "硕士"), "pass");
  assert.equal(educationMatch("博士", "硕士"), "reject");
  assert.equal(educationMatch("博士研究生", "硕士"), "reject");
});

test("educationMatch：用户博士 → 通吃所有学历要求，缺失仍降级", () => {
  for (const v of ["博士", "硕士及以上", "本科", "大专", "不限"]) {
    assert.equal(educationMatch(v, "博士"), "pass", v);
  }
  assert.equal(educationMatch(null, "博士"), "degrade");
});

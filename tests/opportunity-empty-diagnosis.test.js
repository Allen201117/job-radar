const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("path");
const { loadTs } = require("./_load-ts.js");

const {
  planWidenings,
  widenProfile,
  summarizeCriteria,
  WIDEN_DIM_LABEL,
} = loadTs(path.join(__dirname, "..", "lib/opportunities/empty-diagnosis.ts"));

// 2026-09-18 走查里那个唯一真 0 岗的用户，原样拿来当基准用例。
function profile(over = {}) {
  return {
    userId: "u1",
    jobScope: "domestic",
    targetRegions: [],
    targetRoles: ["仓库文员", "办公室文员"],
    targetKeywords: [],
    excludeKeywords: [],
    targetLocations: ["深圳"],
    targetCompanies: [],
    targetIndustries: [],
    skills: [],
    experienceStage: "校招",
    seniority: null,
    highestEducation: null,
    dailyLimit: 20,
    ...over,
  };
}

test("城市排在阶段前面——它最常见、也最不伤匹配精度", () => {
  assert.deepEqual(planWidenings(profile()), [
    { dim: "city", from: "深圳" },
    { dim: "stage", from: "校招" },
  ]);
});

test("没填的维度不当成「可放宽」，否则会提示放宽一个根本没生效的条件", () => {
  assert.deepEqual(planWidenings(profile({ targetLocations: [] })), [
    { dim: "stage", from: "校招" },
  ]);
  assert.deepEqual(planWidenings(profile({ experienceStage: "" })), [
    { dim: "city", from: "深圳" },
  ]);
  assert.deepEqual(
    planWidenings(profile({ targetLocations: [], experienceStage: "" })),
    [],
  );
});

test("空白字符串的城市不算填了", () => {
  assert.deepEqual(planWidenings(profile({ targetLocations: ["  ", ""] })), [
    { dim: "stage", from: "校招" },
  ]);
});

test("放宽一次只动一维，其余字段逐字不变", () => {
  const base = profile();
  const byCity = widenProfile(base, "city");
  assert.deepEqual(byCity.targetLocations, []);
  assert.equal(byCity.experienceStage, "校招");
  assert.deepEqual(byCity.targetRoles, base.targetRoles);

  const byStage = widenProfile(base, "stage");
  assert.equal(byStage.experienceStage, "");
  assert.deepEqual(byStage.targetLocations, ["深圳"]);

  // 原对象不许被改（服务端会拿原画像继续做别的事）
  assert.deepEqual(base.targetLocations, ["深圳"]);
  assert.equal(base.experienceStage, "校招");
});

// 方向是用户最明确的诉求，放宽它 = 把推荐变成大杂烩，违反「精准 > 规模」。
// 方向召回过窄（「仓库文员」被拆成 `仓库 AND 文员`）是召回层的结构问题，要在那里修。
test("方向词永远不在可放宽维度里", () => {
  const dims = planWidenings(profile()).map((p) => p.dim);
  assert.equal(dims.includes("role"), false);
  assert.deepEqual(Object.keys(WIDEN_DIM_LABEL).sort(), ["city", "stage"]);
});

test("条件摘要按「城市 · 阶段 · 方向」的顺序念回给用户", () => {
  assert.deepEqual(summarizeCriteria(profile()), [
    "深圳",
    "校招",
    "仓库文员、办公室文员",
  ]);
});

test("没填目标岗位时摘要回退到关键词，都没有就不编", () => {
  assert.deepEqual(
    summarizeCriteria(profile({ targetRoles: [], targetKeywords: ["供应链"] })),
    ["深圳", "校招", "供应链"],
  );
  assert.deepEqual(
    summarizeCriteria(profile({ targetRoles: [], targetKeywords: [] })),
    ["深圳", "校招"],
  );
});

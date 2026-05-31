const assert = require("node:assert/strict");
const test = require("node:test");

const {
  CHINA_PRIORITY_SOURCES,
  buildChinaPrioritySourceCandidates,
  getKnownChinaOfficialSource,
} = require("../lib/china-official-sources");

test("keeps a broad China source pool for private beta coverage", () => {
  assert.ok(CHINA_PRIORITY_SOURCES.length >= 28);
  assert.deepEqual(
    CHINA_PRIORITY_SOURCES.slice(0, 10).map((source) => source.source_name),
    [
      "腾讯",
      "阿里巴巴",
      "字节跳动",
      "美团",
      "京东",
      "百度",
      "华为",
      "中国移动",
      "招商银行",
      "Siemens 中国",
    ],
  );
  for (const sourceName of ["快手", "小红书", "网易", "华为", "比亚迪", "宁德时代", "中金"]) {
    assert.ok(
      CHINA_PRIORITY_SOURCES.some((source) => source.source_name === sourceName),
      `${sourceName} should be in the China source pool`,
    );
  }
});

test("builds China official candidates before overseas ATS fallback", () => {
  const candidates = buildChinaPrioritySourceCandidates({
    query: "数据分析 实习 上海",
  });

  assert.ok(candidates.length >= 28);
  assert.equal(candidates[0].detected_platform, "official_careers");
  assert.equal(candidates[0].status, "pending");
  assert.match(candidates[0].reason, /中国官方招聘源/);
});

test("filters China official candidates when a company is supplied", () => {
  const candidates = buildChinaPrioritySourceCandidates({
    company: "百度",
    query: "算法 校招 北京",
  });

  assert.deepEqual(
    candidates.map((candidate) => candidate.source_name),
    ["百度"],
  );
});

test("looks up known China official source by URL host", () => {
  const source = getKnownChinaOfficialSource("https://jobs.bytedance.com/campus/position");

  assert.equal(source.source_name, "字节跳动");
  assert.equal(source.detected_platform, "official_careers");
});

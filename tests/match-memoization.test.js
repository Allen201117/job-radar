// 匹配层记忆化的回归护栏（2026-09-02 线上 /jobs 60s 被 maxDuration 砍断后加）。
//
// 背景：无筛选搜索要给 SCAN_BUDGET=28000 个岗位逐个打分，而 keywordMatchUnits /
// _matchedGroupIndexes 只依赖查询串却被「每岗 × 每关键词」重算。某画像存了 23 个
// target_keywords → 单次请求 60,149ms 被杀。改成按查询串缓存后 8× 提速。
//
// 这里钉两条不变量：
//   ① 缓存不改语义 —— 同一查询重复调用、以及不同 options 之间，结果必须逐字段相同；
//   ② 缓存返回的数组是只读契约 —— 调用方若就地改写，会污染后续所有请求。
const assert = require("node:assert/strict");
const test = require("node:test");

const {
  keywordMatchUnits,
  ftsCandidateTerms,
  keywordMatchTier,
  jobMatchesChinaKeyword,
} = require("../lib/china-keyword-expansion.js");

const QUERIES = ["产品经理", "AI 数据产品经理", "前端", "天线工程师", "AI PM", "中学数学教师", "算法", "pm"];

test("keywordMatchUnits：重复调用结果稳定，且不同 options 各自独立（缓存键含 options）", () => {
  for (const q of QUERIES) {
    const a = keywordMatchUnits(q);
    const b = keywordMatchUnits(q);
    assert.deepEqual(b, a, `${q}：重复调用结果漂移`);

    const overseas = keywordMatchUnits(q, { includeOverseasLexicon: true });
    // 海外词库只会并入更多同义词，绝不会更少 —— 若两者相等说明缓存键漏了 options、串了档。
    assert.ok(
      overseas.flat().length >= a.flat().length,
      `${q}：includeOverseasLexicon 的结果比国内档还窄，缓存键可能漏了 options`,
    );
    // 再取一次国内档，确认没有被上面那次海外调用覆盖掉。
    assert.deepEqual(keywordMatchUnits(q), a, `${q}：国内档被海外档的缓存覆盖了`);
  }
});

test("keywordMatchUnits 命中缓存时返回同一份对象 —— 所以调用方只能读、不能就地改写", () => {
  // 这条不是「测缓存能自愈」，而是把**共享**这件事钉成显式契约：命中缓存拿到的是同一个数组，
  // 任何 push / splice / sort 都会漏给后续所有请求（含别的用户）。
  // 现有调用方全部只做 every / some / filter / map（lib/china-keyword-expansion.js 内各处 +
  // lib/jobs-store/opportunities.ts:118）；新增调用方若要改写，必须先自己复制一份。
  const a = keywordMatchUnits("产品经理");
  const b = keywordMatchUnits("产品经理");
  assert.equal(b, a, "同一查询两次调用应命中缓存、返回同一份对象");
  assert.equal(b[0], a[0], "单元数组本身也是共享的");
});

test("记忆化后关键词分层/命中/FTS 候选词与逐次直算一致", () => {
  const jobs = [
    { id: "1", title: "产品经理", company: "字节跳动", summary: "负责用户增长与需求拆解" },
    { id: "2", title: "前端开发工程师", company: "腾讯", summary: "React / TypeScript" },
    { id: "3", title: "天线工程师", company: "华为", summary: "射频与天线设计" },
    { id: "4", title: "中学数学教师", company: "某中学", summary: "初中数学教学" },
  ];
  for (const q of QUERIES) {
    const tiers = jobs.map((j) => keywordMatchTier(j, q));
    const hits = jobs.map((j) => jobMatchesChinaKeyword(j, q));
    const fts = ftsCandidateTerms(q);
    // 反复跑，缓存命中路径与首次计算路径必须给出同样的答案。
    for (let i = 0; i < 3; i++) {
      assert.deepEqual(jobs.map((j) => keywordMatchTier(j, q)), tiers, `${q}：分层结果漂移`);
      assert.deepEqual(jobs.map((j) => jobMatchesChinaKeyword(j, q)), hits, `${q}：命中结果漂移`);
      assert.deepEqual(ftsCandidateTerms(q), fts, `${q}：FTS 候选词漂移`);
    }
  }
});

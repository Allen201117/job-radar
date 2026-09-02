const assert = require("node:assert/strict");
const test = require("node:test");

const {
  jobMatchesChinaKeyword,
  keywordMatchTier,
  keywordMatchUnits,
  classifyJobFunction,
} = require("../lib/china-keyword-expansion");

// 匹配热路径上有三层记忆化（见 lib/china-keyword-expansion.js 文件头）：term / query / job。
// 它们把 /api/jobs/search 的打分从 20.9s 压到 0.2s，但**缓存 key 漏掉任何一个输入，就会让
// 一个岗位或一个查询拿到另一个的判定结果**——静默改坏筛选准确性且不报错。
// 下面每个用例钉死一个「如果 key 写漏了就会挂」的场景，别删。

test("同一个岗位对象连着查不同关键词，各自判定互不串味", () => {
  // 若 query 展开（keywordMatchUnits / _matchedGroupIndexes）被错误地按岗位缓存，
  // 第二个查询会拿到第一个查询的单元 → 前端岗会被判成命中「后端」。
  const job = { title: "前端开发工程师", company: "某科技", summary: "负责 React 页面开发" };
  assert.equal(jobMatchesChinaKeyword(job, "前端"), true);
  assert.equal(jobMatchesChinaKeyword(job, "护士"), false);
  assert.equal(jobMatchesChinaKeyword(job, "前端"), true, "回查同一关键词结果必须稳定");
});

test("同一个关键词连着查不同岗位，各自判定互不串味", () => {
  // 若岗位派生文本（title/company/content）被错误地按查询缓存，第二个岗位会复用第一个的正文。
  const frontend = { title: "前端开发工程师", summary: "React / TypeScript" };
  const nurse = { title: "临床护士", summary: "负责病区护理" };
  assert.equal(jobMatchesChinaKeyword(frontend, "前端"), true);
  assert.equal(jobMatchesChinaKeyword(nurse, "前端"), false);
  assert.equal(jobMatchesChinaKeyword(frontend, "前端"), true);
});

test("岗位对象被就地改写后，派生文本缓存必须失效重算", () => {
  // 富化补正文 / annotate 会就地改行对象。缓存守卫比对的是原始字段引用，改了就得重算，
  // 否则补上正文的岗位仍按旧空正文匹配。
  const job = { title: "工程师", company: "某公司", summary: null };
  assert.equal(jobMatchesChinaKeyword(job, "护士"), false);
  job.title = "临床护士";
  assert.equal(jobMatchesChinaKeyword(job, "护士"), true, "改了 title 必须按新 title 判");
  job.title = "工程师";
  assert.equal(jobMatchesChinaKeyword(job, "护士"), false, "改回去也要跟着变");
});

test("classifyJobFunction 同样跟随岗位就地改写", () => {
  const job = { title: "前端开发工程师" };
  assert.equal(classifyJobFunction(job), "研发");
  job.title = "临床护士";
  assert.equal(classifyJobFunction(job), "医疗健康");
});

test("includeOverseasLexicon 参与 units 缓存 key，两种模式不共用一份", () => {
  // 漏掉这个 flag 会让国内画像拿到海外词库展开（或反过来），跨语言召回口径整体漂移。
  const domestic = keywordMatchUnits("产品经理");
  const overseas = keywordMatchUnits("产品经理", { includeOverseasLexicon: true });
  const domesticAgain = keywordMatchUnits("产品经理");
  assert.deepEqual(domesticAgain, domestic, "国内模式回查必须还是国内那份");
  assert.ok(
    overseas.flat().length >= domestic.flat().length,
    "海外模式是国内模式的超集（并入英文词库）",
  );
});

test("缓存返回的 units 是冻结的：调用方就地改写会当场抛错而不是污染下一个查询", () => {
  const units = keywordMatchUnits("产品经理");
  assert.ok(Object.isFrozen(units), "外层数组必须冻结");
  assert.ok(units.every((u) => Object.isFrozen(u)), "每个匹配单元也要冻结");
  assert.throws(() => units.push(["注入"]), TypeError);
});

test("keywordMatchTier 的 exact / related / null 三档在重复调用下稳定", () => {
  // related 档要读岗位 searchable 全文（惰性缓存的那份），重复调用必须每次都一样。
  const job = { title: "高级软件工程师", company: "某科技", summary: "负责服务端系统开发" };
  const first = keywordMatchTier(job, "后端");
  assert.equal(keywordMatchTier(job, "后端"), first);
  assert.equal(keywordMatchTier(job, "后端"), first);
  assert.equal(keywordMatchTier(job, "护士"), null, "跨职能查询不该被上一次调用带上来");
});

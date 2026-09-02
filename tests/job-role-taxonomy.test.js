const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { matchesJobRole, DEFAULT_FILTERS } = loadTs(path.join(__dirname, "..", "lib", "job-filter.ts"));
const {
  JOB_FUNCTION_TAXONOMY,
  JOB_FUNCTION_BUCKETS,
  CHINA_KEYWORD_GROUPS,
  KEYWORD_GROUP_FUNCTIONS,
} = require("../lib/china-keyword-expansion.js");

// ── 派生树本身 ────────────────────────────────────────────────
// 这棵树必须是**从既有词表按下标派生**的，不能是另写的一份手写表：词表新增方向时手写表会漏同步，
// UI 就会重新出现「能搜到却不能筛」的断层——两级筛选做出来正是为了消掉这种断层。
test("job function taxonomy is derived from the keyword groups, not hand-written", () => {
  assert.deepEqual(
    JOB_FUNCTION_TAXONOMY.map((entry) => entry.function),
    [...JOB_FUNCTION_BUCKETS],
    "一级顺序必须与 JOB_FUNCTION_BUCKETS 完全一致（UI 顺序稳定）",
  );
  for (const entry of JOB_FUNCTION_TAXONOMY) {
    const expected = CHINA_KEYWORD_GROUPS.flatMap((group, i) =>
      KEYWORD_GROUP_FUNCTIONS[i] === entry.function ? [group[0]] : [],
    );
    assert.deepEqual([...entry.roles], expected, `${entry.function} 的二级必须按下标从词表派生`);
  }
});

test("groups with no function mapping never leak into the picker", () => {
  // function=null 的组是「技术领域 / 招聘类型 / 泛锚点」（AI、移动端、实习、工程师…），
  // 不是可供用户主动收窄的岗位方向。放进筛选器会造成跨方向污染。
  const unmapped = CHINA_KEYWORD_GROUPS.filter((_, i) => KEYWORD_GROUP_FUNCTIONS[i] === null).map(
    (group) => group[0],
  );
  const shown = new Set(JOB_FUNCTION_TAXONOMY.flatMap((entry) => entry.roles));
  for (const role of unmapped) {
    assert.ok(!shown.has(role), `未映射一级的组「${role}」不该出现在筛选器里`);
  }
});

test("the roles founders asked for are actually selectable", () => {
  // 创始人原话：「最核心的一个岗位类型都没有，比如研发、产品、设计、测试」——「测试」此前被
  // 并进「研发」大桶、根本不是独立选项。这条钉死它们必须可选。
  const byFn = Object.fromEntries(JOB_FUNCTION_TAXONOMY.map((e) => [e.function, e.roles]));
  assert.ok(byFn["研发"].includes("测试"), "「测试」必须能在「研发」下单独勾选");
  assert.ok(byFn["研发"].includes("前端") && byFn["研发"].includes("后端"));
  assert.ok(byFn["产品"].includes("产品经理"));
  assert.ok(byFn["设计"].includes("设计"));
  // 非互联网行业同样要有细分，否则「别的行业」的用户还是只能按大桶筛
  assert.ok(byFn["金融业务"].length >= 2, "金融业务要有细分方向");
  assert.ok(byFn["医疗健康"].length >= 2, "医疗健康要有细分方向");
  assert.ok(byFn["生产制造"].length >= 2, "生产制造要有细分方向");
});

// ── matchesJobRole ───────────────────────────────────────────
const job = (title, summary = "") => ({ title, summary });

test("empty selection does not filter", () => {
  assert.equal(DEFAULT_FILTERS.jobRole, "");
  assert.equal(matchesJobRole(job("任意岗位"), ""), true);
});

test("role match is title-anchored, not body-anchored", () => {
  assert.equal(matchesJobRole(job("测试开发工程师"), "测试"), true);
  // 关键反例：标题写着销售、正文提到测试。二级筛选是用户主动收窄，放相关层进来就会把这种岗
  // 冒充成测试岗（上一轮跨职能精度攻坚修的正是这类串味）。
  assert.equal(
    matchesJobRole(job("销售工程师", "负责产品测试环节的客户对接与测试反馈收集"), "测试"),
    false,
  );
});

test("multiple roles are OR-ed", () => {
  assert.equal(matchesJobRole(job("前端开发工程师"), "测试,前端"), true);
  assert.equal(matchesJobRole(job("后端开发工程师"), "测试,前端"), false);
});

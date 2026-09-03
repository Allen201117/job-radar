const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { actionHiddenJobIds, sortAndFilterJobs } = loadTs(
  path.join(__dirname, "..", "lib", "scoring.ts"),
);

// actionHiddenJobIds 是「候选撞上限时用 count(*) 算真实总数」的一块拼图：SQL 要把这些岗一并排除，
// 才和 JS 的 hidden_reason 口径对得上。这里拿真实流水线（sortAndFilterJobs）对拍，钉死两边不漂。

const prefs = { target_roles: [], target_keywords: [], exclude_keywords: [] };
const job = (id) => ({ id, company: "A", title: "工程师", summary: "", location: "深圳" });
const act = (jobId, action, at) => ({
  id: `a-${jobId}-${action}`,
  user_id: "u",
  job_id: jobId,
  action,
  created_at: at,
});

/** 用真实流水线算出「默认被隐藏」的 id —— 与被测函数完全独立的一条路。 */
function hiddenViaPipeline(jobs, actions, options) {
  const kept = new Set(sortAndFilterJobs(jobs, prefs, actions, options).map((j) => j.id));
  return new Set(jobs.map((j) => j.id).filter((id) => !kept.has(id)));
}

test("ignored / applied 被隐藏，saved 与 viewed 不隐藏", () => {
  const jobs = ["j1", "j2", "j3", "j4"].map(job);
  const actions = [
    act("j1", "ignored", "2026-09-01T00:00:00Z"),
    act("j2", "applied", "2026-09-01T00:00:00Z"),
    act("j3", "saved", "2026-09-01T00:00:00Z"),
    act("j4", "viewed", "2026-09-01T00:00:00Z"),
  ];
  assert.deepEqual([...actionHiddenJobIds(actions, {})].sort(), ["j1", "j2"]);
  assert.deepEqual(actionHiddenJobIds(actions, {}), hiddenViaPipeline(jobs, actions, {}));
});

test("同一岗位多条操作 → 以最近一次非 viewed 的为准", () => {
  const jobs = [job("j1")];
  // 先忽略、后取消忽略改成收藏 → 不该再被隐藏；viewed 更晚也不能盖掉。
  const actions = [
    act("j1", "ignored", "2026-09-01T00:00:00Z"),
    act("j1", "saved", "2026-09-02T00:00:00Z"),
    act("j1", "viewed", "2026-09-03T00:00:00Z"),
  ];
  assert.equal(actionHiddenJobIds(actions, {}).size, 0);
  assert.deepEqual(actionHiddenJobIds(actions, {}), hiddenViaPipeline(jobs, actions, {}));
});

test("两个开关的每种组合都与真实流水线一致", () => {
  const jobs = ["j1", "j2", "j3"].map(job);
  const actions = [
    act("j1", "ignored", "2026-09-01T00:00:00Z"),
    act("j2", "applied", "2026-09-01T00:00:00Z"),
    act("j3", "applied", "2026-09-01T00:00:00Z"),
  ];
  for (const showIgnored of [false, true]) {
    for (const showApplied of [false, true]) {
      const options = { showIgnored, showApplied };
      assert.deepEqual(
        actionHiddenJobIds(actions, options),
        hiddenViaPipeline(jobs, actions, options),
        `showIgnored=${showIgnored} showApplied=${showApplied}`,
      );
    }
  }
});

test("无偏好时用户操作根本不生效 → 调用方不得传隐藏集合", () => {
  // scoreJob 在 preferences 为 null 时直接返回 hidden_reason=null，
  // 所以 lib/jobs-store/search.ts 只在 prefs 非空时才构造隐藏集合，这里钉住那个前提。
  const jobs = [job("j1")];
  const actions = [act("j1", "ignored", "2026-09-01T00:00:00Z")];
  assert.equal(sortAndFilterJobs(jobs, null, actions, {}).length, 1);
});

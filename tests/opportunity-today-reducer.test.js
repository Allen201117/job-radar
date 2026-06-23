const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { todayReducer, initTodayState } = loadOpp("today-reducer");

function opp(id) {
  return {
    job: { id, company: "C", title: "T", jd_url: "u" + id },
    score: 50, tier: "high", reasons: [], freshness: "verified",
    firstSeenAt: "2026-06-20", lastSeenAt: "2026-06-23",
    userAction: null, viewed: false, isNew: false, exploreEligible: false,
  };
}
function sections(n = [], p = [], e = [], a = []) {
  return { new: n.map(opp), priority: p.map(opp), explore: e.map(opp), aging: a.map(opp) };
}
const ids = (arr) => arr.map((o) => o.job.id);

test("removeOptimistic 移出 + pending + toast", () => {
  let s = initTodayState(sections([], ["a", "b", "c"]));
  s = todayReducer(s, { type: "removeOptimistic", jobId: "b", action: "ignored" });
  assert.deepEqual(ids(s.sections.priority), ["a", "c"]);
  assert.equal(s.pending["b"].action, "ignored");
  assert.deepEqual(s.toast, { jobId: "b", action: "ignored" });
});

test("removeOptimistic 幂等（重复点击不互相覆盖）", () => {
  let s = initTodayState(sections([], ["a", "b"]));
  s = todayReducer(s, { type: "removeOptimistic", jobId: "a", action: "saved" });
  const s2 = todayReducer(s, { type: "removeOptimistic", jobId: "a", action: "applied" });
  assert.equal(s2, s); // no-op，返回同引用
});

test("removeRollback 还原到原位、清 pending+toast（顺序不漂移）", () => {
  let s = initTodayState(sections([], ["a", "b", "c"]));
  s = todayReducer(s, { type: "removeOptimistic", jobId: "b", action: "saved" });
  s = todayReducer(s, { type: "removeRollback", jobId: "b" });
  assert.deepEqual(ids(s.sections.priority), ["a", "b", "c"]);
  assert.equal(s.pending["b"], undefined);
  assert.equal(s.toast, null);
});

test("finalizeRemove 落定（保持移除、清 pending/toast）", () => {
  let s = initTodayState(sections([], ["a", "b"]));
  s = todayReducer(s, { type: "removeOptimistic", jobId: "a", action: "applied" });
  s = todayReducer(s, { type: "finalizeRemove", jobId: "a" });
  assert.deepEqual(ids(s.sections.priority), ["b"]);
  assert.equal(s.pending["a"], undefined);
  assert.equal(s.toast, null);
});

test("undo 成功：恢复后 commit", () => {
  let s = initTodayState(sections([], ["a", "b"]));
  s = todayReducer(s, { type: "removeOptimistic", jobId: "a", action: "ignored" });
  s = todayReducer(s, { type: "undoOptimistic", jobId: "a" });
  assert.deepEqual(ids(s.sections.priority), ["a", "b"]);
  assert.ok(s.undoing["a"]);
  assert.equal(s.toast, null);
  s = todayReducer(s, { type: "undoCommit", jobId: "a" });
  assert.equal(s.undoing["a"], undefined);
  assert.deepEqual(ids(s.sections.priority), ["a", "b"]);
});

test("undo 失败：恢复后 rollback 重新移出 + undoFailed toast", () => {
  let s = initTodayState(sections([], ["a", "b"]));
  s = todayReducer(s, { type: "removeOptimistic", jobId: "a", action: "ignored" });
  s = todayReducer(s, { type: "undoOptimistic", jobId: "a" });
  s = todayReducer(s, { type: "undoRollback", jobId: "a" });
  assert.deepEqual(ids(s.sections.priority), ["b"]);
  assert.equal(s.undoing["a"], undefined);
  assert.equal(s.toast.undoFailed, true);
});

test("多岗并发互不影响", () => {
  let s = initTodayState(sections([], ["a", "b", "c"]));
  s = todayReducer(s, { type: "removeOptimistic", jobId: "a", action: "saved" });
  s = todayReducer(s, { type: "removeOptimistic", jobId: "c", action: "ignored" });
  assert.deepEqual(ids(s.sections.priority), ["b"]);
  s = todayReducer(s, { type: "removeRollback", jobId: "a" });
  assert.deepEqual(ids(s.sections.priority), ["a", "b"]); // a 回原位 index0；c 仍移除
  assert.ok(s.pending["c"]);
});

test("init 克隆，不改动原 sections", () => {
  const orig = sections([], ["a"]);
  const s = initTodayState(orig);
  s.sections.priority.push(opp("x"));
  assert.deepEqual(ids(orig.priority), ["a"]);
});

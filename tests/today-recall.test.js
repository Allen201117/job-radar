const assert = require("node:assert/strict");
const test = require("node:test");

const { mergeRecallJobs } = require("../lib/today-recall");

// 造岗位：只关心 id（合并/去重逻辑只看 id）
const mk = (n, prefix) =>
  Array.from({ length: n }, (_, i) => ({ id: `${prefix}${i}` }));

test("预筛充足（≥ minPreferred）→ 不补兜底，原样返回", () => {
  const preferred = [{ id: "p1" }, { id: "p2" }, { id: "p3" }];
  const fallback = [{ id: "f1" }, { id: "f2" }];
  const out = mergeRecallJobs(preferred, fallback, { target: 10, minPreferred: 2 });
  assert.deepEqual(
    out.map((j) => j.id),
    ["p1", "p2", "p3"],
  );
});

test("预筛不足（< minPreferred）→ 用兜底补齐", () => {
  const preferred = [{ id: "p1" }, { id: "p2" }];
  const fallback = [{ id: "f1" }, { id: "f2" }, { id: "f3" }];
  const out = mergeRecallJobs(preferred, fallback, { target: 10, minPreferred: 5 });
  assert.deepEqual(
    out.map((j) => j.id),
    ["p1", "p2", "f1", "f2", "f3"],
  );
});

test("补齐时与预筛重叠的 id 去重（兜底里已取到的不重复计入）", () => {
  const preferred = [{ id: "a" }, { id: "b" }];
  // 兜底里 a/b 与预筛重叠，应被跳过
  const fallback = [{ id: "b" }, { id: "c" }, { id: "a" }, { id: "d" }];
  const out = mergeRecallJobs(preferred, fallback, { target: 10, minPreferred: 5 });
  assert.deepEqual(
    out.map((j) => j.id),
    ["a", "b", "c", "d"],
  );
});

test("补齐后总数不超过 target（截断）", () => {
  const preferred = [{ id: "p1" }, { id: "p2" }];
  const fallback = [{ id: "f1" }, { id: "f2" }, { id: "f3" }, { id: "f4" }];
  const out = mergeRecallJobs(preferred, fallback, { target: 3, minPreferred: 5 });
  assert.equal(out.length, 3);
  assert.deepEqual(
    out.map((j) => j.id),
    ["p1", "p2", "f1"],
  );
});

test("预筛内部重复 id 也去重", () => {
  const preferred = [{ id: "x" }, { id: "x" }, { id: "y" }];
  const out = mergeRecallJobs(preferred, [], { target: 10, minPreferred: 5 });
  assert.deepEqual(
    out.map((j) => j.id),
    ["x", "y"],
  );
});

test("兜底也凑不满 target 时不报错，有多少给多少", () => {
  const preferred = [{ id: "p1" }];
  const fallback = [{ id: "f1" }];
  const out = mergeRecallJobs(preferred, fallback, { target: 10, minPreferred: 5 });
  assert.deepEqual(
    out.map((j) => j.id),
    ["p1", "f1"],
  );
});

test("跳过 null 条目与缺失 id 的脏数据", () => {
  const preferred = [null, { id: "a" }, { id: null }, undefined];
  const fallback = [{ id: "b" }, { id: undefined }];
  const out = mergeRecallJobs(preferred, fallback, { target: 10, minPreferred: 5 });
  assert.deepEqual(
    out.map((j) => j.id),
    ["a", "b"],
  );
});

test("默认参数：minPreferred=50 时预筛 60 条不触发兜底", () => {
  const preferred = mk(60, "p");
  const fallback = mk(200, "f");
  const out = mergeRecallJobs(preferred, fallback);
  assert.equal(out.length, 60);
  assert.equal(out[0].id, "p0");
});

test("默认参数：预筛 40 条（< 50）补兜底，封顶 target=200", () => {
  const preferred = mk(40, "p");
  const fallback = mk(300, "f");
  const out = mergeRecallJobs(preferred, fallback);
  assert.equal(out.length, 200);
  // 前 40 仍是预筛结果，其后是兜底
  assert.equal(out[0].id, "p0");
  assert.equal(out[39].id, "p39");
  assert.equal(out[40].id, "f0");
});

test("非数组入参安全（不抛）", () => {
  assert.deepEqual(mergeRecallJobs(undefined, null, { minPreferred: 5 }), []);
  assert.deepEqual(
    mergeRecallJobs([{ id: "a" }], undefined, { minPreferred: 5 }).map((j) => j.id),
    ["a"],
  );
});

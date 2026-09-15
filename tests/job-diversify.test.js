const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");
const { spreadByCompany } = loadTs(path.join(__dirname, "..", "lib", "job-diversify.ts"));

const J = (company, id) => ({ company, id: String(id) });
const multiset = (arr) => arr.map((j) => j.id).sort().join(",");

test("保多集:重排前后同一批 job(长度+成员不变)", () => {
  const ranked = [];
  for (let i = 0; i < 300; i++) ranked.push(J(i < 200 ? "字节跳动" : "小公司" + i, i));
  const out = spreadByCompany(ranked, { cap: 3, window: 10, headOnly: 200 });
  assert.equal(out.length, ranked.length);
  assert.equal(multiset(out), multiset(ranked)); // 一个都没丢、没多
});

test("头部窗口内单公司不超 cap(有别家可换时)", () => {
  // 100 个字节 + 穿插 100 个不同小公司,交替喂入
  const ranked = [];
  for (let i = 0; i < 100; i++) { ranked.push(J("字节跳动", "b" + i)); ranked.push(J("小" + i, "s" + i)); }
  const out = spreadByCompany(ranked, { cap: 3, window: 10, headOnly: 200 });
  // 检查头部每个长度 10 的滑窗里字节 ≤ 3
  for (let k = 0; k + 10 <= 200 && k + 10 <= out.length; k++) {
    const win = out.slice(k, k + 10).filter((j) => j.company === "字节跳动").length;
    assert.ok(win <= 3, `窗口[${k},${k + 10}) 字节=${win} 超过 cap`);
  }
});

test("确定性:同输入同输出", () => {
  const ranked = [];
  for (let i = 0; i < 250; i++) ranked.push(J("c" + (i % 7), i));
  assert.equal(multiset(spreadByCompany(ranked)), multiset(spreadByCompany(ranked)));
  assert.deepEqual(spreadByCompany(ranked).map((j) => j.id), spreadByCompany(ranked).map((j) => j.id));
});

test("尾部(headOnly 之后)原序不动", () => {
  const ranked = [];
  for (let i = 0; i < 300; i++) ranked.push(J("字节跳动", i)); // 全同一家
  const out = spreadByCompany(ranked, { cap: 3, window: 10, headOnly: 200 });
  const tailIn = ranked.slice(200).map((j) => j.id);
  const tailOut = out.slice(out.length - 100).map((j) => j.id);
  assert.deepEqual(tailOut, tailIn); // 尾部 100 条顺序不变
});

test("短结果集(<=window)原样返回", () => {
  const ranked = [J("a", 1), J("a", 2), J("b", 3)];
  assert.deepEqual(spreadByCompany(ranked, { window: 10 }).map((j) => j.id), ["1", "2", "3"]);
});

test("全是一家公司:不死循环,长度守恒", () => {
  const ranked = [];
  for (let i = 0; i < 500; i++) ranked.push(J("独苗", i));
  const out = spreadByCompany(ranked);
  assert.equal(out.length, 500);
});

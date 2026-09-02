const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "..", "hooks", "useJobFilters.ts"), "utf8");

test("岗位搜索把重搜和加载更多分开取消，并把 signal 传给 fetch", () => {
  // 搜索接口会占满单线程候选集扫描；只靠请求号丢弃旧响应，仍会让已经过期的计算在服务端排队。
  // 两个 controller 必须分开，否则用户点「加载更多」会被筛选器的正常重搜误取消。
  assert.match(source, /const searchAbortRef = useRef<AbortController \| null>\(null\)/);
  assert.match(source, /const moreAbortRef = useRef<AbortController \| null>\(null\)/);
  assert.match(source, /const abortRef = more \? moreAbortRef : searchAbortRef/);
  assert.match(source, /abortRef\.current\?\.abort\(\);\s*const controller = new AbortController\(\)/);
  assert.match(source, /\{ signal: controller\.signal \}/);
  assert.match(source, /error instanceof Error && error\.name === "AbortError"/);
});

test("岗位搜索在组件卸载时终止所有在途请求", () => {
  // 卸载后已没有界面可消费结果，继续执行长查询只会占住后端并增加 setState 竞态风险。
  assert.match(source, /searchAbortRef\.current\?\.abort\(\);\s*moreAbortRef\.current\?\.abort\(\);/);
});

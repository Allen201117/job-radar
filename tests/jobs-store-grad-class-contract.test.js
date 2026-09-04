const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "lib", "jobs-store", "write.ts"), "utf8");

test("补正文时只按硬信号补空的届别", () => {
  // 这里是源码契约测试：write.ts 依赖 server-only 和数据库模块，直接加载会引入运行时依赖；
  // 断言 SQL 与抽取调用，覆盖这条不得覆盖已有届别的写入边界。
  const fn = source.match(/export async function updateJobSummaryById[\s\S]*?\n}\n/);
  assert.ok(fn, "找不到 updateJobSummaryById，请重新核对写入契约");
  assert.match(fn[0], /extractGradClass\(\{ summary \}\)/);
  assert.match(fn[0], /grad_class\s*=\s*coalesce\(grad_class, \$3\)/i);
  assert.match(fn[0], /\[summary, id, gradClass\]/);
});

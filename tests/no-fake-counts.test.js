const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const landing = fs.readFileSync(
  path.resolve(__dirname, "../app/landing-client.tsx"),
  "utf8",
);
const login = fs.readFileSync(
  path.resolve(__dirname, "../app/login/page.tsx"),
  "utf8",
);

// 精确匹配「已移除的假数字 / 内部匹配分」原始片段，避免误伤 tailwind class 里的数字。
test("landing-client has no hardcoded business numbers / score", () => {
  assert.ok(!landing.includes('data-count="24"'), 'landing still has data-count="24"');
  assert.ok(!landing.includes('data-count="11"'), 'landing still has data-count="11"');
  assert.ok(!landing.includes('data-count="82"'), 'landing still has data-count="82"');
  assert.ok(!landing.includes("个高匹配待处理"), "landing still has 「N 个高匹配待处理」");
  assert.ok(!landing.includes("匹配分"), "landing still references 匹配分");
});

test("login page has no hardcoded business numbers / score", () => {
  assert.ok(!login.includes(">24</p>"), "login still shows the fake 24 count");
  assert.ok(!login.includes("11 个高匹配待处理"), "login still shows 「11 个高匹配待处理」");
  assert.ok(!login.includes(">82</span>"), "login still shows the fake 82 match score");
});

const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { appendCurrentSeasonWhere } = loadTs(path.join(__dirname, "..", "lib", "campus-season.ts"));
const { currentGradClass } = require("../lib/grad-class");

test("往届门只挡校招/实习，且用当季届别做界", () => {
  const conds = ["status = 'active'"];
  const params = ["前面已有的参数"];
  appendCurrentSeasonWhere(conds, params);

  assert.equal(conds.length, 2);
  const clause = conds[1];
  // 绑定参数必须接在已有参数后面，占位符跟着走——写死 $1 会读到别人的参数。
  assert.equal(params.length, 2);
  assert.equal(params[1], currentGradClass());
  assert.ok(clause.includes("$2"), `占位符要跟着 params 走，实际：${clause}`);
});

// ⚠️ 这三条是这道门的全部正确性，改 SQL 必须让它们继续绿。
test("条件语义：只挡「校招/实习 且 标了届别 且 早于当季」三者同时成立", () => {
  const conds = [];
  appendCurrentSeasonWhere(conds, []);
  const clause = conds[0];

  // ① 作用域限定在校招/实习 —— 实测另有 632 个社招岗正文提到老届别，一并滤掉就是误杀。
  assert.ok(clause.includes("recruitment_category in ('校招','实习')"), clause);
  // ② 未标届别放行（留白 ≠ 隐藏，全库 73% 的校招/实习岗没标届别）。
  assert.ok(clause.includes("grad_class is not null"), clause);
  // ③ 严格早于当季才挡；当季与更晚的届别（提前批）都要放行。
  assert.ok(/grad_class\s*<\s*\$/.test(clause), clause);
  assert.ok(clause.trimStart().startsWith("not ("), clause);
});

test("当季届别口径：5-12 月秋招招次年那届，1-4 月春招补当年那届", () => {
  assert.equal(currentGradClass(new Date("2026-09-04T00:00:00Z")), 2027);
  assert.equal(currentGradClass(new Date("2026-05-01T00:00:00Z")), 2027);
  assert.equal(currentGradClass(new Date("2026-04-30T00:00:00Z")), 2026);
  assert.equal(currentGradClass(new Date("2026-01-15T00:00:00Z")), 2026);
});

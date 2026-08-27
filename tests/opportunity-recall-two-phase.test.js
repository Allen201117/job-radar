// stage-1 两阶段召回（lib/jobs-store/opportunities.ts）的纯函数契约。
// 这些不变量是 live 实测踩出来的，改召回 SQL 前先看 tests 里的注释和 2026-07-31 交接文档。
const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { buildRecallSql, stripTierColumns } = loadTs(
  path.join(__dirname, "..", "lib", "jobs-store", "opportunities.ts"),
);

const baseProfile = {
  userId: "u1",
  jobScope: "domestic",
  targetRegions: [],
  targetRoles: ["产品经理"],
  targetKeywords: [],
  excludeKeywords: [],
  targetLocations: [],
  targetCompanies: [],
  targetIndustries: [],
  skills: [],
  experienceStage: "",
  seniority: null,
  highestEducation: null,
  dailyLimit: 20,
};
const mk = (over) => ({ ...baseProfile, ...over });
const SINCE = "2026-07-24T00:00:00.000Z";

test("有方向/公司/城市时各出一层，层号与权重数组一一对应", () => {
  const built = buildRecallSql(mk({ targetLocations: ["上海"], targetCompanies: ["字节跳动"] }), SINCE, 900);
  assert.deepEqual(built.tiers, ["role", "company", "cityNew"]);
  // 每层一个 `N as _tier`，层号即 tiers 数组下标
  for (let i = 0; i < built.tiers.length; i++) {
    assert.ok(built.sql.includes(`select ${i} as _tier`), `missing tier ${i}`);
  }
  // 权重数组随层数收缩，长度必须与层数一致（否则 [_tier + 1] 取到 null → 排序失效）
  const weights = built.params.find((p) => Array.isArray(p) && p.every((n) => typeof n === "number"));
  assert.equal(weights.length, built.tiers.length);
});

test("用户没填城市 → 不出 cityNew 层，层内排序退回按最新", () => {
  const built = buildRecallSql(mk({}), SINCE, 900);
  assert.deepEqual(built.tiers, ["role"]);
  assert.ok(!built.sql.includes("btrim(location)"), "无城市时不应有城市排序表达式");
});

test("画像连方向/公司/城市都没有 → 返回 null，不发查询", () => {
  assert.equal(buildRecallSql(mk({ targetRoles: [] }), SINCE, 900), null);
});

// 硬拒在 stage-2：location mismatch 直接拒掉（lib/opportunities/eligibility.ts checkEligibility），
// 所以层内必须先取城市命中的行，否则名额都花在必然被拒的岗上。
test("填了城市 → 每层都先按「城市命中 → 城市未知 → 其余」排，再按最新", () => {
  const built = buildRecallSql(mk({ targetLocations: ["上海"], targetCompanies: ["字节跳动"] }), SINCE, 900);
  const cityOrder = /case when search_doc @@ to_tsquery\('simple', \$\d+\) then 0 when location is null or btrim\(location\) = '' then 1 else 2 end/;
  // role 层与 company 层都要有；cityNew 层本身就在城市里，按最新即可
  assert.equal((built.sql.match(new RegExp(cityOrder.source, "g")) || []).length, 4); // 2 层 × (window + order by)
});

// ⚠️ 别把「方向×城市」拆成单独一层：那条词库扩展后的方向 tsquery 是最贵的东西，
// 拆开等于让 GIN 扫它两遍（live 实测某画像 3.3s → 6.0s）。整条 SQL 只能出现一次方向层。
test("方向 tsquery 在整条 SQL 里只被扫一次（不许拆成 role + roleCity 两层）", () => {
  const built = buildRecallSql(mk({ targetLocations: ["上海"] }), SINCE, 900);
  const roleParamIndex = built.params.findIndex((p) => typeof p === "string" && p.includes("产品"));
  const roleRef = `to_tsquery('simple', $${roleParamIndex + 1})`;
  const occurrences = built.sql.split(roleRef).length - 1;
  assert.equal(occurrences, 1, "方向查询出现次数必须为 1（出现在 role 层的 where）");
});

// 关键词多的画像会把扩展后的 tsquery 撑到几百个子句，GIN 扫描随之从 0.1s 涨到 3.5s
// （真实画像实测：29 个关键词 → 240 子句 → 召回 3.3s→4.1s）。
const HEAVY_KEYWORDS = [
  "SQL", "Python", "数据分析", "AI", "产品经理", "算法", "机器学习", "运营", "增长",
  "前端", "后端", "测试", "设计", "财务", "法务", "供应链", "市场", "品牌", "销售",
  "客服", "人力资源", "风控", "推荐系统", "大模型", "数据仓库", "可视化", "项目管理",
  "商业分析", "用户研究", "内容运营",
];
const clausesOf = (ts) => ts.replace(/^\(|\)$/g, "").split(" | ");

test("方向 tsquery 子句去重（多个关键词常映射到同一个词库组）", () => {
  const built = buildRecallSql(mk({ targetKeywords: HEAVY_KEYWORDS.slice(0, 10) }), SINCE, 900);
  const ts = built.params.find((p) => typeof p === "string" && p.includes("|"));
  const clauses = clausesOf(ts);
  assert.equal(new Set(clauses).size, clauses.length, "tsquery 里出现了重复子句");
});

test("方向 tsquery 子句数封顶，超预算的原词仍然进查询（只是不再展开词库）", () => {
  // 末尾这个词不属于任何词库组：它只可能以「原词 bigram」的形式出现，
  // 用来证明超出扩展预算的词没有被丢掉。
  const built = buildRecallSql(
    mk({ targetKeywords: [...HEAVY_KEYWORDS, "水泥搅拌"] }),
    SINCE,
    900,
  );
  const ts = built.params.find((p) => typeof p === "string" && p.includes("|"));
  const clauses = clausesOf(ts);
  assert.ok(clauses.length <= 200, `子句数 ${clauses.length} 超出上限 200`);
  assert.ok(
    clauses.some((c) => c.includes("水泥") && c.includes("搅拌")),
    "超出扩展预算的用户原词被整个丢掉了",
  );
});

test("已处理过的岗下推到 SQL 排除，且封顶 500 个 id", () => {
  const ids = Array.from({ length: 900 }, (_, i) => `id-${i}`);
  const built = buildRecallSql(mk({}), SINCE, 900, ids);
  assert.match(built.sql, /id <> all\(\$\d+::uuid\[\]\)/);
  const passed = built.params.find((p) => Array.isArray(p) && typeof p[0] === "string" && p[0].startsWith("id-"));
  assert.equal(passed.length, 500);
});

test("没有已处理岗时不加排除条件（不发空数组给 SQL）", () => {
  const built = buildRecallSql(mk({}), SINCE, 900, []);
  assert.ok(!built.sql.includes("uuid[]"));
});

test("校招预筛同时覆盖届别标题与既有校招关键词", () => {
  const grad = buildRecallSql(mk({ experienceStage: "校招" }), SINCE, 900);
  const stagePatterns = grad.params.find((p) => Array.isArray(p) && p.includes("%校招%"));
  assert.ok(stagePatterns.includes("%届%"), "-27届 类标题必须在 SQL 预筛通过");
  assert.ok("工艺工程师-27届".includes("届"), "届别标题样例应命中新增 SQL 模式");
  for (const pattern of ["%校招%", "%应届%", "%campus%"]) {
    assert.ok(stagePatterns.includes(pattern), `既有 ${pattern} 召回不得收紧`);
  }
});

test("排除词仍在 SQL 里比对完整 summary（不能挪到 JS：召回行只有 300 字）", () => {
  const built = buildRecallSql(mk({ excludeKeywords: ["外包"] }), SINCE, 900);
  assert.match(built.sql, /not \(lower\(concat_ws\(' ', title, company, location, job_type, summary, salary_text\)\)/);
  assert.ok(built.params.some((p) => Array.isArray(p) && p.includes("%外包%")));
});

test("stripTierColumns 去掉辅助列、按 id 去重、保留 SQL 给的顺序", () => {
  const rows = [
    { _tier: 0, _rn: 1, id: "a", title: "A" },
    { _tier: 2, _rn: 1, id: "b", title: "B" },
    { _tier: 1, _rn: 1, id: "a", title: "A(dup)" }, // 层间重叠：同一岗被两层召回
  ];
  const out = stripTierColumns(rows);
  assert.deepEqual(out, [
    { id: "a", title: "A" },
    { id: "b", title: "B" },
  ]);
});

test("stripTierColumns 容忍空输入与无 id 的脏行", () => {
  assert.deepEqual(stripTierColumns(null), []);
  assert.deepEqual(stripTierColumns([null, { _tier: 0 }, { id: "x" }]), [{ id: "x" }]);
});

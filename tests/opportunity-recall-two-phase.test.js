// stage-1 两阶段召回（lib/jobs-store/opportunities.ts）的纯函数契约。
// 这些不变量是 live 实测踩出来的，改召回 SQL 前先看 tests 里的注释和 2026-07-31 交接文档。
const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { RECALL_BUDGET, buildRecallSql, stripTierColumns } = loadTs(
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
  assert.deepEqual(built.tiers, ["role", "company", "cityNew", "function"]);
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
  assert.deepEqual(built.tiers, ["role", "function"]);
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
  // role/company/cityNew 三层按城市桶排序（function 层的城市门在 where 里用 location ilike，不逐行算 tsquery）；
  // 每层在 window 与子查询 order by 各出现一次。
  assert.equal((built.sql.match(new RegExp(cityOrder.source, "g")) || []).length, 6);
});

// companyHit 只豁免行业门，方向不符仍会被 checkEligibility 的 role_mismatch 拒掉；
// cityNew 也可能捞到仅因城市命中、方向不符的岗位。因此这两层必须先把方向命中顶上来。
test("公司层与城市新增层先排方向命中，避免名额被必然 role_mismatch 的岗位占用", () => {
  const built = buildRecallSql(mk({ targetLocations: ["上海"], targetCompanies: ["字节跳动"] }), SINCE, 900);
  const roleParamIndex = built.params.findIndex((p) => typeof p === "string" && p.includes("产品"));
  const roleRef = `search_doc @@ to_tsquery('simple', $${roleParamIndex + 1})`;
  const directionFirst = new RegExp(`case when ${roleRef.replace(/[()$]/g, "\\$&")} then 0 else 1 end`, "g");
  // company 与 cityNew 各在 row_number + 子查询 order by 出现一次。
  assert.equal((built.sql.match(directionFirst) || []).length, 4);
});

// 海外/都要画像的城市词匹配不到国内 location；若沿用「城市 → 空城市 → 其他」，
// US/SG/Remote 岗会被压到最后。目标地区必须成为最高优先级。
test("含海外范围时先排目标地区，再排目标城市，城市未知不再单列优先级", () => {
  const built = buildRecallSql(
    mk({ jobScope: "all", targetRegions: ["US"], targetLocations: ["上海"], targetCompanies: ["字节跳动"] }),
    SINCE,
    900,
  );
  const regionParamIndex = built.params.findIndex((p) => Array.isArray(p) && p.length === 1 && p[0] === "US");
  assert.notEqual(regionParamIndex, -1, "目标地区必须作为 SQL 排序参数传入");
  const cityParamIndex = built.params.findIndex((p) => typeof p === "string" && p.includes("上海"));
  const regionThenCity = new RegExp(
    `case when \\(job_scope = 'overseas' and \\(country_code = any\\(\\$${regionParamIndex + 1}::text\\[\\]\\)\\)\\) then 0 when search_doc @@ to_tsquery\\('simple', \\$${cityParamIndex + 1}\\) then 1 else 2 end`,
    "g",
  );
  assert.equal((built.sql.match(regionThenCity) || []).length, 6);
  assert.ok(!built.sql.includes("when location is null or btrim(location) = '' then 1"));
});

test("Today 默认召回预算为 1800 条", () => {
  assert.equal(RECALL_BUDGET, 1800);
});

// ⚠️ 别把「方向×城市」拆成单独一层：那条词库扩展后的方向 tsquery 是最贵的东西，
// 拆开等于让 GIN 扫它两遍（live 实测某画像 3.3s → 6.0s）。公司/cityNew 的 order by 可逐行
// 判断方向，但方向 tsquery 只能作为一个层的 where 条件，不能新增第二个 GIN 召回层。
test("方向 tsquery 只作为 role 层 where 条件出现（不许拆成 role + roleCity 两层）", () => {
  const built = buildRecallSql(mk({ targetLocations: ["上海"] }), SINCE, 900);
  const roleParamIndex = built.params.findIndex((p) => typeof p === "string" && p.includes("产品"));
  const roleRef = `search_doc @@ to_tsquery('simple', $${roleParamIndex + 1})`;
  // 逐个子查询看 where 段（from jobs where … order by）里有没有方向 tsquery；function 层只在 order by 里
  // 逐行判它（不新增 GIN 扫描），where 里含它的必须恰好是 role 层这一个。
  const whereSegments = built.sql.split("from jobs where").slice(1).map((seg) => seg.split(" order by")[0]);
  const withRole = whereSegments.filter((seg) => seg.includes(roleRef));
  assert.equal(withRole.length, 1, "方向查询只能有一个 where（role 层的 GIN 扫描）");
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

// 顶层子句拆分：方向 tsquery 现在是 AND-of-ORs（`(A|B) & (C|D)` 之间再 OR），
// 不能像旧的扁平结构那样直接 split(" | ")——那会拆进 OR 组内部，把「不同 AND 单元里
// 复用同一个词」误当成重复子句。按括号深度只在 depth 0 处切。
function topLevelClauses(ts) {
  const body = ts.replace(/^\(|\)$/g, "");
  const out = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (ch === "(") depth++;
    else if (ch === ")") depth--;
    else if (depth === 0 && body.startsWith(" | ", i)) {
      out.push(body.slice(start, i));
      i += 2;
      start = i + 1;
    }
  }
  out.push(body.slice(start));
  return out.map((s) => s.trim()).filter(Boolean);
}

// ⚠️ 下面三条的语料从 targetKeywords 挪到了 targetRoles（2026-09-02）：召回的方向词自此
// **只取 targetRoles**，填了目标岗位就不再掺 targetKeywords（技能/补充词到 stage-2 的方向门
// 必然被 role_mismatch 拒掉，留在召回里只会白扫 GIN）。这三条考的是「方向 tsquery 自身的
// 去重 / 预算 / 保原词」性质，与词从哪个字段来无关，所以只换语料、断言原样保留。
test("方向 tsquery 子句去重（多个方向词常映射到同一个词库组）", () => {
  const built = buildRecallSql(mk({ targetRoles: HEAVY_KEYWORDS.slice(0, 10) }), SINCE, 900);
  const ts = built.params.find((p) => typeof p === "string" && p.includes("|"));
  const clauses = topLevelClauses(ts);
  assert.equal(new Set(clauses).size, clauses.length, "tsquery 里出现了重复子句");
});

test("映射到同一词库组的多个方向词只贡献一条子句（SQL / Python / 数据分析）", () => {
  // 去重的实际收益：这三个词都落在「数据分析」组，展开后是同一组 OR，
  // 不去重就会让 GIN 把同一组词扫三遍。
  const built = buildRecallSql(mk({ targetRoles: ["SQL", "Python", "数据分析"] }), SINCE, 900);
  const ts = built.params.find((p) => typeof p === "string" && p.includes("|"));
  assert.equal(ts.split("(sql)").length - 1, 1, "同一个词库组在 tsquery 里出现了不止一次");
});

test("方向 tsquery 子句数封顶，超预算的原词仍然进查询（只是不再展开词库）", () => {
  // 末尾这个词不属于任何词库组：它只可能以「原词 bigram」的形式出现，
  // 用来证明超出扩展预算的词没有被丢掉。
  const built = buildRecallSql(
    mk({ targetRoles: [...HEAVY_KEYWORDS, "水泥搅拌"] }),
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


// ── 2026-09-17：function 层 / 标题优先 / 国内城市门 ────────────────────────────────
test("function 层：目标职能判得出才出层，参数是 userTargetFunctions 的职能名，只按最新排", () => {
  const built = buildRecallSql(mk({ targetLocations: ["上海"] }), SINCE, 900);
  assert.ok(built.tiers.includes("function"));
  const fns = built.params.find((p) => Array.isArray(p) && p.includes("产品"));
  assert.ok(fns, "function 层应把目标职能数组作为参数传入");
  const fnSeg = built.sql.split("from jobs where")[built.tiers.indexOf("function") + 1];
  assert.match(fnSeg, /job_function = any\(\$\d+::text\[\]\)/);
  // where = 职能等值 AND 城市 GIN（BitmapAnd 两个索引），没有 `or location is null`（那会让 GIN 用不上、逐行算 tsquery 3 秒）
  const cityParamIndex = built.params.findIndex((p) => typeof p === "string" && p.includes("上海"));
  const fnWhere = fnSeg.split(" order by")[0];
  assert.ok(fnWhere.includes(`search_doc @@ to_tsquery('simple', $${cityParamIndex + 1})`), "function 层 where 应带城市 tsquery");
  assert.ok(!fnWhere.includes("or location is null"), "function 层的城市条件不能带 or location is null");
  assert.ok(!fnWhere.includes("location ilike"), "function 层不用 location ilike（整桶逐行过滤 2 秒）");
  // 只按最新排、不加 case：与方向层重叠的行靠 JS 去重
  assert.match(fnSeg, /order by first_seen_at desc limit/);
  assert.ok(!fnSeg.includes("case when"), "function 层不加任何 case 排序表达式");
});

test("function 层：目标岗位判不出职能（纯领域词）→ 不出 function 层", () => {
  const built = buildRecallSql(mk({ targetRoles: ["AI Agent"] }), SINCE, 900);
  assert.ok(!built.tiers.includes("function"));
});

test("function 层：没填城市用 30 天窗兜扫描范围；填了城市走城市 GIN，不带窗；海外范围不出这一层", () => {
  const noCity = buildRecallSql(mk({}), SINCE, 900);
  assert.ok(noCity.sql.includes("first_seen_at >= now() - interval '30 days'"));
  // 有城市时靠城市 GIN 与职能索引 BitmapAnd 收窄，不需要时间窗
  const withCity = buildRecallSql(mk({ targetLocations: ["上海"] }), SINCE, 900);
  const fnSeg = withCity.sql.split("from jobs where")[withCity.tiers.indexOf("function") + 1];
  assert.ok(!fnSeg.includes("interval '30 days'"));
  const overseas = buildRecallSql(mk({ jobScope: "all", targetRegions: ["US"] }), SINCE, 900);
  assert.ok(!overseas.tiers.includes("function"));
});

test("标题优先：用户原词在标题里的行排在城市桶之后、最新之前；参数传原词不带 %", () => {
  const built = buildRecallSql(mk({ targetRoles: ["机械工程师"], targetLocations: ["上海"] }), SINCE, 900);
  const raw = built.params.find((p) => Array.isArray(p) && p.includes("机械工程师"));
  assert.ok(raw, "标题优先应把原词数组作为参数传入");
  assert.ok(raw.every((x) => !x.includes("%")), "原词参数不得带 % —— 阶段谓词哨兵按 % 识别 like 组");
  const roleSeg = built.sql.split("from jobs where")[1].split(" limit ")[0];
  const orderPart = roleSeg.slice(roleSeg.lastIndexOf(" order by "));
  const cityAt = orderPart.indexOf("when location is null or btrim(location) = '' then 1 else 2 end");
  const titleAt = orderPart.indexOf("case when title ilike any(array(select '%' || r || '%' from unnest(");
  const freshAt = orderPart.lastIndexOf("first_seen_at desc");
  assert.ok(cityAt >= 0 && titleAt > cityAt && freshAt > titleAt, `role 层排序应为 城市桶 → 标题命中 → 最新，实际：${orderPart}`);
});

test("国内画像填了城市 → role/company/function 层 where 直接收窄到「城市命中或城市未知」", () => {
  const built = buildRecallSql(mk({ targetLocations: ["上海"], targetCompanies: ["字节跳动"] }), SINCE, 900);
  const cityParamIndex = built.params.findIndex((p) => typeof p === "string" && p.includes("上海"));
  const gate = `(search_doc @@ to_tsquery('simple', $${cityParamIndex + 1}) or location is null or btrim(location) = '')`;
  const whereSegments = built.sql.split("from jobs where").slice(1).map((seg) => seg.split(" order by")[0]);
  // role / company 两层带「城市命中或城市未知」门；cityNew 本就含城市条件；function 层只带纯城市 tsquery（要 BitmapAnd）
  assert.equal(whereSegments.filter((seg) => seg.includes(gate)).length, 2);
  // 海外范围不加门（目标地区在排序里判）
  const overseas = buildRecallSql(mk({ jobScope: "all", targetRegions: ["US"], targetLocations: ["上海"] }), SINCE, 900);
  assert.ok(!overseas.sql.includes("or location is null or btrim(location) = '')"));
});

test("城市词带归一名：「深圳市」也要能命中 location 只写「深圳」的岗（SQL 门必须是 JS locationState 的超集）", () => {
  const built = buildRecallSql(mk({ targetLocations: ["深圳市"] }), SINCE, 900);
  const cityTs = built.params.find((p) => typeof p === "string" && p.includes("深圳"));
  assert.ok(cityTs.includes("|"), `城市 tsquery 应 OR 上归一名：${cityTs}`);
});

test("stripTierColumns：只被 function 层捞到的岗打 recall_function_only，方向层也命中的不打", () => {
  const tiers = ["role", "cityNew", "function"];
  const rows = [
    { id: "a", _tier: 0, _rn: 1 },            // 方向层
    { id: "b", _tier: 2, _rn: 1 },            // 只在职能层
    { id: "c", _tier: 2, _rn: 2 },            // 职能层先出现……
    { id: "c", _tier: 1, _rn: 5 },            // ……但城市层也有它 → 不算 function-only
  ];
  const out = stripTierColumns(rows, tiers);
  const byId = Object.fromEntries(out.map((j) => [j.id, j]));
  assert.equal(byId.a.recall_function_only, undefined);
  assert.equal(byId.b.recall_function_only, true);
  assert.equal(byId.c.recall_function_only, undefined);
  assert.equal("_tier" in byId.b, false);
  // 不传 tiers（旧调用方）→ 行为不变，谁都不打标
  assert.equal(stripTierColumns(rows)[1].recall_function_only, undefined);
});

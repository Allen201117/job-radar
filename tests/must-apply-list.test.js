const assert = require("node:assert/strict");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const json = require("../lib/must-apply-list.json");
const overseasJson = require("../lib/must-apply-list-overseas.json");
const { INDUSTRY_CATEGORIES, canonicalizeUserIndustry } = require("../lib/company-industry.js");
const M = loadTs(path.join(__dirname, "..", "lib", "must-apply-list.ts"));
const R = loadTs(path.join(__dirname, "..", "lib", "ilike-matcher.ts"));

test("ilikeMatcher matches SQL ILIKE wildcards without changing literal matching", () => {
  assert.equal(R.ilikeMatcher("%字节%")("北京字节跳动有限公司"), true);
  assert.equal(R.ilikeMatcher("%BYTE%")("ByteDance"), true);
  assert.equal(R.ilikeMatcher("%字节%")("腾讯"), false);
  assert.equal(R.ilikeMatcher("%字节%")("ByteDance"), false);
  assert.equal(R.ilikeMatcher("甲_公司")("甲乙公司"), true);
  assert.equal(R.ilikeMatcher("甲%公司")("甲科技有限公司"), true);
  assert.equal(R.ilikeMatcher("甲%公司")("乙公司"), false);
  assert.equal(R.ilikeMatcher("%国家电网%")("国网江苏省电力有限公司（国家电网）"), true);
});

test("must-apply JSON follows the canonical industry taxonomy and preserves the north-star list", () => {
  const industries = Object.keys(json).filter((key) => !key.startsWith("_"));
  assert.equal(json._version, "2026Q3-v2");
  assert.deepEqual(industries, INDUSTRY_CATEGORIES);
  // 每个行业的必投目标是 30 家；移出口径的必须在 `_removed` 里留记录（原因 / 证据 / 核实日期），
  // 同一家公司重复占名额的，并入另一行时在 `_merged` 里留记录。
  // 所以「现有家数 + 该行业移出 / 并入家数 = 30」。移出了却不留记录，这里就红（2026-09-23 移出 17 家、并入 1 家时立）。
  const removedByIndustry = {};
  for (const bucket of [json._removed || {}, json._merged || {}]) {
    for (const [name, record] of Object.entries(bucket)) {
      if (name.startsWith("_")) continue;
      removedByIndustry[record.industry] = (removedByIndustry[record.industry] || 0) + 1;
    }
  }
  for (const [industry, companies] of Object.entries(json).filter(([key]) => !key.startsWith("_"))) {
    const expected = 30 - (removedByIndustry[industry] || 0);
    assert.equal(companies.length, expected, `${industry}: ${companies.length} 家 + 移出/并入 ${removedByIndustry[industry] || 0} 家应为 30`);
    assert.equal(new Set(companies.map((company) => company.name)).size, expected, `${industry} names must be unique`);
    assert.equal(new Set(companies.map((company) => company.pattern)).size, expected, `${industry} patterns must be unique`);
    for (const company of companies) {
      assert.equal(typeof company.name, "string");
      assert.ok(company.name.trim());
      assert.match(company.pattern, /^%[^%]+%$/);
    }
  }
  assert.equal(json["互联网/科技"][0].name, "字节跳动");
});

test("overseas must-apply JSON follows the domestic industry taxonomy and keeps each industry distinct", () => {
  assert.deepEqual(Object.keys(overseasJson), Object.keys(json).filter((key) => !key.startsWith("_")));
  for (const [industry, companies] of Object.entries(overseasJson)) {
    assert.equal(companies.length, 30, `${industry} must have 30 overseas companies`);
    assert.equal(new Set(companies.map((company) => company.name)).size, 30, `${industry} names must be unique`);
    assert.equal(new Set(companies.map((company) => company.pattern)).size, 30, `${industry} patterns must be unique`);
    // 两种合法形态：%子串%（常规），或无通配的精确匹配（UPS/2U 这类短名：%UPS% 会误吞
    // Groups/Startups 等含子串的公司，ILIKE 无通配即等值匹配，专治「名字太短放宽必误伤」）。
    for (const company of companies) assert.match(company.pattern, /^(%[^%]+%|[^%]+)$/);
  }
});

test("must-apply TypeScript API unions patterns, finds all industries, and resolves user industries", () => {
  assert.deepEqual(M.MUST_APPLY_INDUSTRIES, Object.keys(json).filter((key) => !key.startsWith("_")));
  assert.equal(M.MUST_APPLY_VERSION, "2026Q3-v2");
  assert.deepEqual(M.MUST_APPLY_LIST, json["互联网/科技"]);
  const union = M.mustApplyUnion();
  assert.equal(new Set(union.map((company) => company.pattern)).size, union.length);
  assert.deepEqual(M.industriesForPattern("%贝壳%"), ["互联网/科技", "地产/建筑"]);
  assert.deepEqual(M.resolveMustApplyIndustries(["金融科技"]), [canonicalizeUserIndustry("金融科技")]);
  assert.deepEqual(M.resolveMustApplyIndustries([]), ["互联网/科技"]);
  assert.deepEqual(M.resolveMustApplyIndustries(null), ["互联网/科技"]);
  assert.deepEqual(M.resolveMustApplyIndustries(["不存在行业xyz"]), ["互联网/科技"]);
});

test("must-apply scope APIs select overseas data without changing domestic defaults", () => {
  assert.deepEqual(M.mustApplyByIndustry("domestic"), Object.fromEntries(
    Object.entries(json).filter(([key]) => !key.startsWith("_")),
  ));
  assert.deepEqual(M.mustApplyByIndustry("overseas"), overseasJson);
  assert.deepEqual(M.mustApplyUnion("overseas").slice(0, 2), overseasJson["互联网/科技"].slice(0, 2));
  assert.deepEqual(M.industriesForPattern("%Google%", "overseas"), ["互联网/科技"]);
  assert.deepEqual(M.industriesForPattern("%Google%"), []);
  assert.deepEqual(M.resolveMustApplyScopes("overseas"), ["overseas"]);
  assert.deepEqual(M.resolveMustApplyScopes("all"), ["domestic", "overseas"]);
  assert.deepEqual(M.resolveMustApplyScopes("domestic"), ["domestic"]);
  assert.deepEqual(M.resolveMustApplyScopes(null), ["domestic"]);
});

test("only the four approved sub-brands expose parent portal rollup metadata", () => {
  const entries = Object.values(json)
    .filter(Array.isArray)
    .flat()
    .filter((entry) => entry.parentPattern || entry.brandTokens);
  assert.deepEqual(
    entries.map((entry) => [entry.name, entry.parentPattern, entry.brandTokens]),
    [
      ["网商银行", "%蚂蚁%", ["网商"]],
      ["极氪", "%吉利%", ["极氪"]],
      ["京东物流", "%京东%", ["京东物流"]],
      ["网易云音乐", "%网易%", ["云音乐"]],
    ],
  );
  assert.equal(M.mustApplyUnion().filter((entry) => entry.parentPattern).length, 4);
});

// ============================================================
// 2026-09-04 门禁：别名（aliases）——同一家公司在库里的其它写法。
//
// 立这道门的原因：壳牌在库里记的是英文 `Shell`，缺口普查拿中文「壳牌」去匹配
// sources.company 匹配不上 → 判「零源缺口」→ 插了第二条源 → 与已有源是同一个
// Workday 站点仅大小写不同 → 大小写带进 jd_url、canonical 区分大小写、唯一索引拦不住
// → 同一个岗在库里存了两行（迁移 225 已修）。
// **「有岗但指标显示 0」比「真没岗」更危险：它会驱动人去重复补源。**
// ============================================================

const ALIAS_PATTERN_SHAPE = /^(%[^%]+%|[^%]+)$/;

test("aliases 与 pattern 同语义（ILIKE 模式），且不与自身 pattern 重复", () => {
  for (const [label, list] of [["国内", json], ["海外", overseasJson]]) {
    for (const [industry, companies] of Object.entries(list).filter(([k]) => !k.startsWith("_"))) {
      for (const company of companies) {
        if (company.aliases === undefined) continue;
        assert.ok(Array.isArray(company.aliases) && company.aliases.length,
          `${label}/${industry}/${company.name}: aliases 要么不写，要么是非空数组`);
        for (const alias of company.aliases) {
          assert.match(alias, ALIAS_PATTERN_SHAPE, `${label}/${company.name} 的别名 ${alias} 形状非法`);
          assert.notEqual(alias, company.pattern, `${label}/${company.name} 的别名与 pattern 重复`);
        }
        assert.equal(new Set(company.aliases).size, company.aliases.length,
          `${label}/${company.name} 的别名有重复`);
      }
    }
  }
});

test("别名不得命中同一清单里的另一家公司（张冠李戴门）", () => {
  for (const [label, list] of [["国内", json], ["海外", overseasJson]]) {
    const entries = Object.entries(list).filter(([k]) => !k.startsWith("_")).flatMap(([, v]) => v);
    const conflicts = [];
    for (const company of entries) {
      for (const alias of company.aliases || []) {
        const matches = R.ilikeMatcher(alias);
        for (const other of entries) {
          if (other.name === company.name) continue;
          // 不只比「别名 == 别人的 pattern」，还要按**子串**互查别人的名字与别名：
          // 短别名是最容易误伤的形态（CLAUDE.md 立过碑的 `%京东%` 会吃掉京东方 BOE）。
          const hits = [other.name, other.pattern, ...(other.aliases || [])]
            .filter((token) => matches(String(token).replace(/%/g, "")));
          if (hits.length) {
            conflicts.push(`${label}：${company.name} 的别名 ${alias} 撞上了 ${other.name}（${hits.join("/")}）`);
          }
        }
      }
    }
    assert.deepEqual(conflicts, [], conflicts.join("\n"));
  }
});

// pattern 本身也会张冠李戴，而上面那道门只查别名。这里钉死一个 live 实测过的真实碰撞。
test("中国电建的 pattern 不得吃掉中国能建的「火电建设」子公司", () => {
  const entries = Object.entries(json).filter(([k]) => !k.startsWith("_")).flatMap(([, v]) => v);
  const dianjian = entries.find((e) => e.name === "中国电建");
  const matches = M.mustApplyPatterns(dianjian).map((p) => R.ilikeMatcher(p));
  const hit = (name) => matches.some((m) => m(name));
  // ❌ 旧 pattern `%电建%` 命中「火**电建**设」：2026-09-17 香港库全量实测，
  //    139 个 ilike '%电建%' 的在招岗里 41 个是中国能建的（湖南/浙江火电建设），
  //    而 98 个真中国电建的岗**全部**含「中国电建」四个字 —— 收紧后
  //    去掉 41 个错算、真岗一个不少（反方向为 0，不是抽样，是扫全集）。
  assert.equal(hit("中国能源建设集团湖南火电建设有限公司（中国能建）"), false);
  assert.equal(hit("中国电建集团华东勘测设计研究院有限公司"), true);
});

test("mustApplyPatterns = pattern + 别名，无别名时行为不变", () => {
  assert.deepEqual(M.mustApplyPatterns({ pattern: "%甲%" }), ["%甲%"]);
  assert.deepEqual(M.mustApplyPatterns({ pattern: "%甲%", aliases: [] }), ["%甲%"]);
  assert.deepEqual(M.mustApplyPatterns({ pattern: "%壳牌%", aliases: ["%Shell%"] }), ["%壳牌%", "%Shell%"]);
  // 空白/重复项不该污染匹配集
  assert.deepEqual(M.mustApplyPatterns({ pattern: "%甲%", aliases: [" ", "%甲%", "%A%"] }), ["%甲%", "%A%"]);
});

// 2026-09-23：移出口径的公司不许「删得无影无踪」——每条都要能说清为什么移、凭什么、以后怎么捞回。
test("_removed 记录齐全，且被移出的公司不再出现在任何行业里", () => {
  const removed = Object.entries(json._removed || {}).filter(([name]) => !name.startsWith("_"));
  assert.equal(removed.length, 17);
  const active = Object.entries(json).filter(([k]) => !k.startsWith("_")).flatMap(([, v]) => v);
  const activeNames = new Set(active.map((c) => c.name));
  const activePatterns = new Set(active.map((c) => c.pattern));
  for (const [name, r] of removed) {
    for (const field of ["industry", "pattern", "reason", "evidence", "how_to_restore", "verified_at", "decision"]) {
      assert.ok(typeof r[field] === "string" && r[field].trim(), `${name}.${field} 不能为空`);
    }
    assert.ok(INDUSTRY_CATEGORIES.includes(r.industry), `${name}: 行业 ${r.industry} 不存在`);
    assert.match(r.verified_at, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(!activeNames.has(name), `${name} 已移出却仍在清单里`);
    assert.ok(!activePatterns.has(r.pattern), `${name} 的 pattern 仍在清单里`);
  }
});

test("_merged：万达电影并进儒意影业（同一家公司改名后在清单里占了两个名额，不是删掉一家）", () => {
  const merged = json._merged["万达电影"];
  const media = json["传媒/文娱"];
  assert.ok(!media.some((c) => c.name === "万达电影"));
  const target = media.find((c) => c.name === merged.merged_into);
  assert.ok(target, "并入的那一家必须还在原行业里");
  assert.equal(target.pattern, "%儒意%");
  assert.equal(target.aliases, undefined, "库里没有叫「万达电影」的岗/源，不加别名（别名须逐条有据）");
  for (const field of ["industry", "pattern", "evidence", "verified_at", "decision"]) {
    assert.ok(typeof merged[field] === "string" && merged[field].trim(), `万达电影.${field} 不能为空`);
  }
});

test("元数据键不会漏进读取方：TS 与 Python 两侧都只读行业数组", () => {
  assert.deepEqual(M.MUST_APPLY_INDUSTRIES, INDUSTRY_CATEGORIES);
  assert.equal(M.MUST_APPLY_VERSION, "2026Q3-v2");
  const names = M.mustApplyUnion().map((c) => c.name);
  assert.ok(!names.includes("思考乐") && !names.includes("万达电影") && names.includes("儒意影业"));
  const py = execFileSync("python3", ["-c", [
    "import json, sys",
    `sys.path.insert(0, ${JSON.stringify(path.join(__dirname, "..", "crawler"))})`,
    "import must_apply",
    "names = must_apply.all_names()",
    "print(json.dumps({'version': must_apply.version(), 'n': len(must_apply.patterns()),",
    "  'industries': list(must_apply.by_industry().keys()), 'si': '思考乐' in names, 'wanda': '万达电影' in names}, ensure_ascii=False))",
  ].join("\n")], { encoding: "utf8" });
  const got = JSON.parse(py);
  assert.equal(got.version, "2026Q3-v2");
  assert.deepEqual(got.industries, INDUSTRY_CATEGORIES);
  assert.equal(got.n, new Set(M.mustApplyUnion().flatMap((c) => M.mustApplyPatterns(c))).size);
  assert.equal(got.si, false);
  assert.equal(got.wanda, false);
});

// 别名是**口径**：加一条就等于改北极星与缺口台账的判定，必须逐条有据（库里真有这个名字）。
// 所以这里把当前全量别名钉死，改动会红——红了就去 commit message 里写清「库里哪一行叫这个名字」。
test("当前别名清单逐条钉死（国内：库里记的是英文名）", () => {
  const rows = Object.entries(json).filter(([k]) => !k.startsWith("_")).flatMap(([, v]) => v)
    .filter((entry) => entry.aliases).map((entry) => [entry.name, entry.aliases]);
  assert.deepEqual(rows, [
    ["大陆集团", ["%Continental%"]],  // sources/jobs 记作 Continental（425 个 active）
    ["拜耳", ["%Bayer%"]],            // jobs 里 Bayer 622 个 + 拜耳 Bayer 76 个
    ["壳牌", ["%Shell%"]],            // 2026-09-04 事故当事人：库里一度记作 Shell
  ]);
});

test("当前别名清单逐条钉死（海外：库里记的是中文名）", () => {
  const rows = Object.entries(overseasJson).filter(([k]) => !k.startsWith("_")).flatMap(([, v]) => v)
    .filter((entry) => entry.aliases).map((entry) => [entry.name, entry.aliases]);
  assert.deepEqual(rows, [
    ["Walmart", ["%沃尔玛%"]],
    ["McDonald's", ["%麦当劳%"]],
    ["Fast Retailing (Uniqlo)", ["%优衣库%"]],
    ["Eaton", ["%伊顿%"]],
    ["Volkswagen", ["%大众汽车%"]],
    ["Mercedes-Benz", ["%奔驰%"]],
    ["General Motors", ["%通用汽车%"]],
    ["Hyundai", ["%现代汽车%"]],
    ["ZF", ["%采埃孚%"]],
    ["Continental", ["%大陆集团%"]],
    ["Merck", ["%默沙东%"]],
    ["Bristol Myers Squibb", ["%百时美施贵宝%"]],
    // 2026-09-17 加：库里那行叫「埃克森美孚 ExxonMobil」（508 个健康 overseas 岗）。
    // 同日 gap_census 的归属改走拉丁词边界后，pattern `%Exxon%` 不再命中 `ExxonMobil`
    // （后面紧跟 `mobil`，不是词尾）——这条别名是把那 508 个岗接回来的补丁，
    // 不是新增口径。词边界本身不能放宽：放宽就等于让 `%ABB%` 重新吃掉 AbbVie（8,530 岗）。
    ["ExxonMobil", ["%埃克森美孚%"]],
    ["Shell", ["%壳牌%"]],
    ["TotalEnergies", ["%道达尔%"]],
    ["BASF", ["%巴斯夫%"]],
    ["Prologis", ["%普洛斯%"]],
    ["CapitaLand", ["%凯德%"]],
    ["J&T Express", ["%极兔%"]],
    ["A.P. Moller", ["%马士基%"]],
    ["Bandai Namco", ["%万代南梦宫%"]],
  ]);
});

// ============================================================
// 2026-09-03 门禁：必投清单的行业分组必须与 company-industry 分类器一致。
//
// 立这道门的原因：清单此前**自己定义了第二套行业归属**，与分类器冲突 20 条 ——
// 宁德时代/蔚来/理想/小鹏/微众银行/蚂蚁/SHEIN 全被塞进「互联网/科技」，
// 用户直接看出来了（「宁德时代不算互联网行业，这是最基本的常识」）。
// 根因不是某个条目写错，是**同一个事实有两个数据源、且没人对账**。
//
// 现行口径：`classifyCompanyIndustry` 是公司→行业的**唯一权威**。
// 清单只负责「这个行业的必投目标是哪 30 家」，不负责判断某家公司属于哪个行业。
// 分类器判不出（null）的公司不拦——那是覆盖度问题，不是矛盾。
// ============================================================

const { classifyCompanyIndustry } = require("../lib/company-industry.js");

// 显式豁免：分类器按「实体本身」判，清单按「求职者会去哪个行业的清单里找它」放。
// 少数公司这两者合理地不同，必须逐条写明理由；不写理由的一律当错处理。
const INDUSTRY_PLACEMENT_EXEMPTIONS = {
  // 京东科技是京东的金融科技板块，求职者在金融清单里找它；分类器按母品牌判互联网。
  京东科技: { listedAs: "金融", classifierSays: "互联网/科技" },
  // SHEIN 是跨境电商平台：分类器按「卖服装」判消费/零售，求职者按「互联网公司」投算法/供应链数字化岗。
  // 与宁德时代那类错放不同——这不是常识错误，是同一实体的两个成立视角。
  SHEIN: { listedAs: "互联网/科技", classifierSays: "消费/零售" },
  // AMD 是芯片设计公司：清单按半导体归制造/工业（与中芯国际/华虹同档），分类器按科技巨头归互联网。
  AMD: { listedAs: "制造/工业", classifierSays: "互联网/科技" },
};

test("必投清单的行业分组不得与 company-industry 分类器冲突", () => {
  const conflicts = [];
  for (const [industry, companies] of Object.entries(json).filter(([k]) => !k.startsWith("_"))) {
    for (const { name } of companies) {
      const got = classifyCompanyIndustry(name);
      if (got === null || got === industry) continue;
      const ex = INDUSTRY_PLACEMENT_EXEMPTIONS[name];
      if (ex && ex.listedAs === industry && ex.classifierSays === got) continue;
      conflicts.push(`${name}：清单放在「${industry}」，分类器判「${got}」`);
    }
  }
  assert.deepEqual(
    conflicts,
    [],
    `清单与分类器冲突 ${conflicts.length} 条 —— 要么公司放错行业清单，要么分类器判错，` +
      `二选一改掉；确属合理差异就写进 INDUSTRY_PLACEMENT_EXEMPTIONS 并注明理由。\n` +
      conflicts.join("\n"),
  );
});

test("海外必投清单同样受行业一致性门禁约束", () => {
  const conflicts = [];
  for (const [industry, companies] of Object.entries(overseasJson).filter(([k]) => !k.startsWith("_"))) {
    for (const { name } of companies || []) {
      const got = classifyCompanyIndustry(name);
      if (got === null || got === industry) continue;
      if (INDUSTRY_PLACEMENT_EXEMPTIONS[name]) continue;
      conflicts.push(`${name}：清单放在「${industry}」，分类器判「${got}」`);
    }
  }
  assert.deepEqual(conflicts, [], `海外清单冲突 ${conflicts.length} 条\n${conflicts.join("\n")}`);
});

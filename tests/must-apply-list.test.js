const assert = require("node:assert/strict");
const path = require("node:path");
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
  assert.equal(json._version, "2026Q3-v1");
  assert.deepEqual(industries, INDUSTRY_CATEGORIES);
  for (const [industry, companies] of Object.entries(json).filter(([key]) => !key.startsWith("_"))) {
    assert.equal(companies.length, 30, `${industry} must have 30 companies`);
    assert.equal(new Set(companies.map((company) => company.name)).size, 30, `${industry} names must be unique`);
    assert.equal(new Set(companies.map((company) => company.pattern)).size, 30, `${industry} patterns must be unique`);
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
  assert.equal(M.MUST_APPLY_VERSION, "2026Q3-v1");
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
          if (matches(other.name) || alias === other.pattern || (other.aliases || []).includes(alias)) {
            conflicts.push(`${label}：${company.name} 的别名 ${alias} 撞上了 ${other.name}`);
          }
        }
      }
    }
    assert.deepEqual(conflicts, [], conflicts.join("\n"));
  }
});

test("mustApplyPatterns = pattern + 别名，无别名时行为不变", () => {
  assert.deepEqual(M.mustApplyPatterns({ pattern: "%甲%" }), ["%甲%"]);
  assert.deepEqual(M.mustApplyPatterns({ pattern: "%甲%", aliases: [] }), ["%甲%"]);
  assert.deepEqual(M.mustApplyPatterns({ pattern: "%壳牌%", aliases: ["%Shell%"] }), ["%壳牌%", "%Shell%"]);
  // 空白/重复项不该污染匹配集
  assert.deepEqual(M.mustApplyPatterns({ pattern: "%甲%", aliases: [" ", "%甲%", "%A%"] }), ["%甲%", "%A%"]);
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

const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

// 必投清单的「独占归属」：一个库里的公司名只归清单里的一家（lib/must-apply-owner.ts）。
//
// 立这份测试的原因（2026-10-11 全集实测，1,725 个在招公司名 × 国内 311 + 海外 327 条清单）：
// 同一份清单曾有三套匹配口径——管理员看板是裸子串、一个名字命中两条清单就各算一遍；缺口台账是
// 「最长者独占 + 英文按整词」；校招专区是「用户所选行业的清单里谁排前面归谁」。
//   · 看板海外 ABB 显示 6,600 个健康岗，实际 4 个（其余是 AbbVie、雅培 Abbott）；
//   · 看板国内京东里混着京东方 1,032 个；校招专区默认行业下「京东」卡混着京东方的校招岗。
// 现在三处用同一份规则，与 crawler/gap_census.resolve_owner 靠共用夹具对齐。
const O = loadTs(path.join(__dirname, "..", "lib", "must-apply-owner.ts"));
const R = loadTs(path.join(__dirname, "..", "lib", "jobs-store", "read.ts"));
const M = loadTs(path.join(__dirname, "..", "lib", "must-apply-list.ts"));
const fixture = require("./fixtures/must-apply-owner-cases.json");
const json = require("../lib/must-apply-list.json");
const overseasJson = require("../lib/must-apply-list-overseas.json");

test("英文模式按整词，中文模式按子串", () => {
  assert.equal(O.tokenInName("abb", "abbvie"), false);
  assert.equal(O.tokenInName("abb", "雅培 abbott"), false);
  assert.equal(O.tokenInName("abb", "abb"), true);
  assert.equal(O.tokenInName("abb", "abb 中国"), true);
  assert.equal(O.tokenInName("imax", "minimax 稀宇科技"), false);
  assert.equal(O.tokenInName("j&t express", "j&t express 极兔"), true);
  assert.equal(O.tokenInName("京东", "京东方 boe"), true); // 中文仍是子串，由「最长者独占」裁决
});

test("与爬虫侧逐条一致：共用夹具里每个名字归到同一家", () => {
  assert.ok(fixture.cases.length >= 100);
  const resolvers = { domestic: O.mustApplyOwnerResolver("domestic"), overseas: O.mustApplyOwnerResolver("overseas") };
  const mismatches = [];
  for (const c of fixture.cases) {
    const got = resolvers[c.scope](c.name);
    if (got !== c.owner) mismatches.push(`${c.scope}：${c.name} → 网站侧「${got}」，夹具「${c.owner}」`);
  }
  assert.deepEqual(mismatches, []);
});

test("最长者独占：京东方不归京东，子品牌不归母品牌，排除的名字不归这家", () => {
  const owner = O.mustApplyOwnerResolver("domestic");
  assert.equal(owner("京东方 BOE"), "京东方");
  assert.equal(owner("京东物流"), "京东物流");
  assert.equal(owner("腾讯音乐 TME"), "腾讯音乐");
  assert.equal(owner("吉利德 Gilead"), "");
  assert.equal(owner("吉利汽车"), "吉利");
  // 被一家排除后，还可以归给别的清单公司
  assert.equal(owner("连云港新东方国际货柜码头有限公司（中远海运集团）"), "中远海运");
  // 「按末尾括号归集团」做不到的反向样例：实体就是蒙牛本身
  assert.equal(owner("内蒙古蒙牛乳业（集团）股份有限公司（中粮集团）"), "蒙牛");
});

test("不在真实清单里的条目（测试 / 临时清单）也能参与归属", () => {
  const owner = O.mustApplyOwnerResolver("domestic", [
    { name: "甲公司", pattern: "%甲乙丙%" },
    { name: "甲公司物流", pattern: "%甲乙丙物流%", excludes: ["%甲乙丙物流园%"] },
  ]);
  assert.equal(owner("甲乙丙集团"), "甲公司");
  assert.equal(owner("甲乙丙物流"), "甲公司物流");
  assert.equal(owner("甲乙丙物流园"), "甲公司");
  assert.equal(owner("京东方 BOE"), "京东方"); // 真实清单的竞争者仍然在场
});

function agg(company, domesticHealthy, overseasHealthy = 0) {
  const counts = (healthy) => ({ activeTotal: healthy, healthy, new7d: 0, checked72h: 0, campusJobs: 0, internJobs: 0, socialJobs: 0 });
  return {
    company,
    ...counts(domesticHealthy + overseasHealthy),
    byScope: { domestic: counts(domesticHealthy), overseas: counts(overseasHealthy) },
  };
}

test("看板覆盖率按独占归属算：不再把别家的岗、也不再把同一批岗算两遍", () => {
  const aggregates = [
    agg("京东", 1159), agg("京东方 BOE", 1032), agg("京东物流", 893), agg("京东科技", 208),
    agg("ABB", 363, 4), agg("AbbVie", 591, 5173), agg("雅培 Abbott", 116, 1423),
    agg("吉利汽车", 2614), agg("吉利德 Gilead", 11, 422),
    agg("宁德时代 CATL", 647), agg("宁德新能源", 203),
    agg("MiniMax 稀宇科技", 192, 5),
  ];
  const domestic = new Map(R.computeMustApplyCoverage(M.mustApplyUnion("domestic"), aggregates, "domestic").map((r) => [r.name, r]));
  assert.equal(domestic.get("京东").healthy, 1159);
  assert.equal(domestic.get("京东方").healthy, 1032);
  assert.equal(domestic.get("京东物流").healthy, 893);
  assert.equal(domestic.get("ABB").healthy, 363);
  assert.equal(domestic.get("吉利").healthy, 2614);
  assert.equal(domestic.get("宁德时代").healthy, 647);
  const overseas = new Map(R.computeMustApplyCoverage(M.mustApplyUnion("overseas"), aggregates, "overseas").map((r) => [r.name, r]));
  assert.equal(overseas.get("ABB").healthy, 4);
  assert.equal(overseas.get("ABB").otherScopeHealthy, 363);
  assert.equal(overseas.get("IMAX").healthy, 0);
  assert.equal(overseas.get("AbbVie").healthy, 5173);
});

// 排除是**口径**：加一条就等于改北极星与缺口台账的判定，必须逐条有据。
// 依据（2026-10-11 香港库在招岗全集，国内健康岗数）写在每条后面；全表见
// docs/reviews/2026-10-11-attribution-gate-and-must-apply-patterns.md §3.2。
test("当前排除清单逐条钉死", () => {
  const rows = Object.entries(json).filter(([k]) => !k.startsWith("_")).flatMap(([, v]) => v)
    .filter((entry) => entry.excludes).map((entry) => [entry.name, entry.excludes]);
  assert.deepEqual(rows, [
    ["泰康保险", ["%国投泰康%"]],                    // 国投泰康信托有限公司（国投集团）8 个，国投的公司
    ["吉利", ["%吉利德%"]],                          // 吉利德 Gilead 11 个（海外另有 422 个），药企
    ["中国石油", ["%中国石油和化学工业联合会%"]],    // 化学工业出版社（…联合会）2 个，行业协会
    ["中国建筑", ["%中建材%", "%中建研%"]],          // 中建材两家 2 个（中国建材）、中建研科技 10 个（中国建研院）
    ["中国中铁", ["%中铁物总%"]],                    // 中铁物总供应链科技集团（中国物流集团）5 个
    ["新东方", ["%新东方国际货柜%"]],                // 连云港新东方国际货柜码头（中远海运集团）6 个
  ]);
  const overseasRows = Object.entries(overseasJson).flatMap(([, v]) => v).filter((entry) => entry.excludes);
  assert.deepEqual(overseasRows, []);
});

test("排除与模式同形，且不会把这家自己的名字排掉", () => {
  for (const [, companies] of Object.entries(json).filter(([k]) => !k.startsWith("_"))) {
    for (const company of companies) {
      if (company.excludes === undefined) continue;
      assert.ok(Array.isArray(company.excludes) && company.excludes.length, `${company.name}: excludes 要么不写，要么是非空数组`);
      for (const exclude of company.excludes) {
        assert.match(exclude, /^%[^%]+%$/, `${company.name} 的排除 ${exclude} 形状非法`);
        const token = exclude.replace(/%/g, "").toLowerCase();
        assert.ok(!O.tokenInName(token, company.name.toLowerCase()), `${company.name} 的排除 ${exclude} 把它自己的名字排掉了`);
      }
    }
  }
});

test("2026-10-11 收窄的三条模式：真名一个不少，别家不再命中", () => {
  const owner = O.mustApplyOwnerResolver("domestic");
  // 改前 `%宁德%` / `%中储%` / `%三峡%`；库里这三家的岗与源只有下面这些真名（全集核过）。
  for (const [name, expected] of [
    ["宁德时代", "宁德时代"], ["宁德时代 CATL", "宁德时代"], ["宁德新能源", ""], ["宁德新能源 ATL 校招", ""],
    ["中储智运", "中储智运"], ["中储恒科物联网系统有限公司（中国物流集团）", ""],
    ["三峡集团", "三峡集团"], ["国投甘肃小三峡发电有限公司（国投集团）", ""],
  ]) {
    assert.equal(owner(name), expected, name);
  }
});

// 两端合并同名条目的写法不同（网站侧与缺口台账取后出现的那条，must_apply.excludes_by_owner 取并集），
// 所以同一家公司出现在多个行业里时，模式 / 别名 / 排除必须逐字相同——否则两端会给出不同的归属。
test("同一家公司出现在多个行业里时，定义必须逐字相同", () => {
  for (const [label, list] of [["国内", json], ["海外", overseasJson]]) {
    const seen = new Map();
    for (const [, companies] of Object.entries(list).filter(([k]) => !k.startsWith("_"))) {
      for (const c of companies) {
        const def = JSON.stringify([c.pattern, c.aliases || [], c.excludes || []]);
        if (seen.has(c.name)) assert.equal(def, seen.get(c.name), `${label}：${c.name} 在两个行业里的定义不一致`);
        else seen.set(c.name, def);
      }
    }
  }
});

// lib/campus-zone.ts 被客户端组件引用（campus-client / campus-all-jobs）。它一旦 import 清单或归属模块，
// 两份清单 JSON 和行业分类器就会被打进 /campus 首屏包——归属函数必须由服务端调用方注入。
test("客户端可达的 campus-zone 不直接引用清单与归属模块", () => {
  const fs = require("node:fs");
  const source = fs.readFileSync(path.join(__dirname, "..", "lib", "campus-zone.ts"), "utf8");
  assert.doesNotMatch(source, /from\s+["'][^"']*must-apply-(owner|list)["']/);
  const read = fs.readFileSync(path.join(__dirname, "..", "lib", "jobs-store", "read.ts"), "utf8");
  assert.match(read, /foldCampusZone\(list, aggregate, rowLevel, mustApplyOwnerPicker\(list\)\)/);
});

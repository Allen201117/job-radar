// /today 目标城市 → 岗位 location 的匹配（2026-09-23）。背景见 lib/opportunities/location-targets.ts。
//
// 守三件事：
//   ① 省目标按省解析：填「陕西」看得到西安 / 榆林的岗，看不到「大连市-中山区」这类裸子串会误判的外省岗；
//   ② 城市目标行为与改前逐字相同（原词或规范名子串）；
//   ③ 召回 SQL 的城市检索词是 stage-2 判中范围的**超集**——漏一个名字，那个市的岗就永远进不了池。
const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("node:path");
const { loadTs, loadOpp } = require("./_load-ts");

const ROOT = path.join(__dirname, "..");
const { provinceOfTarget, resolveLocationTarget, matchLocationTargets, locationTargetSqlTerms } = loadTs(
  path.join(ROOT, "lib", "opportunities", "location-targets.ts"),
);
const { computeMatchFacts } = loadOpp("eligibility");
const { buildRadarProfile } = loadOpp("profile");
const { buildRecallSql } = loadTs(path.join(ROOT, "lib", "jobs-store", "opportunities.ts"));
const geo = require("../lib/geo.js");
const fixture = require("./fixtures/cn-location-provinces.json");

const NOW = new Date("2026-09-23T00:00:00.000Z");
function job(location) {
  return {
    id: "j1", source_id: "s1", company: "示例公司", title: "", location, job_type: null,
    summary: "x".repeat(80), jd_url: "https://e/job/1", apply_url: null, salary_text: null,
    posted_at: null, experience: null, education: null, deadline: null,
    first_seen_at: NOW.toISOString(), last_seen_at: NOW.toISOString(), status: "active",
    content_hash: null, created_at: "",
  };
}
function profile(targetLocations) {
  return {
    userId: "u", jobScope: "domestic", targetRegions: [], targetRoles: ["产品经理"], targetKeywords: [],
    excludeKeywords: [], targetLocations, targetCompanies: [], targetIndustries: [], skills: [],
    experienceStage: "", seniority: null, highestEducation: null, dailyLimit: 20,
  };
}
const facts = (location, targets) =>
  computeMatchFacts(job(location), profile(targets), undefined, { primary: null, viewed: false }, NOW);

test("provinceOfTarget: 省短名 / 全称认省，城市 / 直辖市 / 城市群不认", () => {
  assert.equal(provinceOfTarget("陕西"), "陕西");
  assert.equal(provinceOfTarget("陕西省"), "陕西");
  assert.equal(provinceOfTarget("广西壮族自治区"), "广西");
  assert.equal(provinceOfTarget("新疆维吾尔自治区"), "新疆");
  assert.equal(provinceOfTarget("内蒙古自治区"), "内蒙古");
  for (const t of ["北京", "上海市", "深圳", "长三角", "珠三角", "新加坡", "", "广东省深圳市"]) {
    assert.equal(provinceOfTarget(t), null, t);
  }
});

test("省目标：全省地级市都算，命中原因写省名", () => {
  const f = facts("西安", ["陕西"]);
  assert.equal(f.location, "match");
  assert.equal(f.locationName, "陕西");
  assert.equal(facts("榆林市-神木市", ["陕西省"]).location, "match");
  assert.equal(facts("深圳", ["广东"]).location, "match");
  assert.equal(facts("湖州", ["杭州", "浙江"]).location, "match");
  assert.equal(facts("北京", ["陕西"]).location, "mismatch");
  assert.equal(facts(null, ["陕西"]).location, "unknown");
});

test("省目标：裸子串会误判的外省写法一律不中（反方向）", () => {
  assert.equal(facts("大连市-中山区", ["广东"]).location, "mismatch");
  assert.equal(facts("安徽省·马鞍山市", ["辽宁"]).location, "mismatch");
  assert.equal(facts("黑河-五大连池市", ["辽宁"]).location, "mismatch");
  // 这两条改前是**命中**的（location 字面含省名）——是旧口径的误报，本次一并纠正。
  assert.equal(facts("天津-河北区", ["河北"]).location, "mismatch");
  assert.equal(facts("内蒙古自治区·乌海市·海南区", ["海南"]).location, "mismatch");
});

test("城市目标：与改前逐字相同（原词或规范名出现在 location 里）", () => {
  const before = (loc, t) => {
    // 改前 eligibility.locationState 的实现，原样抄在这里当对照。
    const { normalizeChinaCity } = require("../lib/china-keyword-expansion");
    const norm = normalizeChinaCity(t);
    return loc.includes(t) || Boolean(norm && loc.includes(norm));
  };
  const targets = ["北京", "北京市", "深圳市", "上海", "天津", "新加坡", "香港", "浙江省宁波市", "远程"];
  const locations = fixture.cases.map((c) => c.location).filter(Boolean).concat(["北京市朝阳区", "Beijing", "深圳"]);
  for (const t of targets) {
    for (const loc of locations) {
      assert.equal(Boolean(matchLocationTargets(loc, [t])), before(loc, t), `${t} × ${loc}`);
    }
  }
});

test("城市群：按 expandChinaCityTargets 的既有定义展开", () => {
  assert.equal(facts("苏州", ["长三角"]).location, "match");
  assert.equal(facts("深圳", ["珠三角"]).location, "match");
  assert.equal(facts("成都", ["长三角"]).location, "mismatch");
});

test("召回 SQL：省目标的检索词覆盖解析器判给该省的全部写法（超集）", () => {
  // search_doc 含 location 的全部二元组，所以「某个检索词是 location 的子串」⇒ tsquery 命中。
  for (const { location, expected } of fixture.cases) {
    for (const province of expected) {
      if (!provinceOfTarget(province)) continue; // 直辖市 / 港澳走城市路径
      const terms = locationTargetSqlTerms(province);
      assert.ok(terms.some((t) => location.includes(t)), `${province} 的检索词覆盖不到「${location}」`);
    }
  }
  for (const province of Object.keys(geo.CN_PROVINCE_PREFECTURES)) {
    for (const name of geo.CN_PROVINCE_PREFECTURES[province]) {
      const loc = `${name}市`;
      if (geo.locationProvinces(loc).includes(province)) {
        assert.ok(locationTargetSqlTerms(province).some((t) => loc.includes(t)), `${province} × ${loc}`);
      }
    }
  }
});

test("召回 SQL：城市门带上全省地级名，城市目标的检索词与改前一致", () => {
  const built = buildRecallSql(profile(["陕西"]), NOW.toISOString(), 900);
  const cityTs = built.params.find((p) => typeof p === "string" && p.includes("西安"));
  assert.ok(cityTs, "陕西画像的城市 tsquery 里没有西安");
  for (const name of ["陕西", "榆林", "商洛"]) assert.ok(cityTs.includes(name), name);
  assert.deepEqual(resolveLocationTarget("深圳市").cities, ["深圳市", "深圳"]);
  assert.deepEqual(locationTargetSqlTerms("北京"), ["北京"]);
});

test("buildRadarProfile：一格多值的目标城市在读侧也拆开", () => {
  const p = buildRadarProfile(
    "u",
    { id: "p", user_id: "u", target_roles: ["质量工程师"], target_locations: ["杭州 深圳 无锡 宁波", "浙江 江苏 广东"] },
    null,
  );
  assert.deepEqual(p.targetLocations, ["杭州", "深圳", "无锡", "宁波", "浙江", "江苏", "广东"]);
  // 含拉丁字母的写法不拆（「Hong Kong」），认不出的原样保留。
  const q = buildRadarProfile("u", { id: "p", user_id: "u", target_roles: ["x"], target_locations: ["Hong Kong", "马来西亚"] }, null);
  assert.deepEqual(q.targetLocations, ["香港", "马来西亚"]);
});

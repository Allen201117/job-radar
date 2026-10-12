const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts.js");

// 用 _load-ts 加载：insight-match.ts 现在依赖 lib/geo.js（中文地名表），单文件 shim 解析不了相对 .js 依赖。
const M = loadTs(path.join(__dirname, "..", "lib", "insight-match.ts"));

function profile(company, aliases = []) {
  return { id: company, company, display_name: company, aliases, summary: null, last_verified_at: null, created_at: "", updated_at: "" };
}

test("normalizeCompany 去后缀与地域装饰", () => {
  assert.equal(M.normalizeCompany("字节跳动有限公司"), "字节跳动");
  assert.equal(M.normalizeCompany("Microsoft (China)"), "microsoft");
  assert.equal(M.normalizeCompany("Apple Inc."), "apple");
  assert.equal(M.normalizeCompany("  腾讯科技有限公司 "), "腾讯");
});

test("companyMatches 命中 company 或 alias", () => {
  const p = profile("字节跳动", ["字节", "ByteDance"]);
  assert.equal(M.companyMatches(p, "字节"), true);
  assert.equal(M.companyMatches(p, "bytedance"), true);
  assert.equal(M.companyMatches(p, "字节跳动（中国）"), true);
  assert.equal(M.companyMatches(p, "腾讯"), false);
});

test("findCompanyProfile 全等优先于子串", () => {
  const profiles = [
    profile("苹果", ["Apple", "苹果中国"]),
    profile("微软", ["Microsoft", "微软中国"]),
  ];
  assert.equal(M.findCompanyProfile(profiles, "Apple").company, "苹果");
  assert.equal(M.findCompanyProfile(profiles, "Microsoft (China)").company, "微软");
  assert.equal(M.findCompanyProfile(profiles, "不存在的公司"), null);
});

test("短拉丁别名不得误命中无关词（Reddit ≠ 小红书）", () => {
  const profiles = [profile("小红书", ["RED", "Xiaohongshu", "xhs"])];
  assert.equal(M.findCompanyProfile(profiles, "Reddit"), null);
  assert.equal(M.companyMatches(profiles[0], "Reddit"), false);
  // 真正的小红书写法仍命中
  assert.equal(M.findCompanyProfile(profiles, "Xiaohongshu").company, "小红书");
  assert.equal(M.companyMatches(profiles[0], "小红书"), true);
});

test("中文短名 + 城市后缀仍子串命中（腾讯深圳 → 腾讯）", () => {
  const profiles = [profile("腾讯", ["Tencent"])];
  assert.equal(M.findCompanyProfile(profiles, "腾讯（深圳）").company, "腾讯");
  assert.equal(M.companyMatches(profiles[0], "腾讯科技（北京）"), true);
  assert.equal(M.companyMatches(profiles[0], "腾讯科技（深圳）有限公司"), true);
  assert.equal(M.companyMatches(profiles[0], "深圳市腾讯计算机系统有限公司"), true);
});

// ⚠️ 张冠李戴门（2026-09-17 立）：中文名的子串命中不能只看「含汉字」。「京东」是「京东方」的子串、
// 「中国银行」是「中国银行业协会」的子串，旧实现一律放行 → 京东方（BOE）的岗被算进京东的洞察派生指标。
// 现行判据：多出来的那一截必须**全部**是公司装饰词（科技/集团/分行…）或中文地名，否则视为另一家公司。
test("中文子串命中：多出的部分不是装饰词/地名 = 另一家公司", () => {
  const jd = profile("京东", ["JD", "JD.com"]);
  assert.equal(M.companyMatches(jd, "京东方"), false);
  assert.equal(M.companyMatches(jd, "京东方科技集团股份有限公司"), false);
  assert.equal(M.companyMatches(jd, "京东物流"), false); // 子公司要靠 alias 显式登记，不靠子串猜
  assert.equal(M.companyMatches(jd, "京东健康"), false);
  assert.equal(M.companyMatches(jd, "京东集团"), true);
  assert.equal(M.companyMatches(jd, "京东（北京）"), true);
  assert.equal(M.companyMatches(jd, "京东科技集团北京分公司"), true);

  const boc = profile("中国银行", ["Bank of China", "BOC"]);
  assert.equal(M.companyMatches(boc, "中国银行业协会"), false);
  assert.equal(M.companyMatches(boc, "中国银行股份有限公司"), true);
  assert.equal(M.companyMatches(boc, "中国银行深圳市分行"), true);

  const tencent = profile("腾讯", ["Tencent"]);
  assert.equal(M.companyMatches(tencent, "腾讯音乐"), false);
  assert.equal(M.companyMatches(tencent, "腾讯云计算（北京）"), false);
});

test("反方向同样成立：查询名更短时，画像名多出的部分不是装饰词 = 不命中", () => {
  // 画像是「京东方」、岗位公司写「京东」→ 不能把京东的岗算到京东方头上
  assert.equal(M.companyMatches(profile("京东方"), "京东"), false);
  // 画像是「腾讯音乐」、岗位公司写「腾讯」→ 不命中
  assert.equal(M.companyMatches(profile("腾讯音乐"), "腾讯"), false);
  // 画像是「腾讯科技（深圳）」这种带装饰的写法、岗位写「腾讯」→ 仍命中
  assert.equal(M.companyMatches(profile("腾讯科技（深圳）"), "腾讯"), true);
});

test("findCompanyProfile：京东与京东方并存时各归各", () => {
  const profiles = [profile("京东", ["JD"]), profile("京东方", ["BOE"])];
  assert.equal(M.findCompanyProfile(profiles, "京东方").company, "京东方");
  assert.equal(M.findCompanyProfile(profiles, "京东方科技集团").company, "京东方");
  assert.equal(M.findCompanyProfile(profiles, "京东").company, "京东");
  assert.equal(M.findCompanyProfile(profiles, "京东集团").company, "京东");
});

// 全集对拍（1,383 画像 × 1,537 家在招公司名）里真实存在的「同一家」写法，收紧规则不能把它们误伤
test("同一家的真实写法仍命中：拼音/活动后缀、末尾括号集团名、央企地区子公司、品牌括号", () => {
  assert.equal(M.companyMatches(profile("云南白药 YNBY 校招"), "云南白药"), true);
  assert.equal(M.companyMatches(profile("云南白药"), "云南白药 YNBY 实习"), true);
  assert.equal(M.companyMatches(profile("地平线 Horizon Robotics 实习"), "地平线"), true);
  assert.equal(M.companyMatches(profile("北汽集团"), "北京奔驰汽车有限公司（北汽集团）"), true);
  assert.equal(M.companyMatches(profile("中国铁建"), "中铁十七局集团有限公司（中国铁建）"), true);
  assert.equal(M.companyMatches(profile("中国电建"), "中国电建集团江西省水电工程局有限公司"), true);
  assert.equal(M.companyMatches(profile("中国电建"), "中国电建集团北京勘测设计研究院有限公司"), true);
  assert.equal(M.companyMatches(profile("好未来"), "好未来（学而思）"), true);
  assert.equal(M.companyMatches(profile("双汇"), "河南双汇投资发展"), true);
  assert.equal(M.companyMatches(profile("中国平安"), "平安银行股份有限公司佛山分行（中国平安）"), true);
  // 品牌 + 行业描述词
  assert.equal(M.companyMatches(profile("大疆创新"), "大疆"), true);
  assert.equal(M.companyMatches(profile("申通快递"), "申通"), true);
  assert.equal(M.companyMatches(profile("微众银行"), "深圳前海微众银行"), true);
});

test("另一家公司仍不命中：品牌词残尾、末尾括号写着别的集团、协会", () => {
  assert.equal(M.companyMatches(profile("网易"), "网易有道"), false);
  assert.equal(M.companyMatches(profile("网易"), "网易云音乐"), false);
  assert.equal(M.companyMatches(profile("东软集团股份有限公司"), "东软医疗"), false);
  assert.equal(M.companyMatches(profile("华峰集团"), "华峰测控"), false);
  // 数据自己在括号里声明了归属是中国建研院，不是中国建筑
  assert.equal(M.companyMatches(profile("中国建筑"), "中国建筑科学研究院有限公司建筑防火研究所（中国建研院）"), false);
  // 光有「科学研究院」没有地区，不按央企子公司写法放行
  assert.equal(M.companyMatches(profile("中国建筑"), "中国建筑科学研究院有限公司"), false);
  assert.equal(M.companyMatches(profile("中国银行"), "中国银行业协会"), false);
});

// ============================================================
// 2026-10-11：门把不同公司放行的四处收紧。
// 全集回放（1,725 个在招公司名 × 1,318 个画像）与逐对判定见
// docs/reviews/2026-10-11-attribution-gate-and-must-apply-patterns.md。
// ============================================================

test("短名自己带英文时，多出来的英文是另一个名字，不是拼音尾巴（沃尔沃汽车 ≠ 沃尔沃集团）", () => {
  // 归一后「沃尔沃 Volvo Group」= 沃尔沃volvo，是「沃尔沃volvocars」的前缀；多出的 cars 曾被当成拼音尾巴放行。
  assert.equal(M.companyMatches(profile("沃尔沃 Volvo Group"), "沃尔沃 Volvo Cars"), false);
  assert.equal(M.companyMatches(profile("沃尔沃 Volvo Cars"), "沃尔沃 Volvo Group"), false);
  assert.equal(M.findCompanyProfile([profile("沃尔沃 Volvo Group")], "沃尔沃 Volvo Cars"), null);
  // 短名是纯中文时，英文尾巴照旧算装饰；中文的招聘渠道后缀也照旧
  assert.equal(M.companyMatches(profile("地平线"), "地平线 Horizon Robotics"), true);
  assert.equal(M.companyMatches(profile("荣耀 Honor"), "荣耀 Honor 实习"), true);
  assert.equal(M.companyMatches(profile("招商证券 CMS 校招"), "招商证券 CMS"), true);
});

test("「饮料」不是装饰词：东鹏（瓷砖卫浴）≠ 东鹏饮料", () => {
  // 9-17 把「饮料」收进装饰词的依据是「东鹏饮料 = 东鹏」，而那条源当时就挂错了名（抓的是东鹏控股）。
  assert.equal(M.companyMatches(profile("东鹏"), "东鹏饮料"), false);
  assert.equal(M.companyMatches(profile("东鹏饮料"), "东鹏"), false);
  // 同一批加进来的其它行业描述词不受影响
  assert.equal(M.companyMatches(profile("蒙牛"), "蒙牛乳业"), true);
  assert.equal(M.companyMatches(profile("极兔"), "极兔速递"), true);
});

test("登记过「不是同一家」的名字，门不放行（上海大华集团 ≠ 浙江大华股份）", () => {
  const security = profile("大华股份 Dahua", ["浙江大华技术"]);
  const estate = profile("大华集团");
  assert.equal(M.companyMatches(security, "大华集团"), false);
  assert.equal(M.companyMatches(security, "大华集团有限公司"), false);
  assert.equal(M.companyMatches(estate, "大华股份 Dahua"), false);
  assert.equal(M.companyMatches(estate, "浙江大华技术股份有限公司"), false);
  // 其中一个画像没了，它的名字也不会落到另一家头上
  assert.equal(M.findCompanyProfile([security], "大华集团"), null);
  assert.equal(M.findCompanyProfile([estate], "大华股份 Dahua"), null);
  assert.equal(M.findCompanyProfile([estate], "浙江大华技术股份有限公司"), null);
  // 各自的名字照常认到自己
  assert.equal(M.findCompanyProfile([security, estate], "大华集团").company, "大华集团");
  assert.equal(M.findCompanyProfile([estate, security], "大华股份 Dahua").company, "大华股份 Dahua");
  assert.equal(M.companyMatches(security, "浙江大华技术股份有限公司"), true);
  assert.equal(M.companyMatches(security, "大华股份"), true);
  assert.equal(M.companyMatches(estate, "大华集团有限公司"), true);
  // 名字里有「大华」但不是这两家的，名单不管
  assert.equal(M.companyMatches(estate, "大华银行（中国）有限公司"), false);
});

test("「不是同一家」名单逐条钉死：每条都要有依据，两边的标记词不能重叠", () => {
  const registry = require("../lib/insight-distinct-companies.json");
  assert.deepEqual(registry.map((entry) => entry.core), ["大华"]);
  for (const entry of registry) {
    assert.ok(Array.isArray(entry.sides) && entry.sides.length >= 2, `${entry.core}: 至少两边`);
    const seen = new Set();
    for (const side of entry.sides) {
      assert.ok(typeof side.label === "string" && side.label.trim(), `${entry.core}: 每一边要写清是哪家公司`);
      assert.ok(Array.isArray(side.markers) && side.markers.length, `${entry.core}: 每一边至少一个标记词`);
      for (const marker of side.markers) {
        assert.equal(marker, marker.toLowerCase(), `${entry.core}: 标记词写小写`);
        assert.ok(!seen.has(marker), `${entry.core}: 标记词「${marker}」出现在两边`);
        seen.add(marker);
      }
    }
    for (const field of ["evidence", "verified_at"]) {
      assert.ok(typeof entry[field] === "string" && entry[field].trim(), `${entry.core}.${field} 不能为空`);
    }
    assert.match(entry.verified_at, /^\d{4}-\d{2}-\d{2}$/);
  }
});

test("精确优先：名字另有精确画像时，别的画像不认领（companyOwnsName）", () => {
  const profiles = [profile("京东", ["JD", "京东集团"]), profile("京东科技")];
  const index = M.buildExactProfileIndex(profiles);
  // 门本身仍放行（「科技」是装饰词，腾讯科技（北京）= 腾讯 这类写法要靠它）
  assert.equal(M.companyMatches(profiles[0], "京东科技"), true);
  // 但京东科技有自己的画像 → 只归它
  assert.equal(M.companyOwnsName(profiles[0], "京东科技", index), false);
  assert.equal(M.companyOwnsName(profiles[1], "京东科技", index), true);
  assert.equal(M.companyOwnsName(profiles[0], "京东集团", index), true);
  // 没有精确画像的名字，仍按门归属
  assert.equal(M.companyOwnsName(profiles[0], "京东（北京）", index), true);
  assert.equal(M.companyOwnsName(profiles[1], "腾讯", index), false);
  // 京东科技的画像没了：门照旧把它放给京东（母子关系是 9-17 定的设计，不在这次收紧范围）
  assert.equal(M.companyOwnsName(profiles[0], "京东科技", M.buildExactProfileIndex([profiles[0]])), true);
});

test("ownedJobCount：别的画像精确登记的名字不计入本画像的在招数", () => {
  const profiles = [profile("中国铁建"), profile("中国铁建国际集团有限公司"), profile("中国铁建投资集团有限公司")];
  const index = M.buildExactProfileIndex(profiles);
  const counts = [
    { company: "中铁十七局集团有限公司（中国铁建）", job_count: 1 },
    { company: "中国铁建国际集团有限公司", job_count: 33 },
    { company: "中国铁建投资集团有限公司", job_count: 23 },
    { company: "腾讯", job_count: 999 },
  ];
  // 改前是门放行求和 = 57；两家子公司各有画像，不该算到集团头上
  assert.equal(M.ownedJobCount(profiles[0], counts, index), 1);
  assert.equal(M.ownedJobCount(profiles[1], counts, index), 33);
});

test("精确优先遇上「不是同一家」：名单说是另一家的精确登记者，不能把名字占住", () => {
  // 「大华股份」归一后只剩「大华」，精确登记它的是大华集团的画像；名单说它属于浙江大华那一边。
  const security = profile("大华股份 Dahua", ["浙江大华技术"]);
  const estate = profile("大华集团");
  const index = M.buildExactProfileIndex([estate, security]);
  assert.equal(M.companyOwnsName(security, "大华股份", index), true);
  assert.equal(M.companyOwnsName(estate, "大华股份", index), false);
  assert.equal(M.companyOwnsName(estate, "大华集团", index), true);
  assert.equal(M.companyOwnsName(security, "大华集团", index), false);
  assert.equal(M.ownedJobCount(security, [{ company: "大华股份", job_count: 7 }, { company: "大华集团", job_count: 51 }], index), 7);
});

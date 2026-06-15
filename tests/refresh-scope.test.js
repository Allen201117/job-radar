const assert = require("node:assert/strict");
const test = require("node:test");

const { resolveRefreshScope } = require("../lib/refresh-scope");

const src = (id, company, adapter_name, extra = {}) => ({
  id,
  company,
  adapter_name,
  source_url: extra.source_url || `https://${id}.example.com/jobs`,
  industry: extra.industry || "",
  segment: extra.segment || "",
  enabled: extra.enabled !== false,
});

test("手动公司筛选优先：只命中该公司的源", () => {
  const sources = [src("a", "字节跳动", "bytedance"), src("b", "腾讯", "tencent")];
  const r = resolveRefreshScope(
    { filters: { company: "字节" }, preferences: { targetCompanies: ["腾讯"] }, sources },
    {},
  );
  assert.deepEqual(r.sourceIds, ["a"]); // 手动「字节」覆盖偏好「腾讯」
});

test("未配公司 → 用偏好 target_companies 兜底", () => {
  const sources = [src("a", "字节跳动", "bytedance"), src("b", "腾讯", "tencent"), src("c", "阿里", "alibaba")];
  const r = resolveRefreshScope(
    { filters: {}, preferences: { targetCompanies: ["腾讯", "阿里"] }, sources },
    {},
  );
  assert.deepEqual(new Set(r.sourceIds), new Set(["b", "c"]));
});

test("关键词命中 industry/segment 的源排在最前（本土均可入选兜底）", () => {
  const sources = [
    src("a", "某游戏公司", "moka", { industry: "游戏" }),
    src("b", "某银行", "beisen", { industry: "金融" }),
  ];
  const r = resolveRefreshScope({ filters: { keyword: "游戏" }, preferences: {}, sources }, {});
  // 关键词命中行业的本土源（a）排第一；b 也是本土源、靠基础分兜底入选（逐岗过滤再保证只放行命中岗）。
  assert.equal(r.sourceIds[0], "a");
  assert.deepEqual(new Set(r.sourceIds), new Set(["a", "b"]));
});

test("中文/国内城市查询：本土 adapter 排在外企 ATS 前", () => {
  const sources = [
    src("g1", "WorldQuant", "greenhouse", { segment: "foreign", industry: "量化" }),
    src("g2", "Cloudflare", "greenhouse", { segment: "foreign", industry: "互联网" }),
    src("d1", "某本土科技", "moka", { segment: "private", industry: "互联网" }),
    src("d2", "某本土制造", "beisen", { segment: "private", industry: "制造" }),
  ];
  const r = resolveRefreshScope(
    { filters: { keyword: "产品经理", city: "深圳", jobType: "实习" }, preferences: {}, sources },
    {},
  );
  // 本土源（d1/d2）必须全部排在任何外企源之前。
  const domestic = ["d1", "d2"];
  const rankOfLastDomestic = Math.max(...domestic.map((id) => r.sourceIds.indexOf(id)));
  const foreignRanks = ["g1", "g2"]
    .map((id) => r.sourceIds.indexOf(id))
    .filter((i) => i >= 0);
  for (const fr of foreignRanks) {
    assert.ok(rankOfLastDomestic < fr, "外企源不得排在本土源之前");
  }
  // 外企无显式公司/关键词命中时（产品经理不命中其行业）应被本土挤出，不占 N 槽。
  assert.ok(r.sourceIds.indexOf("d1") >= 0 && r.sourceIds.indexOf("d2") >= 0);
});

test("notes 提到所查城市的源获得城市/HQ 加成、排在同类本土源前", () => {
  const sources = [
    src("near", "深圳公司", "moka", { industry: "互联网", notes: "深圳科技园 in-house 招聘" }),
    src("far", "成都公司", "moka", { industry: "互联网", notes: "成都高新区" }),
  ];
  const r = resolveRefreshScope(
    { filters: { keyword: "产品", city: "深圳" }, preferences: {}, sources },
    {},
  );
  assert.equal(r.sourceIds[0], "near"); // 深圳 notes 命中 → 城市信号加成排第一
});

test("海外/港澳意图（城市=香港）：不做本土优先压制，外企量化源照常命中", () => {
  const sources = [
    src("g1", "IMC Trading", "greenhouse", { segment: "foreign", industry: "量化" }),
    src("d1", "某本土制造", "beisen", { segment: "private", industry: "制造" }),
  ];
  const r = resolveRefreshScope(
    { filters: { keyword: "量化", city: "香港" }, preferences: {}, sources },
    {},
  );
  // 香港=海外意图 → 不给本土基础分；外企关键词命中（量化）入选，本土无关键词命中则不入选。
  assert.ok(r.sourceIds.includes("g1"));
  assert.ok(!r.sourceIds.includes("d1"));
});

test("proven：已收录里真有该岗位的公司优先于一切 metadata 信号（根治选错公司→坍缩）", () => {
  const sources = [
    src("dom", "某本土公司", "moka", { industry: "互联网" }), // 本土基础分 +100
    src("prov", "迈瑞医疗", "beisen"), // proven（库里真有 城市+关键词 岗位）
    src("exact", "OPPO", "oppo"), // proven exact（还命中类型）
  ];
  const r = resolveRefreshScope(
    {
      filters: { keyword: "产品经理", city: "深圳", jobType: "实习" },
      preferences: {},
      provenCompanies: ["迈瑞医疗", "OPPO"],
      provenExactCompanies: ["OPPO"],
      sources,
    },
    {},
  );
  assert.equal(r.sourceIds[0], "exact"); // exact(+5000) 第一
  assert.equal(r.sourceIds[1], "prov"); // related(+3000) 第二
  assert.ok(r.sourceIds.indexOf("exact") < r.sourceIds.indexOf("dom")); // 都在本土 metadata 源之前
});

test("proven：外企 adapter 上的 proven 公司也优先（信号来自真实库存岗位，不看平台）", () => {
  const sources = [
    src("dom", "某本土公司", "moka"), // 本土 +100
    src("foreignProven", "飞利浦 Philips", "workday"), // 外企但 proven +3000
  ];
  const r = resolveRefreshScope(
    {
      filters: { keyword: "产品经理", city: "深圳" },
      preferences: {},
      provenCompanies: ["飞利浦 Philips"],
      sources,
    },
    {},
  );
  assert.equal(r.sourceIds[0], "foreignProven");
});

test("exclude_keywords 命中公司名的源被剔除", () => {
  const sources = [src("a", "外包科技", "moka"), src("b", "字节跳动", "bytedance")];
  const r = resolveRefreshScope(
    { filters: {}, preferences: { targetCompanies: ["外包", "字节"], excludeKeywords: ["外包"] }, sources },
    {},
  );
  assert.deepEqual(r.sourceIds, ["b"]);
});

test("总 cap N 限制返回数量", () => {
  const sources = Array.from({ length: 40 }, (_, i) =>
    src(`s${i}`, `公司${i}`, i % 2 ? "moka" : "beisen", { source_url: `https://h${i}.x.com/j` }),
  );
  const companies = sources.map((s) => s.company);
  const r = resolveRefreshScope({ filters: {}, preferences: { targetCompanies: companies }, sources }, { cap: 25 });
  assert.equal(r.sourceIds.length, 25);
  assert.equal(r.matchedCount, 40);
  assert.equal(r.droppedCount, 15);
});

test("每 adapter|host 多样性 cap：单主机不独占全部槽位", () => {
  // 30 个源全在同一 adapter+host（app.mokahr.com），perHostCap=3 应先只取 3 个再二轮填满到 cap。
  const sources = Array.from({ length: 30 }, (_, i) =>
    src(`m${i}`, `公司${i}`, "moka", { source_url: "https://app.mokahr.com/jobs" }),
  );
  const companies = sources.map((s) => s.company);
  // 再混入 2 个不同 host 的源
  sources.push(src("z1", "公司Z1", "beisen", { source_url: "https://z1.zhiye.com/j" }));
  sources.push(src("z2", "公司Z2", "workday", { source_url: "https://z2.wd.com/j" }));
  companies.push("公司Z1", "公司Z2");
  const r = resolveRefreshScope(
    { filters: {}, preferences: { targetCompanies: companies }, sources },
    { cap: 25, perHostCap: 3 },
  );
  // 两个独立 host 的源必须进第一轮（多样性），证明没被单主机挤掉
  assert.ok(r.sourceIds.includes("z1"), "beisen 源应入选");
  assert.ok(r.sourceIds.includes("z2"), "workday 源应入选");
  assert.equal(r.sourceIds.length, 25);
});

test("零命中（无筛选无偏好）→ 空范围", () => {
  const sources = [src("a", "字节跳动", "bytedance")];
  const r = resolveRefreshScope({ filters: {}, preferences: {}, sources }, {});
  assert.deepEqual(r.sourceIds, []);
});

test("disabled 源不入选", () => {
  const sources = [src("a", "字节跳动", "bytedance", { enabled: false })];
  const r = resolveRefreshScope(
    { filters: {}, preferences: { targetCompanies: ["字节"] }, sources },
    {},
  );
  assert.deepEqual(r.sourceIds, []);
});

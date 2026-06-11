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

test("关键词命中 industry/segment 的源入选", () => {
  const sources = [
    src("a", "某游戏公司", "moka", { industry: "游戏" }),
    src("b", "某银行", "beisen", { industry: "金融" }),
  ];
  const r = resolveRefreshScope({ filters: { keyword: "游戏" }, preferences: {}, sources }, {});
  assert.deepEqual(r.sourceIds, ["a"]);
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

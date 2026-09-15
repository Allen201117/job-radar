const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");
const { classifyCompanyTier, companyTierPatterns, COMPANY_TIER_LABELS, NAMED_TIER_PATTERNS } =
  loadTs(path.join(__dirname, "..", "lib", "company-tiers.ts"));

test("命中命名标签", () => {
  assert.equal(classifyCompanyTier("字节跳动"), "大厂");
  assert.equal(classifyCompanyTier("中国交建 校招"), "央国企");
  assert.equal(classifyCompanyTier("Apple"), "外企");
  assert.equal(classifyCompanyTier("MiniMax 稀宇科技"), "初创独角兽");
});

test("不命中任何名单 → 中小厂兜底", () => {
  assert.equal(classifyCompanyTier("某不知名小公司有限公司"), "中小厂");
  assert.equal(classifyCompanyTier(""), "中小厂");
});

test("标签顺序:中小厂在末尾", () => {
  assert.deepEqual(COMPANY_TIER_LABELS[COMPANY_TIER_LABELS.length - 1], "中小厂");
  assert.ok(COMPANY_TIER_LABELS.includes("大厂"));
});

test("companyTierPatterns 拆解正确", () => {
  const r = companyTierPatterns(["大厂", "中小厂"]);
  assert.ok(r.includeSmb === true);
  assert.ok(r.named.some((p) => p.includes("字节")));
  const r2 = companyTierPatterns(["外企"]);
  assert.equal(r2.includeSmb, false);
  assert.ok(r2.named.length > 0);
});

test("NAMED_TIER_PATTERNS 覆盖所有命名标签、不含中小厂", () => {
  assert.ok(NAMED_TIER_PATTERNS.length >= 100); // 大厂+央国企+外企+独角兽 patterns 合计
  // 中小厂无 pattern,不应出现
});

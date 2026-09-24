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

test("大华：安防大华（库里记作「大华股份 Dahua」）是大厂，上海大华集团（地产）不是", () => {
  // 迁移 291：moka 租户 dahua 曾被记成「浙江大华技术」，%浙江大华% 只命中那条错名、漏掉真的大华股份。
  assert.equal(classifyCompanyTier("大华股份 Dahua"), "大厂");
  assert.equal(classifyCompanyTier("浙江大华技术股份有限公司"), "大厂");
  assert.equal(classifyCompanyTier("大华集团"), "中小厂");
});

test("贝壳：社招 / 校招两个门户分别记作「贝壳 Beike」「贝壳找房」，都是大厂", () => {
  // 原 pattern 是 %贝壳找房%，社招 476 个在招岗（贝壳 Beike）一直被兜底成中小厂（2026-09-24 查实）。
  assert.equal(classifyCompanyTier("贝壳 Beike"), "大厂");
  assert.equal(classifyCompanyTier("贝壳找房"), "大厂");
});

test("不命中任何名单 → 中小厂兜底", () => {
  assert.equal(classifyCompanyTier("某不知名小公司有限公司"), "中小厂");
  assert.equal(classifyCompanyTier(""), "中小厂");
});

test("标签顺序:中小厂在末尾", () => {
  assert.deepEqual(COMPANY_TIER_LABELS, ["大厂","央国企","外企","初创独角兽","中小厂"]);
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
  assert.ok(NAMED_TIER_PATTERNS.length >= 100);
  assert.ok(!NAMED_TIER_PATTERNS.some(p => p.includes("中小厂")));
});

test("跨标签无核心子串碰撞(保计数精确的不变量)", () => {
  // 收集每个命名标签的 pattern 核心
  const tiers = require("../lib/company-tiers.json");
  const byTier = {};
  for (const [k, v] of Object.entries(tiers)) {
    if (k === "_meta" || !Array.isArray(v)) continue;
    byTier[k] = v.map((e) => e.pattern.replace(/%/g, "").trim().toLowerCase());
  }
  const names = Object.keys(byTier);
  for (let i = 0; i < names.length; i++) {
    for (let j = 0; j < names.length; j++) {
      if (i === j) continue;
      for (const a of byTier[names[i]]) {
        for (const b of byTier[names[j]]) {
          // a 不应是 b 的子串(否则同一公司名可能同时命中两个标签,SQL/JS 口径分叉)
          assert.ok(!b.includes(a), `跨标签核心碰撞: "${a}"(${names[i]}) ⊂ "${b}"(${names[j]})`);
        }
      }
    }
  }
});

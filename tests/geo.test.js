const test = require("node:test");
const assert = require("node:assert");

const { deriveCountryCode, deriveJobScope, locationInScope } = require("../lib/geo.js");

test("deriveCountryCode: greater china", () => {
  assert.equal(deriveCountryCode("Beijing, China"), "CN");
  assert.equal(deriveCountryCode("Business Analyst, Beijing"), "CN");
  assert.equal(deriveCountryCode("Focus Group, Shanghai"), "CN");
  assert.equal(deriveCountryCode("Hong Kong"), "HK");
});

test("deriveCountryCode: overseas", () => {
  assert.equal(deriveCountryCode("New York, NY"), "US");
  assert.equal(deriveCountryCode("Singapore"), "SG");
  for (const [location, expected] of [
    ["Remote - US", "US"],
    ["Remote, US", "US"],
    ["US - Remote", "US"],
    ["US Remote", "US"],
    ["Remote (USA)", "US"],
    ["Remote - United States", "US"],
    ["Remote, USA", "US"],
    ["Remote (US)", "US"],
    ["Remote (U.S.)", "US"],
    ["Remote - Singapore", "SG"],
    ["Remote, SG", "SG"],
    ["Singapore - Remote", "SG"],
    ["Remote (Singapore)", "SG"],
  ]) {
    assert.equal(deriveCountryCode(location), expected, location);
  }
});

test("deriveCountryCode: unknown", () => {
  assert.equal(deriveCountryCode("Remote"), null);
  assert.equal(deriveCountryCode("Belarus"), null);
  assert.equal(deriveCountryCode(""), null);
});

test("deriveJobScope: domestic vs overseas", () => {
  assert.equal(deriveJobScope("Beijing, China"), "domestic");
  assert.equal(deriveJobScope("Hong Kong"), "domestic");
  assert.equal(deriveJobScope("New York"), "overseas");
  assert.equal(deriveJobScope("Singapore"), "overseas");
  for (const location of ["Remote - US", "US Remote", "Remote (USA)", "Remote - Singapore"]) {
    assert.equal(deriveJobScope(location), "overseas", location);
  }
  assert.equal(deriveJobScope("Remote"), "domestic");
});

test("locationInScope: Taiwan is not in domestic or overseas launch scopes", () => {
  for (const loc of ["Taiwan", "Taipei, Taiwan", "台北, 台湾"]) {
    assert.equal(locationInScope(loc, ["CN"]), false, loc);
    assert.equal(locationInScope(loc, ["US", "SG", "Remote"]), false, loc);
    assert.equal(locationInScope(loc, ["CN", "US", "SG", "Remote"]), false, loc);
  }
});

// 对齐 crawler/test_geo.py 的 TaiwanWithChinaSuffixTest。
// 背景：Python 侧 2026-07-28 就把 TW 加进 _COUNTRY_TOKENS 了，**JS 侧一直漏着**，
// 于是「Taiwan, Province of China」这类含 china 字样的写法在 JS 侧被判成 CN/domestic，
// 经 lib/jobs-store/write.ts 的 withDerivedFields 写进香港库就是台湾岗进国内看板。
// 上面那条 "Taiwan is not in domestic or overseas launch scopes" 只覆盖不含 china 字样的写法
// （当时 code=null 自然落 false），所以一直是绿的、盖不住这个洞。
const TAIWAN_WITH_CHINA_SUFFIX = [
  "Taipei, Taipei shih, Taiwan, Province of China",
  "Taiwan, Province of China",
  "Hsinchu, Taiwan, Province of China",
  "台北, 台湾, 中国",
];

test("deriveCountryCode: Taiwan with china suffix is TW, not CN", () => {
  for (const loc of TAIWAN_WITH_CHINA_SUFFIX) {
    assert.equal(deriveCountryCode(loc), "TW", loc);
  }
});

test("deriveJobScope: Taiwan never counts as domestic", () => {
  for (const loc of [...TAIWAN_WITH_CHINA_SUFFIX, "Taiwan", "Taipei, Taiwan", "台北, 台湾"]) {
    assert.equal(deriveJobScope(loc), "overseas", loc);
  }
});

test("locationInScope: Taiwan with china suffix is out of every region set", () => {
  for (const loc of TAIWAN_WITH_CHINA_SUFFIX) {
    assert.equal(locationInScope(loc, ["CN"]), false, loc);
    assert.equal(locationInScope(loc, ["US", "SG", "Remote"]), false, loc);
    assert.equal(locationInScope(loc, ["CN", "US", "SG", "Remote"]), false, loc);
  }
});

test("deriveCountryCode: 拦台湾没有误伤大陆/港澳", () => {
  assert.equal(deriveCountryCode("Shanghai, Shanghai Shi, China"), "CN");
  assert.equal(deriveCountryCode("Wuxi, Jiangsu Sheng, China"), "CN");
  assert.equal(deriveCountryCode("Hong Kong"), "HK");
  assert.equal(deriveCountryCode("Macau"), "MO");
  assert.equal(locationInScope("Wuxi, Jiangsu Sheng, China", ["CN"]), true);
  assert.equal(locationInScope("Hong Kong", ["CN"]), true);
});

// 防的就是这次这个 bug 本身：两端各改各的、其中一端悄悄落后。
// 直接读 crawler/geo.py 的 TW 字面量做对拍，漂了就红。
test("TW token 表与 crawler/geo.py 逐字一致，且排在 CN 前面", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const py = fs.readFileSync(path.join(__dirname, "..", "crawler", "geo.py"), "utf8");
  const m = py.match(/^\s*"TW":\s*\[([^\]]*)\]/m);
  assert.ok(m, "没在 crawler/geo.py 里找到 \"TW\": [...] —— 两端对拍失效，先修这里再说");
  const pyTokens = m[1].split(",").map((s) => s.trim()).filter(Boolean)
    .map((s) => s.replace(/^["']|["']$/g, ""));

  const { COUNTRY_TOKENS } = require("../lib/geo.js");
  assert.ok(COUNTRY_TOKENS, "lib/geo.js 需要导出 COUNTRY_TOKENS 供对拍");
  assert.deepEqual(COUNTRY_TOKENS.TW, pyTokens);

  const keys = Object.keys(COUNTRY_TOKENS);
  assert.ok(
    keys.indexOf("TW") >= 0 && keys.indexOf("TW") < keys.indexOf("CN"),
    "TW 必须排在 CN 前面：遍历按插入序，先命中先返回，排在 CN 后面等于没加",
  );
});

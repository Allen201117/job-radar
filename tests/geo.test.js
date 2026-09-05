const test = require("node:test");
const assert = require("node:assert");

const { deriveCountryCode, deriveJobScope, locationInScope, normalizeRegions } = require("../lib/geo.js");

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

// ============================================================
// 裸「远程」按**源自己的 regions** 兜底判归属 —— 对齐 crawler/test_geo.py 的
// BareRemoteScopeBySourceRegionsTest（两端是同一个判定的两份实现，必须逐字同口径）。
//
// 为什么要这道门：crawler/geo.py 2026-09-04 就给 derive_job_scope 加了 regions 兜底，
// 但 lib/geo.js 的 deriveJobScope 一直只有一个参数 —— 于是同一个裸「远程」岗，
// 爬虫写 overseas、app 的 discovery/search 刷新一次就写回 domestic。
// 2026-09-05 香港库实测：「location 抽不出国家」的在招岗里，源含 CN 的 114,075 个全是
// domestic、源不含 CN 的 16,159 个全是 overseas，交叉项 0 个 —— 按源判是干净的。
// ============================================================

test("deriveJobScope: 海外源的裸「远程」判 overseas", () => {
  assert.equal(deriveJobScope("远程", ["US", "SG", "Remote"]), "overseas");
  assert.equal(deriveJobScope("Remote", ["US", "SG", "Remote"]), "overseas");
  assert.equal(deriveJobScope("Distributed", ["US", "SG", "Remote"]), "overseas");
});

test("deriveJobScope: 源含 CN 的裸「远程」保持 domestic（宁可漏判不可错杀）", () => {
  assert.equal(deriveJobScope("远程", ["CN", "US", "SG", "Remote"]), "domestic");
  assert.equal(deriveJobScope("远程", ["CN"]), "domestic");
});

test("deriveJobScope: 不传 regions 时行为一字不变（不波及老调用方）", () => {
  assert.equal(deriveJobScope("远程"), "domestic");
  assert.equal(deriveJobScope("Remote"), "domestic");
  assert.equal(deriveJobScope(""), "domestic");
  // 空数组 / null 与「没传」等价（对齐 Python 的 `if regions:`）
  assert.equal(deriveJobScope("远程", []), "domestic");
  assert.equal(deriveJobScope("远程", null), "domestic");
});

test("deriveJobScope: 地点能抽出国家时以地点为准，压过源 regions", () => {
  assert.equal(deriveJobScope("Beijing, China", ["US", "SG"]), "domestic");
  assert.equal(deriveJobScope("香港", ["US"]), "domestic");
  assert.equal(deriveJobScope("New York, NY", ["CN", "US"]), "overseas");
  assert.equal(deriveJobScope("Remote - US", ["CN", "US", "SG", "Remote"]), "overseas");
});

test("deriveJobScope: 空地点 / Multiple Locations 与裸远程同理，都走源兜底", () => {
  assert.equal(deriveJobScope("", ["US"]), "overseas");
  assert.equal(deriveJobScope("Multiple Locations", ["US"]), "overseas");
  assert.equal(deriveJobScope("Unknown", ["US"]), "overseas");
});

test("normalizeRegions: 数组 / PG 数组字面量 / 脏值都归一到同一份判定", () => {
  assert.deepEqual(normalizeRegions(["CN", " US ", ""]), ["CN", "US"]);
  assert.deepEqual(normalizeRegions("{US,SG,Remote}"), ["US", "SG", "Remote"]);
  assert.deepEqual(normalizeRegions(new Set(["CN", "US"])), ["CN", "US"]);
  assert.deepEqual(normalizeRegions(null), []);
  assert.deepEqual(normalizeRegions([]), []);
  // ⚠️ 裸字符串绝不能被切成单个字符（"CN" → ["C","N"] 会判不出 CN，把国内岗打成海外）
  assert.deepEqual(normalizeRegions("CN"), ["CN"]);
  assert.equal(deriveJobScope("远程", "{CN,US}"), "domestic");
  assert.equal(deriveJobScope("远程", "{US,SG}"), "overseas");
});

// 外企 ATS 给的是小写 ISO 国别码 + 空格分词拼音城市；不认 "cn" 就判不出中国，
// 中国岗会在 locationInScope 处被当成非中国岗丢掉（大陆集团 29 个里丢了 8 个）。
// 串来自 SmartRecruiters 大陆集团中国岗（2026-09-05 live 原样抓取）。
// ⚠️ 必须与 crawler/geo.py 的 CHINA_LOCATION_MARKERS 逐条一致。
test("deriveCountryCode: ISO cn marks China without leaking into other places", () => {
  for (const location of [
    "He Fei Shi, An Hui Sheng, cn",
    "Ning Bo Shi, Zhe Jiang Sheng, cn",
    "Ji Ning Shi, Shan Dong Sheng, cn",
    "Yang Pu Qu, Shang Hai Shi, cn",
    "Zhangjiagang, cn",
  ]) {
    assert.equal(deriveCountryCode(location), "CN", location);
    assert.equal(locationInScope(location, ["CN", "US", "SG", "Remote"]), true, location);
  }
  assert.notEqual(deriveCountryCode("Cincinnati, OH"), "CN");
  assert.notEqual(deriveCountryCode("Chennai, TN, in"), "CN");
  assert.equal(deriveCountryCode("Hong Kong, cn"), "HK");
});

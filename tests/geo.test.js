const test = require("node:test");
const assert = require("node:assert");

const fs = require("node:fs");
const path = require("node:path");

const geo = require("../lib/geo.js");
const { deriveCountryCode, deriveJobScope, locationInScope } = geo;

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

// 中文地名：库里 27.8 万个「中文地点 + 在招」的岗曾有 8.3 万个 country_code 为空 ——
// 旧词表的中文标记只有「中国」+21 个一线城市，认得 "Changchun" 却认不得「长春市」，
// 这些岗的国内外归属完全押在 sources.regions 一个字段上（2026-09-05 实测）。
test("deriveCountryCode: 中文省市/自治州/分隔写法都判得出中国", () => {
  for (const loc of [
    "安徽省·芜湖市", "福建·宁德市", "山东省-济南市",
    "长春市", "嘉兴", "惠州市",
    "保定市-莲池区", "安徽省·芜湖市·鸠江区",
    "广东省", "内蒙古自治区·呼和浩特市", "昌吉回族自治州-昌吉市", "巴音郭楞蒙古自治州",
    "全国",
  ]) {
    assert.equal(deriveCountryCode(loc), "CN", loc);
    assert.equal(deriveJobScope(loc), "domestic", loc);
    assert.equal(locationInScope(loc, ["CN"]), true, loc);
  }
});

// 红线：台/日/韩的中文地名一个都不许判成中国。这也是不能用「含 省/市/区/县 → 中国」
// 那条 84% 覆盖率规则的原因 —— 它会把新北市/大阪市/東京都/首尔市一起吞进去。
test("deriveCountryCode: 台日韩中文地名不判中国，且不在任何抓取范围内", () => {
  for (const [loc, expected] of [
    ["新北市", "TW"], ["台北市", "TW"], ["桃園市", "TW"], ["臺中市", "TW"], ["台南市", "TW"],
    ["台湾省", "TW"], ["金门县", "TW"], ["云林县", "TW"],
    ["大阪市", "JP"], ["東京都", "JP"], ["北海道", "JP"], ["横滨市", "JP"], ["日本·东京", "JP"],
    ["首尔市", "KR"], ["韩国·首尔", "KR"], ["釜山", "KR"], ["京畿道", "KR"],
  ]) {
    assert.equal(deriveCountryCode(loc), expected, loc);
    assert.equal(deriveJobScope(loc), "overseas", loc);
    assert.equal(locationInScope(loc, ["CN", "US", "SG", "Remote"]), false, loc);
  }
});

// 反方向：长得像台/日/韩、其实是大陆的写法一个都不许误杀。
// 错判方向不对称 —— 漏判台湾岗只是回到 null（照样被 locationInScope 丢掉，无害），
// 错判大陆岗是把在招岗静默删掉（有害）。每条都是库里真实存在的写法。
test("deriveCountryCode: 大陆的新北区/连江县/北海市/邢台南和区不许被判成境外", () => {
  for (const loc of [
    "江苏省·常州市·新北区", "常州市-新北区",
    "福建省·福州市·连江县",
    "广西壮族自治区·北海市", "北海市-银海区",
    "河北省·邢台市·南和区", "邢台南和区",
    // 一岗多地写法混进外国国名，仍判中国（JP/KR 刻意排在 CN 后面）
    "青岛市、日本、潍坊市", "长沙市,铜仁市,钦州市,印度尼西亚,贵阳市,韩国",
  ]) {
    assert.equal(deriveCountryCode(loc), "CN", loc);
    assert.equal(locationInScope(loc, ["CN"]), true, loc);
  }
});

// 两端词表必须逐条一致：normalizer（Python 爬虫写入）与 lib/jobs-store/write.ts（app 写入）
// 各自算 country_code / job_scope，词表一漂，同一个岗从两条链进来会得到两个归属。
test("geo 词表与 crawler/geo.py 逐条一致", () => {
  const py = fs.readFileSync(path.join(__dirname, "..", "crawler", "geo.py"), "utf8");
  const pick = (name) => {
    const m = py.match(new RegExp(`^${name} = \\(([\\s\\S]*?)^\\)`, "m"));
    assert.ok(m, `crawler/geo.py 里找不到 ${name}`);
    return m[1].replace(/#.*$/gm, "").match(/"([^"]+)"/g).map((s) => s.slice(1, -1));
  };
  for (const name of [
    "CHINA_CJK_PLACE_MARKERS", "TAIWAN_CJK_MARKERS", "JAPAN_CJK_MARKERS", "KOREA_CJK_MARKERS",
  ]) {
    assert.deepEqual(geo[name], pick(name), `${name} 与 crawler/geo.py 不一致`);
  }
});

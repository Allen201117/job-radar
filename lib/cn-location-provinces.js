// 省级归属解析 + location 切段（2026-09-23 从 lib/geo.js 拆出，逻辑逐字未改）。
//
// 为什么单独成文件：/jobs 城市筛选、打分、校招「对你有货」都要按省判 location，而 job-filter / scoring /
// campus-facets 同时被客户端组件引用——直接 require("./geo") 会把整份 geo.js（52KB 词表）打进 /jobs /campus
// /today /saved 的首屏包（实测 First Load JS 各 +16kB），浏览器端却一次都不调这些函数。
// 这里只放省级解析与它依赖的切段；lib/geo.js 从这里取同一份 SEGMENT_SPLIT_RE / segments 并原样再导出，
// 对外 API 不变，crawler/geo.py 的对拍口径也不变（_SEGMENT_SPLIT_RE / location_provinces）。
// ⚠️ 本文件不许 require("./geo")：一旦反向依赖，浏览器包又会把 geo.js 整份带回去。

const SEGMENT_SPLIT_RE = /[·・.。,，、;；:：/／\\|｜\-—–－~～()（）\[\]【】{}《》<>\s]+/;

function segments(text) {
  return String(text || "").trim().split(SEGMENT_SPLIT_RE).filter(Boolean);
}

// ---------------------------------------------------------------------------
// 省级归属：岗位 location 落在哪几个省级行政区（2026-09-23 加，给 /today 城市门把「陕西」展开成全省用）。
// ⚠️ 与 crawler/geo.py 的 location_provinces 逐条同口径；映射本体 lib/cn-province-prefectures.json 两端共读，
//    逐条用例在 tests/fixtures/cn-location-provinces.json 两端共测。
//
// 为什么不是「location 含该省任一地级名」一条子串：全库在招 8,107 种 location 写法逐条对拍，裸子串会把
//   「大连市-中山区」判给广东、「安徽省·马鞍山市」判给辽宁（鞍山）、「天津-河北区」判给河北、
//   「内蒙古自治区·乌海市·海南区」判给海南、「黑河-五大连池市」判给辽宁（大连）。
// 下面每条规则都对应一个实测反例：
//   ① 按分隔符切段，**每段只认第一个地名**：「北京市朝阳区」认出北京就停，朝阳（辽宁）不再参与；
//   ② 同一位置取最长名：「马鞍山」压过「鞍山」、「大兴安岭」压过「兴安」、「海南藏族」压过「海南」；
//   ③ 地名必须在段首或行政后缀之后：「五大连池」「峨眉山」里的大连 / 眉山不算；
//   ④ 紧跟「区」的是同名市辖区不是这个地级单位（天津河北区 / 乌海海南区 / 大连中山区 / 大庆大同区），「区域」除外；
//      紧跟「县」的只有跨省重名的几个不认（见 JSON 的 _county_collisions），「南昌县」「澄迈县」照认；
//   ⑤ 紧跟「路 / 街」是街道名（南京路 / 中山路）。
// 县级市（昆山 / 义乌 / 顺德）不收：与上面 CN_ADMIN_NAMES「县区级不收」同一取舍，收了只会放大同名风险。
// ---------------------------------------------------------------------------
const CN_PROVINCE_DATA = require("./cn-province-prefectures.json");
const CN_PROVINCE_PREFECTURES = CN_PROVINCE_DATA.provinces;
const PLACE_PROVINCE = new Map();
for (const m of CN_PROVINCE_DATA.municipalities) PLACE_PROVINCE.set(m, m);
for (const [province, list] of Object.entries(CN_PROVINCE_PREFECTURES)) {
  PLACE_PROVINCE.set(province, province);
  for (const name of list) PLACE_PROVINCE.set(name, province);
}
for (const [name, province] of Object.entries(CN_PROVINCE_DATA._disambiguation)) PLACE_PROVINCE.set(name, province);
// 首字 → 以它开头的地名（长的在前）：每个位置只比同首字的几个名字，不扫全表。
const PLACE_NAMES_BY_HEAD = new Map();
for (const name of [...PLACE_PROVINCE.keys()].sort((a, b) => b.length - a.length)) {
  if (!PLACE_NAMES_BY_HEAD.has(name[0])) PLACE_NAMES_BY_HEAD.set(name[0], []);
  PLACE_NAMES_BY_HEAD.get(name[0]).push(name);
}
const COUNTY_COLLISIONS = new Set(CN_PROVINCE_DATA._county_collisions.names);
const PLACE_BOUNDARY_BEFORE = new Set(["省", "市", "州", "盟", "区", "县", "旗", "国"]);

function segmentProvince(seg) {
  for (let i = 0; i < seg.length; i++) {
    if (i > 0 && !PLACE_BOUNDARY_BEFORE.has(seg[i - 1])) continue;
    const name = (PLACE_NAMES_BY_HEAD.get(seg[i]) || []).find((n) => seg.startsWith(n, i));
    if (!name) continue;
    const next = seg[i + name.length];
    if (next === "区" && seg[i + name.length + 1] !== "域") continue;
    if (next === "县" && COUNTY_COLLISIONS.has(name)) continue;
    if (next === "路" || next === "街") continue;
    return PLACE_PROVINCE.get(name);
  }
  return null;
}

/** location 落在哪些省级行政区（省短名 / 直辖市 / 港澳），按出现顺序去重；认不出返回 []。 */
function locationProvinces(location) {
  const out = [];
  for (const seg of segments(location)) {
    const province = segmentProvince(seg);
    if (province && !out.includes(province)) out.push(province);
  }
  return out;
}

/** 解析器会判给该省的全部地名（省名 + 地级短名 + 全称消歧名）。召回 SQL 的城市门用它，保证是 locationProvinces 的超集。 */
function chinaProvincePlaceNames(province) {
  if (!CN_PROVINCE_PREFECTURES[province]) return [];
  return [...PLACE_PROVINCE.entries()].filter(([, p]) => p === province).map(([name]) => name);
}

module.exports = {
  SEGMENT_SPLIT_RE,
  segments,
  CN_PROVINCE_PREFECTURES,
  locationProvinces,
  chinaProvincePlaceNames,
};

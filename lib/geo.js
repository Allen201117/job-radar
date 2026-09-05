const CHINA_LOCATION_MARKERS = [
  "china", "中国", "prc", "greater china",
  // ISO-2 国家码；与 crawler/geo.py 的 CHINA_LOCATION_MARKERS 逐条一致（改一边必须改另一边）。
  // 外企 ATS 的 location.country 给小写国别码，城市却是空格分词拼音（"He Fei Shi"），
  // 拼音表按词边界一个都对不上，中国岗会被当成非中国岗丢掉。
  // 全库含独立 "cn" 词的 active 岗现判定 100% 已是 CN，加它零误伤。
  "cn",
  "beijing", "shanghai", "shenzhen", "guangzhou", "hangzhou", "chengdu",
  "nanjing", "suzhou", "wuhan", "xi'an", "xian", "foshan", "dongguan",
  "tianjin", "chongqing", "wuxi", "ningbo", "qingdao", "dalian", "xiamen",
  "hefei", "changsha", "zhengzhou", "jinan", "kunming", "shijiazhuang",
  "changchun", "harbin", "shenyang", "nanchang", "fuzhou", "nanning",
  "guiyang", "lanzhou", "taiyuan", "wenzhou", "zhuhai", "yantai", "xuzhou",
  "changzhou", "nantong", "weifang", "luoyang", "huizhou",
  "jiangsu", "zhejiang", "guangdong", "sichuan", "shandong", "henan",
  "hebei", "hunan", "hubei", "anhui", "fujian", "jiangxi", "liaoning",
  "shaanxi", "shanxi", "yunnan", "guizhou", "gansu", "hainan", "jilin",
  "heilongjiang", "qinghai", "ningxia", "xinjiang", "guangxi",
  "nei mongol", "inner mongolia",
  "北京", "上海", "深圳", "广州", "杭州", "成都", "南京", "苏州", "武汉", "西安", "佛山",
  "天津", "重庆", "无锡", "宁波", "青岛", "大连", "厦门", "合肥", "长沙", "郑州",
  "hong kong", "香港", "macau", "macao", "澳门",
];

const COUNTRY_TOKENS = {
  HK: ["hong kong", "香港", "hongkong"],
  MO: ["macau", "macao", "澳门"],
  CN: CHINA_LOCATION_MARKERS.filter((m) => !["hong kong", "香港", "macau", "macao", "澳门"].includes(m)),
  US: [
    "united states", "usa", "u.s.", "u.s.a", "america", "us",
    "new york", "纽约", "san francisco", "旧金山", "sf bay", "bay area",
    "seattle", "西雅图", "sunnyvale", "mountain view", "cupertino", "san jose",
    "santa clara", "palo alto", "austin", "boston", "chicago", "los angeles",
    "washington", "atlanta", "denver", "dallas", "houston", "san diego",
    "redmond", "menlo park", ", ca", ", ny", ", wa", ", tx", ", ma",
  ],
  SG: ["singapore", "sg", "新加坡"],
};

const GREATER_CHINA = new Set(["CN", "HK", "MO"]);
const REMOTE_MARKERS = ["remote", "anywhere", "distributed", "work from home", "wfh", "远程", "远端"];
const CJK_RE = /[\u4e00-\u9fff]/;

function norm(text) {
  return String(text || "").trim().toLowerCase();
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function containsToken(text, token) {
  if (CJK_RE.test(token) || token.startsWith(",")) {
    return text.includes(token);
  }
  const parts = token.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean).map(escapeRegExp);
  if (!parts.length) {
    return false;
  }
  return new RegExp(`(?<![a-z0-9])${parts.join("[^a-z0-9]+")}(?![a-z0-9])`).test(text);
}

function isRemoteLocation(location) {
  const text = norm(location);
  return REMOTE_MARKERS.some((marker) => text.includes(marker));
}

function deriveCountryCode(location) {
  const text = norm(location);
  if (!text || text === "unknown" || text === "multiple locations") {
    return null;
  }
  for (const [code, tokens] of Object.entries(COUNTRY_TOKENS)) {
    if (tokens.some((token) => containsToken(text, token))) {
      return code;
    }
  }
  return null;
}

// sources.regions 归一：supabase-js 把 text[] 解析成数组，但 PG 数组字面量字符串 "{CN,US}"
// 也可能一路传到这里 —— 与 crawler/normalizer.source_regions 同口径地剥 {}、切逗号、trim。
// ⚠️ 不能直接 Array.from(字符串)：那会切成单个字符，"CN" 变 ["C","N"] 后判不出 CN。
function normalizeRegions(regions) {
  if (!regions) return [];
  let list;
  if (Array.isArray(regions)) {
    list = regions;
  } else if (typeof regions === "string") {
    const text = regions.trim();
    const inner = text.startsWith("{") && text.endsWith("}") ? text.slice(1, -1) : text;
    list = inner.split(",");
  } else {
    list = Array.from(regions);
  }
  return list.map((r) => String(r).trim()).filter(Boolean);
}

/**
 * domestic = 大中华（CN/HK/MO），其余 overseas。与 crawler/geo.py 的 derive_job_scope 同口径，
 * 改一处必须两处同改（tests/geo-cross-lang.test.js 会拿同一批用例对拍两端）。
 *
 * 地点**抽不出国家**时（空 / "Multiple Locations" / 裸「远程」「Remote」），按**源自己的
 * regions** 兜底判定；没传 regions 则维持旧默认 domestic，故老调用方行为一字不变。
 *
 * ⚠️ 为什么必须看源：裸「远程」默认判 domestic 是**海外扩展之前**的合理默认（那时库里只有
 * CN 源，远程岗几乎必然在国内）。2026-07-02 放开 US/SG/Remote 之后这个默认就反了 ——
 * 2026-09-05 香港库实测：「location 抽不出国家」的在招岗里，源含 CN 的 114,075 个全是
 * domestic、源不含 CN 的 16,159 个全是 overseas（Wells Fargo 4,419 / Target 3,670 /
 * JLL 1,945 / AbbVie 1,512…），交叉项 0 个 —— 按源判是干净的。
 * （带国家写法的远程「Remote - US」早已由 f306271 修好，这里补的是**裸远程**那一半。）
 */
function deriveJobScope(location, regions) {
  const code = deriveCountryCode(location);
  if (code) {
    return GREATER_CHINA.has(code) ? "domestic" : "overseas";
  }
  const scoped = normalizeRegions(regions);
  if (scoped.length && !scoped.includes("CN")) {
    return "overseas";
  }
  return "domestic";
}

function locationInScope(location, regions) {
  const regionSet = new Set((regions && regions.length ? regions : ["CN"]).map(String));
  const code = deriveCountryCode(location);
  if (code) {
    if (regionSet.has(code)) return true;
    if (regionSet.has("CN") && GREATER_CHINA.has(code)) return true;
    return false;
  }
  if (isRemoteLocation(location)) {
    return regionSet.has("Remote") || regionSet.has("CN");
  }
  return false;
}

module.exports = {
  deriveCountryCode,
  deriveJobScope,
  locationInScope,
  normalizeRegions,
};

const CHINA_LOCATION_MARKERS = [
  "china", "中国", "prc", "greater china",
  // ISO-2 国家码；与 crawler/geo.py 的 CHINA_LOCATION_MARKERS 保持逐条一致（改一边必须改另一边）。
  // 外企 ATS 的 location.country 给小写国别码，城市却是空格分词拼音（"He Fei Shi"），拼音表按
  // 词边界一个都对不上。全库含独立 "cn" 词的 active 岗现判定 100% 已是 CN，加它零误伤。
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

/**
 * 与 crawler/geo.py 的 derive_job_scope 同口径（改一边必须改另一边）。
 *
 * ⚠️ 没写国家的远程岗算 overseas，不算 domestic：live 实测全库 9,873 个地点为「远程」的
 * active 岗里一个中国岗都没有（全是外企 ATS），旧规则等于把外企远程岗当中国供给。
 * 同时这让 lib/job-scope.ts 的 Remote 档第一次真的能命中——它要求
 * `job_scope='overseas' && country_code == null`，旧规则永远产不出这个组合。
 * 地点为空仍算 domestic：本土 ATS 大量岗位不填地点，推去海外会让国内看板凭空少岗。
 */
function deriveJobScope(location) {
  const code = deriveCountryCode(location);
  if (!code) {
    return isRemoteLocation(location) ? "overseas" : "domestic";
  }
  return GREATER_CHINA.has(code) ? "domestic" : "overseas";
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
};

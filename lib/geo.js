const CHINA_LOCATION_MARKERS = [
  "china", "中国", "prc", "greater china",
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
  // ⚠️ TW 必须排在 CN 前面（Object.entries 按插入序遍历，先命中先返回），与 crawler/geo.py
  // 的 _COUNTRY_TOKENS 同口径、同顺序 —— 改一处必须两处同改。
  // 台湾按项目口径**不抓、不归入任一范围**：TW ∉ 任何 source regions 且 TW ∉ GREATER_CHINA，
  // 于是 locationInScope 一律 false、deriveJobScope 落 overseas（= 不进国内看板）。
  // 此前 TW 压根不在本表里（Python 侧 2026-07-28 已补、JS 侧漏了）→ "Taiwan, Province of China"
  // 这种写法因为含 "china" 被判成 CN，经 lib/jobs-store/write.ts 的 withDerivedFields 写进库
  // 就是「台湾岗挂 CN/domestic 进国内看板」，正是 Python 侧当年修掉的那个洞。
  TW: ["taiwan", "台湾", "臺灣", "taipei", "台北", "臺北", "kaohsiung", "高雄", "hsinchu", "新竹"],
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

function deriveJobScope(location) {
  const code = deriveCountryCode(location);
  if (!code) {
    return "domestic";
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
  // 导出给 tests/geo.test.js 与 crawler/geo.py 的 TW 字面量做对拍（防两端再次漂移）
  COUNTRY_TOKENS,
  deriveCountryCode,
  deriveJobScope,
  locationInScope,
};

// 中文地名词表（省级 + 地级行政区，不含后缀）。⚠️ 必须与 crawler/geo.py 的
// CHINA_CJK_PLACE_MARKERS 逐条一致（改一边必须改另一边）。
//
// 为什么显式列名而不是「含 省/市/区/县/自治州 → 中国」一条规则：那条规则能覆盖 84% 的缺口，
// 但会把「新北市 / 大阪市 / 東京都 / 首尔市」一起判成中国。台湾按项目口径不抓、不归入任一范围。
// 县区级不收 ——「保定市-莲池区」靠上级前缀命中即可，收县区只会放大同名风险。
const CHINA_CJK_PLACE_MARKERS = [
  "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东",
  "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "内蒙古", "内蒙", "广西", "西藏", "宁夏", "新疆", "石家庄", "唐山",
  "秦皇岛", "邯郸", "邢台", "保定", "张家口", "承德", "沧州", "廊坊", "衡水", "雄安", "太原", "大同", "阳泉", "长治", "晋城",
  "朔州", "晋中", "运城", "忻州", "临汾", "吕梁", "呼和浩特", "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔", "巴彦淖尔",
  "乌兰察布", "兴安盟", "锡林郭勒", "阿拉善", "沈阳", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新", "辽阳", "盘锦",
  "铁岭", "朝阳", "葫芦岛", "长春", "四平", "辽源", "通化", "白山", "松原", "白城", "延边", "哈尔滨", "齐齐哈尔", "鸡西", "鹤岗",
  "双鸭山", "大庆", "伊春", "佳木斯", "七台河", "牡丹江", "黑河", "绥化", "大兴安岭", "徐州", "常州", "南通", "连云港", "淮安",
  "盐城", "扬州", "镇江", "泰州", "宿迁", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水", "芜湖",
  "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山", "滁州", "阜阳", "宿州", "六安", "亳州", "池州", "宣城", "福州",
  "莆田", "三明", "泉州", "漳州", "南平", "龙岩", "宁德", "南昌", "景德镇", "萍乡", "九江", "新余", "鹰潭", "赣州", "吉安",
  "宜春", "抚州", "上饶", "济南", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安", "威海", "日照", "临沂", "德州",
  "聊城", "滨州", "菏泽", "开封", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳", "许昌", "漯河", "三门峡", "南阳", "商丘",
  "信阳", "周口", "驻马店", "济源", "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州", "黄冈", "咸宁", "随州",
  "恩施", "仙桃", "潜江", "天门", "神农架", "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳", "郴州", "永州",
  "怀化", "娄底", "湘西", "韶关", "珠海", "汕头", "江门", "湛江", "茂名", "肇庆", "惠州", "梅州", "汕尾", "河源", "阳江",
  "清远", "东莞", "中山", "潮州", "揭阳", "云浮", "南宁", "柳州", "桂林", "梧州", "防城港", "钦州", "贵港", "玉林", "百色",
  "贺州", "河池", "来宾", "崇左", "海口", "三亚", "三沙", "儋州", "琼海", "文昌", "万宁", "五指山", "自贡", "攀枝花", "泸州",
  "德阳", "绵阳", "广元", "遂宁", "内江", "乐山", "南充", "眉山", "宜宾", "广安", "达州", "雅安", "巴中", "资阳", "阿坝",
  "甘孜", "凉山", "贵阳", "六盘水", "遵义", "安顺", "毕节", "铜仁", "黔西南", "黔东南", "黔南", "昆明", "曲靖", "玉溪", "保山",
  "昭通", "丽江", "普洱", "临沧", "楚雄", "红河", "文山", "西双版纳", "大理", "德宏", "怒江", "迪庆", "拉萨", "日喀则", "昌都",
  "林芝", "山南", "那曲", "铜川", "宝鸡", "咸阳", "渭南", "延安", "汉中", "榆林", "安康", "商洛", "兰州", "嘉峪关", "金昌",
  "天水", "武威", "张掖", "平凉", "酒泉", "庆阳", "定西", "陇南", "临夏", "甘南", "西宁", "海东", "海北", "黄南", "果洛",
  "玉树", "海西", "银川", "石嘴山", "吴忠", "固原", "中卫", "乌鲁木齐", "克拉玛依", "吐鲁番", "哈密", "昌吉", "博尔塔拉", "巴音郭楞",
  "阿克苏", "克孜勒苏", "喀什", "和田", "伊犁", "塔城", "阿勒泰", "石河子", "北海市", "东方市", "白银市", "全国",
];

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
  ...CHINA_CJK_PLACE_MARKERS,
  "hong kong", "香港", "macau", "macao", "澳门",
];

// 港澳台日韩中文地名。⚠️ 与 crawler/geo.py 的 TAIWAN/JAPAN/KOREA_CJK_MARKERS 逐条一致。
// 收词按「宁可漏判、不可错杀」：漏判一个台湾岗只是回到 code=null（非远程照样被 locationInScope
// 丢掉，无害）；错判一个大陆岗为台湾则是把在招岗静默删掉。所以有重叠风险的只收
// 「繁体裸名」+「简体带后缀名」：常州有新北区 → 只收「新北市」；福州有连江县 → 只收繁体「連江」。
const TAIWAN_CJK_MARKERS = [
  "台湾", "臺灣", "台灣", "臺湾", "台北", "臺北", "高雄", "新竹", "基隆", "苗栗", "彰化", "南投", "花莲", "花蓮", "澎湖",
  "嘉義", "嘉义市", "嘉义县", "新北市", "桃園", "桃园市", "臺中", "台中市", "臺南", "台南市", "臺東", "台东县", "雲林", "云林县",
  "屏東", "屏东县", "宜蘭", "宜兰县", "金門", "金门县", "連江",
];

const JAPAN_CJK_MARKERS = [
  "日本", "东京", "東京", "大阪", "京都", "横滨", "橫濱", "横浜", "名古屋", "神户", "神戶", "神戸", "札幌", "仙台", "川崎",
  "福冈", "福岡", "广岛", "廣島", "広島", "长崎", "長崎", "熊本", "静冈", "静岡", "新潟", "奈良", "千叶", "千葉", "埼玉",
  "神奈川", "兵库", "兵庫", "爱知", "愛知", "北海道", "冲绳", "沖繩", "沖縄", "横须贺", "橫須賀",
];

// ⚠️ 刻意不收「大田」「光州」「汉城」：福建有大田县、河南潢川古称光州、「武汉城市圈」含「汉城」。
const KOREA_CJK_MARKERS = [
  "韩国", "韓國", "首尔", "首爾", "釜山", "仁川", "大邱", "蔚山", "京畿道", "济州", "濟州",
];

const COUNTRY_TOKENS = {
  // ⚠️ TW 必须排在 CN 前面（对象按插入序遍历，先命中先返回）：「Taipei, Taiwan, Province of
  // China」含 "china"，排在 CN 后会被判成大陆放行。台湾 ∉ 任何 source regions 且 ∉ GREATER_CHINA。
  TW: ["taiwan", "taipei", "kaohsiung", "hsinchu", ...TAIWAN_CJK_MARKERS],
  HK: ["hong kong", "香港", "hongkong"],
  MO: ["macau", "macao", "澳门"],
  CN: CHINA_LOCATION_MARKERS.filter((m) => !["hong kong", "香港", "macau", "macao", "澳门"].includes(m)),
  // ⚠️ JP / KR 相反，必须排在 CN **后面**：「青岛市、日本、潍坊市」这类一岗多地写法要保住 CN，
  // 不能因为多写了一个国名就把中国岗翻成海外。纯日韩写法不含中国地名，排在后面照样命中。
  JP: JAPAN_CJK_MARKERS,
  KR: KOREA_CJK_MARKERS,
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
  deriveCountryCode,
  deriveJobScope,
  locationInScope,
  // 导出词表只为 tests/geo.test.js 的「与 crawler/geo.py 逐条一致」对拍，业务代码别用。
  CHINA_CJK_PLACE_MARKERS,
  TAIWAN_CJK_MARKERS,
  JAPAN_CJK_MARKERS,
  KOREA_CJK_MARKERS,
};

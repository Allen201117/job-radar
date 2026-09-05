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
  "林芝", "山南", "那曲", "铜川", "宝鸡",
  // ⚠️「咸阳」只收带「市」的写法：韩国庆尚南道有咸阳郡，本表是子串匹配且 CN 排在 KR 前面。
  // 裸写「咸阳」的陕西岗由 CN_ADMIN_NAMES 的整段白名单兜住。与 crawler/geo.py 同口径。
  "咸阳市",
  "渭南", "延安", "汉中", "榆林", "安康", "商洛", "兰州", "嘉峪关", "金昌",
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
  // ⚠️「新界」「九龙」不能放本表：这里的中文 token 是**子串**匹配，重庆有九龙坡区
  // （线上 30 个岗），一放进来「重庆市-九龙坡区」就被判成香港。它们在 STRICT_CJK_PLACES 里 ——
  // 与 TAIWAN_CJK_MARKERS 只收「新北市」不收「新北」是同一条取舍。
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
    "redmond", "menlo park",
    // ⚠️ 这里**不要**再放 ", ca" / ", ny" / ", wa" 这类「逗号+州缩写」的 token：
    // 以 "," 开头的 token 在 containsToken 里走的是**裸子串**，", ca" 会命中 ", Capital"、
    // ", ma" 命中 ", Manulife" / ", Maharashtra"、", wa" 命中 ", Wan" —— 线上实测把
    // 蒙特利尔/多伦多/华沙/孟买的岗判成美国，其中还有香港地址。
    // 州缩写改由下面 US_STATE_* 那套「位置受限 + 必须大写」的规则处理。
  ],
  SG: ["singapore", "sg", "新加坡"],
};

const GREATER_CHINA = new Set(["CN", "HK", "MO"]);

// ---------------------------------------------------------------------------
// 中文行政区地名识别 —— 与 crawler/geo.py 的同名表**逐条一致，改一边必须改另一边**。
// 完整的「为什么」与红线（新北市/大阪市/首尔市 不许判 CN；新北区/延边朝鲜族/九龙坡区
// 不许判成境外）写在 crawler/geo.py 中部那一大段注释里，此处不重复。
// 匹配顺序：① COUNTRY_TOKENS ② STRICT_CJK_PLACES（境外，整段精确）③ 中文行政区通用规则。
// ②必须在③之前，否则「大阪市」会被③的后缀规则抢走判成 CN。
// ---------------------------------------------------------------------------

const SEGMENT_SPLIT_RE = /[·・.。,，、;；:：/／\\|｜\-—–－~～()（）\[\]【】{}《》<>\s]+/;

const STRICT_CJK_PLACES = {
  "HK": [
    "新界", "九龙", "九龍", "香港岛", "香港島",
  ],
  "TW": [
    "台湾", "臺灣", "台湾省", "中国台湾", "新北市", "台中市", "臺中市", "台南市", "臺南市", "桃园市", "桃園市", "基隆市", "新竹市",
    "新竹县", "嘉义市", "嘉義市", "嘉义县", "彰化县", "彰化縣", "宜兰县", "宜蘭縣", "花莲县", "花蓮縣", "屏东县", "屏東縣", "苗栗县",
    "苗栗縣", "南投县", "南投縣", "云林县", "雲林縣", "澎湖县", "金门县", "金門縣", "台东县", "臺東縣",
  ],
  "JP": [
    "日本", "东京", "東京", "东京都", "東京都", "大阪", "大阪市", "大阪府", "京都", "京都市", "京都府", "横滨", "橫濱", "横滨市",
    "名古屋", "名古屋市", "札幌", "札幌市", "神户", "神戶", "神户市", "福冈", "福岡", "福冈市", "广岛", "廣島", "广岛市", "仙台",
    "仙台市", "千叶", "千葉", "千叶市", "千叶县", "埼玉", "埼玉县", "川崎", "川崎市", "北九州", "北九州市", "静冈", "静冈县",
    "新潟", "熊本", "长崎", "長崎", "冲绳", "沖繩", "冲绳县", "奈良", "神奈川", "神奈川县",
  ],
  "KR": [
    "韩国", "韓國", "南韩", "首尔", "首爾", "首尔市", "首尔特别市", "汉城", "釜山", "釜山市", "釜山广域市", "仁川", "仁川市",
    "仁川广域市", "大邱广域市", "光州广域市", "大田广域市", "蔚山", "蔚山市", "蔚山广域市", "世宗市", "世宗特别自治市", "京畿道", "忠清北道",
    "忠清南道", "全罗北道", "全罗南道", "庆尚北道", "庆尚南道", "江原道", "济州道", "济州特别自治道",
  ],
  "KP": [
    "朝鲜民主主义人民共和国", "北朝鲜", "平壤", "平壤市",
  ],
  "VN": [
    "越南", "胡志明市", "胡志明", "河内", "河内市", "岘港", "海防市",
  ],
  "TH": [
    "泰国", "曼谷", "曼谷市", "清迈",
  ],
  "MY": [
    "马来西亚", "吉隆坡", "槟城", "柔佛",
  ],
  "ID": [
    "印度尼西亚", "印尼", "雅加达", "泗水",
  ],
  "PH": [
    "菲律宾", "马尼拉",
  ],
  "IN": [
    "印度", "新德里", "孟买", "班加罗尔",
  ],
  "AE": [
    "阿联酋", "迪拜", "杜拜", "阿布扎比",
  ],
  "US": [
    "美国", "圣何塞", "帕罗奥多", "帕洛阿尔托", "洛杉矶", "森尼韦尔", "圣克拉拉", "贝尔维尤", "费利蒙", "山景城", "尔湾", "奥斯汀",
    "布鲁克林", "萨克拉门托", "华盛顿哥伦比亚特区",
  ],
  "GB": [
    "英国", "伦敦", "莱斯特",
  ],
  "DE": [
    "德国", "慕尼黑", "柏林", "杜塞尔多夫", "法兰克福", "斯图加特",
  ],
  "FR": [
    "法国", "巴黎",
  ],
  "NL": [
    "荷兰", "阿姆斯特丹", "鹿特丹", "霍夫多尔普",
  ],
  "ES": [
    "西班牙", "马德里",
  ],
  "IT": [
    "意大利", "米兰", "罗马",
  ],
  "PL": [
    "波兰", "华沙",
  ],
  "RU": [
    "俄罗斯", "俄罗斯联邦", "莫斯科",
  ],
  "MX": [
    "墨西哥", "墨西哥城", "瓜达拉哈拉",
  ],
  "BR": [
    "巴西", "圣保罗", "巴西利亚",
  ],
  "SA": [
    "沙特阿拉伯", "利雅得", "艾卜哈",
  ],
  "TR": [
    "土耳其", "伊斯坦布尔",
  ],
  "AU": [
    "澳大利亚", "悉尼", "墨尔本", "布里斯班",
  ],
  "CA": [
    "加拿大", "多伦多", "温哥华",
  ],
  "ZA": [
    "南非", "约翰内斯堡",
  ],
  "EG": [
    "埃及", "开罗",
  ],
  "NG": [
    "尼日利亚", "拉各斯",
  ],
  "KE": [
    "肯尼亚", "内罗毕", "奈洛比",
  ],
  "KZ": [
    "哈萨克斯坦", "阿拉木图", "阿斯塔纳",
  ],
  "UZ": [
    "乌兹别克斯坦", "塔什干",
  ],
  "TJ": [
    "塔吉克斯坦",
  ],
  "KG": [
    "吉尔吉斯斯坦",
  ],
  "PK": [
    "巴基斯坦", "拉合尔",
  ],
  "BD": [
    "孟加拉", "孟加拉国", "达卡",
  ],
  "LK": [
    "斯里兰卡",
  ],
  "KH": [
    "柬埔寨", "金边",
  ],
  "LA": [
    "老挝", "万象",
  ],
  "MM": [
    "缅甸", "仰光",
  ],
  "BN": [
    "文莱",
  ],
  "MN": [
    "蒙古国",
  ],
  "ZW": [
    "津巴布韦",
  ],
  "GN": [
    "几内亚",
  ],
  "MA": [
    "摩洛哥", "卡萨布兰卡",
  ],
  "HU": [
    "匈牙利", "布达佩斯",
  ],
  "CZ": [
    "捷克", "布拉格", "布拉格直辖市",
  ],
  "SK": [
    "斯洛伐克",
  ],
  "SI": [
    "斯洛文尼亚",
  ],
  "RO": [
    "罗马尼亚", "布加勒斯特",
  ],
  "RS": [
    "塞尔维亚", "贝尔格莱德",
  ],
  "BG": [
    "保加利亚", "索非亚",
  ],
  "GR": [
    "希腊", "雅典",
  ],
  "PT": [
    "葡萄牙", "里斯本",
  ],
  "SE": [
    "瑞典", "斯德哥尔摩",
  ],
  "NO": [
    "挪威", "奥斯陆",
  ],
  "DK": [
    "丹麦", "哥本哈根", "巴勒鲁普",
  ],
  "FI": [
    "芬兰", "赫尔辛基",
  ],
  "IE": [
    "爱尔兰", "都柏林",
  ],
  "AT": [
    "奥地利", "维也纳", "格拉茨",
  ],
  "CH": [
    "瑞士", "苏黎世", "日内瓦",
  ],
  "BE": [
    "比利时", "列日", "梅赫伦", "布鲁塞尔",
  ],
  "LU": [
    "卢森堡",
  ],
  "UA": [
    "乌克兰", "基辅",
  ],
  "BY": [
    "白俄罗斯", "明斯克",
  ],
  "LV": [
    "拉脱维亚",
  ],
  "EE": [
    "爱沙尼亚",
  ],
  "IL": [
    "以色列", "特拉维夫",
  ],
  "AR": [
    "阿根廷", "布宜诺斯艾利斯",
  ],
  "CL": [
    "智利", "圣地亚哥",
  ],
  "PE": [
    "秘鲁", "利马",
  ],
  "CO": [
    "哥伦比亚", "波哥大",
  ],
  "UY": [
    "乌拉圭",
  ],
  "VE": [
    "委内瑞拉",
  ],
  "PA": [
    "巴拿马",
  ],
  "NI": [
    "尼加拉瓜", "马那瓜",
  ],
  "EC": [
    "厄瓜多尔", "基多",
  ],
  "DZ": [
    "阿尔及利亚",
  ],
  "TZ": [
    "坦桑尼亚",
  ],
  "ZM": [
    "赞比亚",
  ],
  "ET": [
    "埃塞俄比亚",
  ],
  "GH": [
    "加纳",
  ],
  "CI": [
    "科特迪瓦", "阿比让",
  ],
  "CM": [
    "喀麦隆",
  ],
  "SN": [
    "塞内加尔",
  ],
  "ML": [
    "马里",
  ],
  "AO": [
    "安哥拉", "罗安达", "罗安达市",
  ],
  "CD": [
    "刚果民主共和国", "金沙萨",
  ],
  "CG": [
    "刚果",
  ],
  "GA": [
    "加蓬",
  ],
  "UG": [
    "乌干达",
  ],
  "SL": [
    "塞拉利昂",
  ],
  "LR": [
    "利比里亚",
  ],
  "DJ": [
    "吉布提",
  ],
  "IQ": [
    "伊拉克", "埃尔比勒",
  ],
  "IR": [
    "伊朗", "德黑兰",
  ],
  "KW": [
    "科威特",
  ],
  "QA": [
    "卡塔尔", "多哈",
  ],
  "OM": [
    "阿曼",
  ],
  "JO": [
    "约旦", "安曼",
  ],
  "AZ": [
    "阿塞拜疆", "巴库",
  ],
  "DO": [
    "多米尼加", "圣多明各",
  ],
};

const CN_ADMIN_NAMES = [
  "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东",
  "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾省", "内蒙古", "广西", "西藏",
  "宁夏", "新疆", "内蒙古自治", "广西壮族", "西藏自治", "宁夏回族", "新疆维吾尔", "雄安", "石家庄", "唐山", "秦皇岛", "邯郸", "邢台",
  "保定", "张家口", "承德", "沧州", "廊坊", "衡水", "太原", "大同", "阳泉", "长治", "晋城", "朔州", "晋中", "运城", "忻州",
  "临汾", "吕梁", "呼和浩特", "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔", "巴彦淖尔", "乌兰察布", "兴安", "锡林郭勒",
  "阿拉善", "沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新", "辽阳", "盘锦", "铁岭", "朝阳", "葫芦岛",
  "长春", "四平", "辽源", "通化", "白山", "松原", "白城", "延边", "延边朝鲜族", "哈尔滨", "齐齐哈尔", "鸡西", "鹤岗", "双鸭山",
  "大庆", "伊春", "佳木斯", "七台河", "牡丹江", "黑河", "绥化", "大兴安岭", "南京", "无锡", "徐州", "常州", "苏州", "南通",
  "连云港", "淮安", "盐城", "扬州", "镇江", "泰州", "宿迁", "杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州",
  "舟山", "台州", "丽水", "合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山", "滁州", "阜阳", "宿州",
  "六安", "亳州", "池州", "宣城", "福州", "厦门", "莆田", "三明", "泉州", "漳州", "南平", "龙岩", "宁德", "南昌", "景德镇",
  "萍乡", "九江", "新余", "鹰潭", "赣州", "吉安", "宜春", "抚州", "上饶", "济南", "青岛", "淄博", "枣庄", "东营", "烟台",
  "潍坊", "济宁", "泰安", "威海", "日照", "临沂", "德州", "聊城", "滨州", "菏泽", "郑州", "开封", "洛阳", "平顶山", "安阳",
  "鹤壁", "新乡", "焦作", "濮阳", "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店", "济源", "武汉", "黄石",
  "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州", "黄冈", "咸宁", "随州", "恩施", "恩施土家族苗族", "仙桃", "潜江",
  "天门", "神农架", "长沙", "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳", "郴州", "永州", "怀化", "娄底",
  "湘西", "湘西土家族苗族", "广州", "韶关", "深圳", "珠海", "汕头", "佛山", "江门", "湛江", "茂名", "肇庆", "惠州", "梅州",
  "汕尾", "河源", "阳江", "清远", "东莞", "中山", "潮州", "揭阳", "云浮", "南宁", "柳州", "桂林", "梧州", "北海", "防城港",
  "钦州", "贵港", "玉林", "百色", "贺州", "河池", "来宾", "崇左", "海口", "三亚", "三沙", "儋州", "琼海", "文昌", "万宁",
  "东方", "五指山", "定安", "屯昌", "澄迈", "临高", "陵水", "保亭", "白沙", "昌江", "乐东", "琼中", "成都", "自贡", "攀枝花",
  "泸州", "德阳", "绵阳", "广元", "遂宁", "内江", "乐山", "南充", "眉山", "宜宾", "广安", "达州", "雅安", "巴中", "资阳",
  "阿坝", "甘孜", "凉山", "阿坝藏族羌族", "甘孜藏族", "凉山彝族", "贵阳", "六盘水", "遵义", "安顺", "毕节", "铜仁", "黔西南",
  "黔东南", "黔南", "昆明", "曲靖", "玉溪", "保山", "昭通", "丽江", "普洱", "临沧", "楚雄", "红河", "文山", "西双版纳", "大理",
  "德宏", "怒江", "迪庆", "拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里", "西安", "铜川", "宝鸡", "咸阳", "渭南",
  "延安", "汉中", "榆林", "安康", "商洛", "兰州", "嘉峪关", "金昌", "白银", "天水", "武威", "张掖", "平凉", "酒泉", "庆阳",
  "定西", "陇南", "临夏", "甘南", "临夏回族", "甘南藏族", "西宁", "海东", "海北", "黄南", "果洛", "玉树", "海西", "银川",
  "石嘴山", "吴忠", "固原", "中卫", "乌鲁木齐", "克拉玛依", "吐鲁番", "哈密", "昌吉", "博尔塔拉", "巴音郭楞", "阿克苏", "克孜勒苏",
  "喀什", "和田", "伊犁", "塔城", "阿勒泰", "石河子", "阿拉尔", "图木舒克", "五家渠", "北屯", "铁门关", "双河", "可克达拉", "昆玉",
  "胡杨河", "新星", "昌吉回族", "博尔塔拉蒙古", "巴音郭楞蒙古", "克孜勒苏柯尔克孜", "伊犁哈萨克",
];

const ADMIN_SUFFIXES = [
  "特别行政区", "自治区", "自治州", "自治县", "自治旗", "地区", "新区", "省", "市", "区", "县", "州", "盟", "旗",
];

const NON_PLACE_SEGMENTS = new Set([
  "不限", "不限地区", "全国", "全国各地", "全球", "全球各地", "全部", "全部地区", "其他", "其他地区", "其它", "其它地区", "各地",
  "地点不限", "多地", "异地", "待定", "面议",
]);

const OVERSEAS_UNSPECIFIED_SEGMENTS = new Set([
  "国外", "国外地区", "境外", "境外地区", "海外", "海外国家", "海外地区",
]);

const CN_ADMIN_NAME_SET = new Set(CN_ADMIN_NAMES);
// 民族限定词：「大理白族自治州」「红河哈尼族彝族自治州」。必须以「族」收尾，是中国独有构词。
const CN_ADMIN_RE = new RegExp(
  "(?:" +
    [...CN_ADMIN_NAMES].sort((a, b) => b.length - a.length).map(escapeRegExp).join("|") +
    ")(?:[\\u4e00-\\u9fff]{1,4}族){0,3}(?:" +
    ADMIN_SUFFIXES.join("|") +
    ")",
);

function segments(text) {
  return String(text || "").trim().split(SEGMENT_SPLIT_RE).filter(Boolean);
}

function strictCjkCountry(segs) {
  for (const [code, places] of Object.entries(STRICT_CJK_PLACES)) {
    const set = new Set(places);
    if (segs.some((seg) => set.has(seg))) return code;
  }
  return null;
}

function looksLikeCnAdmin(segs) {
  for (const seg of segs) {
    if (NON_PLACE_SEGMENTS.has(seg) || OVERSEAS_UNSPECIFIED_SEGMENTS.has(seg)) continue;
    if (CN_ADMIN_NAME_SET.has(seg)) return true;
    if (CN_ADMIN_RE.test(seg)) return true;
  }
  return false;
}

// 地点自报「海外」「国外」但没说哪国：没有国家码可给，但 deriveJobScope 必须判 overseas。
function isOverseasUnspecified(location) {
  if (!location) return false;
  return segments(location).some((seg) => OVERSEAS_UNSPECIFIED_SEGMENTS.has(seg));
}

const REMOTE_MARKERS = ["remote", "anywhere", "distributed", "work from home", "wfh", "远程", "远端"];
const CJK_RE = /[\u4e00-\u9fff]/;

// ---------------------------------------------------------------------------
// 美国州名 / 州缩写 —— 与 crawler/geo.py 的 _US_STATE_* 逐条一致，改一边必须改另一边。
// 只在「City, ST」这个位置认缩写，且必须是原串里的**大写**形态：裸认两字母会撞
// IN=印度 / DE=德国 / CA=加拿大 / TN=印度泰米尔纳德邦。整体排在所有词表之后。
// ---------------------------------------------------------------------------

const US_STATE_NAMES = [
  "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
  "connecticut", "delaware", "florida", "idaho", "illinois", "indiana",
  "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland",
  "massachusetts", "michigan", "minnesota", "mississippi", "missouri", "montana",
  "nebraska", "nevada", "new hampshire", "new jersey", "new mexico", "north carolina",
  "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
  "south carolina", "south dakota", "tennessee", "utah", "vermont", "virginia",
  "west virginia", "wisconsin", "wyoming", "puerto rico", "texas",
];

// ⚠️ 刻意不收 "georgia"（与格鲁吉亚同名）；washington / new york 已在上面的 US 词表里。
const US_STATE_CODES = new Set(["AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "PR", "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY"]);

// ZIP+4 要认「逗号分隔」的写法：某个 adapter 会把 "55403-2542" 写成 "55403, 2542"。
const US_STATE_TAIL_RE = /(?:(?<=[,\s])|(?<=[a-z]))([A-Z]{2})\s*,?\s*(?:\d{5}(?:\s*[,-]\s*\d{4})?)?\s*$/;

function hasUsState(location) {
  if (!location) return false;
  const match = US_STATE_TAIL_RE.exec(String(location).trim());
  return Boolean(match) && US_STATE_CODES.has(match[1]);
}

// 州全称并进 US 词表，走 containsToken 的词边界语义（"Mossville, Illinois" 即命中）。
COUNTRY_TOKENS.US.push(...US_STATE_NAMES);

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
  const segs = segments(location);
  // ⚠️ 一岗多地写法（"柳州市、南非"）里**中国优先**：那种岗确实有一部分在国内，
  // 判成境外就把它从国内供给里抹掉。安全前提是 looksLikeCnAdmin 必须**白名单锚定** ——
  // "大阪市"/"新北市"/"首尔市" 里没有大陆地名，命中不了它，照样落到 strictCjkCountry。
  // 与 crawler/geo.py 同口径，改一边必须改另一边。
  if (looksLikeCnAdmin(segs)) return "CN";
  const strict = strictCjkCountry(segs);
  if (strict) return strict;
  // 州缩写排在最后：任何显式国名/城市都优先于它（"Chennai, TN, in" 因此不会判成 US）。
  if (hasUsState(location)) return "US";
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
 * 判定顺序**不能换**（与 Python 逐行对齐）：地点能抽出国家 → 以地点为准；地点自报「海外」
 * 「国外」→ overseas（这一步必须在源兜底之前，否则 CN 源下的「海外」岗会被算成国内供给）；
 * 都不成立才按**源自己的 regions** 兜底；没传 regions 则维持旧默认 domestic，
 * 故老调用方行为一字不变。
 *
 * ⚠️ 为什么必须看源：裸「远程」默认判 domestic 是**海外扩展之前**的合理默认（那时库里只有
 * CN 源，远程岗几乎必然在国内）。2026-07-02 放开 US/SG/Remote 之后这个默认就反了 ——
 * 2026-09-05 香港库实测「location 抽不出国家」的 45,694 个在招岗：源不含 CN 的 4,312 个
 * **全部**是 overseas、一个 domestic 都没有（AbbVie 1,576 / ServiceNow 608 / Ubisoft 272…），
 * 即这条按源判的规则在存量上零反例。
 * （带国家写法的远程「Remote - US」早已由 f306271 修好，这里补的是**裸远程**那一半。）
 */
function deriveJobScope(location, regions) {
  const code = deriveCountryCode(location);
  if (code) {
    return GREATER_CHINA.has(code) ? "domestic" : "overseas";
  }
  // 自报「海外」「国外」的岗不许算成国内供给（与 crawler/geo.py 同口径）。
  if (isOverseasUnspecified(location)) return "overseas";
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
  isOverseasUnspecified,
  locationInScope,
  normalizeRegions,
  // 导出词表只为 tests/geo.test.js 的「与 crawler/geo.py 逐条一致」对拍，业务代码别用。
  CHINA_CJK_PLACE_MARKERS,
  TAIWAN_CJK_MARKERS,
  JAPAN_CJK_MARKERS,
  KOREA_CJK_MARKERS,
};

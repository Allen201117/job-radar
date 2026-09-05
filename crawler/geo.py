import re
from typing import Optional


# 中文地名词表（省级 + 地级行政区，不含后缀）。
#
# ⚠️ 为什么必须显式列名、而不是「地点里含 省/市/区/县/自治州 → 中国」一条规则：
# 那条规则能覆盖 84% 的缺口，但会把 **新北市 / 大阪市 / 東京都 / 首尔市** 一起判成中国 ——
# 台湾按项目口径不抓、不归入任一范围，日韩是海外，一条都不能错。所以只认真实存在的行政区名。
#
# 2026-09-05 实测：库里 27.8 万个「中文地点 + 在招」的岗里 8.3 万个 country_code 为空，
# 因为旧词表的中文标记只有「中国」+21 个一线城市 —— 认得 "Changchun" 却认不得「长春市」。
# 这些岗的国内外归属于是**完全依赖 sources.regions 一个字段**兜底（derive_job_scope 的
# 「抽不出国家就问源」分支）：哪天某个源被放开成 {CN,US}，它名下这批岗会静默翻成 overseas。
#
# 收录口径：省级 34 个（不含台湾）+ 地级市 / 自治州 / 地区 / 盟。**县区级不收**——
# 「保定市-莲池区」「安徽省·芜湖市·鸠江区」靠上级前缀命中即可，收县区只会放大同名风险。
CHINA_CJK_PLACE_MARKERS = (
    # 省级行政区（含简称写法）。台湾不在此列，见 _COUNTRY_TOKENS 的 TW。
    "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建", "江西",
    "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
    "甘肃", "青海", "内蒙古", "内蒙", "广西", "西藏", "宁夏", "新疆",
    # 河北 / 山西
    "石家庄", "唐山", "秦皇岛", "邯郸", "邢台", "保定", "张家口", "承德", "沧州", "廊坊",
    "衡水", "雄安",
    "太原", "大同", "阳泉", "长治", "晋城", "朔州", "晋中", "运城", "忻州", "临汾", "吕梁",
    # 内蒙古 / 东北
    "呼和浩特", "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔", "巴彦淖尔",
    "乌兰察布", "兴安盟", "锡林郭勒", "阿拉善",
    "沈阳", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新", "辽阳", "盘锦",
    "铁岭", "朝阳", "葫芦岛",
    "长春", "四平", "辽源", "通化", "白山", "松原", "白城", "延边",
    "哈尔滨", "齐齐哈尔", "鸡西", "鹤岗", "双鸭山", "大庆", "伊春", "佳木斯", "七台河",
    "牡丹江", "黑河", "绥化", "大兴安岭",
    # 华东
    "徐州", "常州", "南通", "连云港", "淮安", "盐城", "扬州", "镇江", "泰州", "宿迁",
    "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水",
    "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山", "滁州", "阜阳",
    "宿州", "六安", "亳州", "池州", "宣城",
    "福州", "莆田", "三明", "泉州", "漳州", "南平", "龙岩", "宁德",
    "南昌", "景德镇", "萍乡", "九江", "新余", "鹰潭", "赣州", "吉安", "宜春", "抚州", "上饶",
    "济南", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安", "威海", "日照",
    "临沂", "德州", "聊城", "滨州", "菏泽",
    # 华中
    "开封", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳", "许昌", "漯河", "三门峡",
    "南阳", "商丘", "信阳", "周口", "驻马店", "济源",
    "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州", "黄冈", "咸宁",
    "随州", "恩施", "仙桃", "潜江", "天门", "神农架",
    "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳", "郴州", "永州",
    "怀化", "娄底", "湘西",
    # 华南
    "韶关", "珠海", "汕头", "江门", "湛江", "茂名", "肇庆", "惠州", "梅州", "汕尾",
    "河源", "阳江", "清远", "东莞", "中山", "潮州", "揭阳", "云浮",
    "南宁", "柳州", "桂林", "梧州", "防城港", "钦州", "贵港", "玉林", "百色", "贺州",
    "河池", "来宾", "崇左",
    "海口", "三亚", "三沙", "儋州", "琼海", "文昌", "万宁", "五指山",
    # 西南
    "自贡", "攀枝花", "泸州", "德阳", "绵阳", "广元", "遂宁", "内江", "乐山", "南充",
    "眉山", "宜宾", "广安", "达州", "雅安", "巴中", "资阳", "阿坝", "甘孜", "凉山",
    "贵阳", "六盘水", "遵义", "安顺", "毕节", "铜仁", "黔西南", "黔东南", "黔南",
    "昆明", "曲靖", "玉溪", "保山", "昭通", "丽江", "普洱", "临沧", "楚雄", "红河",
    "文山", "西双版纳", "大理", "德宏", "怒江", "迪庆",
    "拉萨", "日喀则", "昌都", "林芝", "山南", "那曲",
    # 西北
    "铜川", "宝鸡",
    # ⚠️「咸阳」只收带「市」的写法：韩国庆尚南道有**咸阳郡**（库里 1 行「韩国·庆尚南道·咸阳郡」），
    # 本表是子串匹配且 CN 排在 KR 前面，裸「咸阳」会把它判成中国。
    # 裸写「咸阳」的 7 个陕西岗由下面 _CN_ADMIN_NAMES 的**整段**白名单兜住，零损失。
    "咸阳市",
    "渭南", "延安", "汉中", "榆林", "安康", "商洛",
    "兰州", "嘉峪关", "金昌", "天水", "武威", "张掖", "平凉", "酒泉", "庆阳", "定西",
    "陇南", "临夏", "甘南",
    "西宁", "海东", "海北", "黄南", "果洛", "玉树", "海西",
    "银川", "石嘴山", "吴忠", "固原", "中卫",
    "乌鲁木齐", "克拉玛依", "吐鲁番", "哈密", "昌吉", "博尔塔拉", "巴音郭楞", "阿克苏",
    "克孜勒苏", "喀什", "和田", "伊犁", "塔城", "阿勒泰", "石河子",
    # ⚠️ 「北海」（广西）必须写成「北海市」：裸「北海」是日本「北海道」的前缀，
    # 而 JP 排在 CN 后面，裸词会让北海道被判成中国。库里 21 个含「北海」的地点
    # 逐个核过，全部写作「北海市」，加后缀零损失（2026-09-05 实测）。
    "北海市",
    # ⚠️ 同理：「东方」（海南）「白银」（甘肃）是常用词，只认带「市」的写法。
    "东方市", "白银市",
    # 非地名、但同样无歧义的「全国性」写法：本土源用它表示「全国各地都招」。
    # 不认它有**现在就在发生的**代价：location_in_scope("全国", {"CN"}) 返回 False，
    # 凡是做地区后置过滤的 adapter 会把这些岗当成「不在 CN 范围」直接丢掉。
    # 库里 2,002 行「全国」逐个核过，全部来自 TCL / 中国一汽 / 三一集团 这类本土公司源
    # （2026-09-05 实测），判 CN 零误伤。⚠️ 「全部地区」「其它」刻意不收 —— 那是筛选器的
    # 占位值不是「全国」，留 None 走「按源 regions 兜底」才是对的。
    "全国",
)

CHINA_LOCATION_MARKERS = (
    "china", "中国", "prc", "greater china",
    # ISO-2 国家码。外企 ATS（SmartRecruiters / Greenhouse 等）的 location.country 直接给
    # 小写国别码，而城市名是**空格分词的拼音**（"He Fei Shi" / "Ning Bo Shi" / "Zhe Jiang Sheng"），
    # 拼音表按词边界一个都对不上 ⇒ derive_country_code 返回 None ⇒ location_in_scope 落
    # 「非远程且无国家」的 False 分支 ⇒ **中国岗被当成非中国岗直接丢弃**。
    # 大陆集团 29 个中国岗里 8 个（28%）就是这么丢的（2026-09-05 live 实测）。
    # 认这个码是**对方自己声明的国别**，不是我们猜的；全库 596 行含独立 "cn" 词的 active 岗
    # 逐行核过，现判定 100% 已经是 CN，加它零误伤。
    "cn",
    # First/new first-tier and major industrial cities. Foreign ATS boards often
    # provide only a city/province name without an explicit "China" suffix.
    "beijing", "shanghai", "shenzhen", "guangzhou", "hangzhou", "chengdu",
    "nanjing", "suzhou", "wuhan", "xi'an", "xian", "foshan", "dongguan",
    "tianjin", "chongqing", "wuxi", "ningbo", "qingdao", "dalian", "xiamen",
    "hefei", "changsha", "zhengzhou", "jinan", "kunming", "shijiazhuang",
    "changchun", "harbin", "shenyang", "nanchang", "fuzhou", "nanning",
    "guiyang", "lanzhou", "taiyuan", "wenzhou", "zhuhai", "yantai", "xuzhou",
    "changzhou", "nantong", "weifang", "luoyang", "huizhou",
    # Provinces/autonomous regions in pinyin.
    "jiangsu", "zhejiang", "guangdong", "sichuan", "shandong", "henan",
    "hebei", "hunan", "hubei", "anhui", "fujian", "jiangxi", "liaoning",
    "shaanxi", "shanxi", "yunnan", "guizhou", "gansu", "hainan", "jilin",
    "heilongjiang", "qinghai", "ningxia", "xinjiang", "guangxi",
    "nei mongol", "inner mongolia",
    "北京", "上海", "深圳", "广州", "杭州", "成都", "南京", "苏州", "武汉", "西安", "佛山",
    "天津", "重庆", "无锡", "宁波", "青岛", "大连", "厦门", "合肥", "长沙", "郑州",
    *CHINA_CJK_PLACE_MARKERS,
    "hong kong", "香港", "macau", "macao", "澳门",
)

_CJK_MARKERS = tuple(m for m in CHINA_LOCATION_MARKERS if any("一" <= ch <= "鿿" for ch in m))
_LATIN_MARKERS = tuple(m for m in CHINA_LOCATION_MARKERS if m not in _CJK_MARKERS)
_LATIN_MARKER_RE = re.compile(r"\b(?:" + "|".join(re.escape(m) for m in _LATIN_MARKERS) + r")\b")

REMOTE_MARKERS = ("remote", "anywhere", "distributed", "work from home", "wfh", "远程", "远端")

OVERSEAS_LOCATION_TOKENS = {
    "usa", "us", "canada", "uk", "britain", "ireland", "germany", "france", "netherlands",
    "spain", "italy", "poland", "portugal", "sweden", "switzerland", "austria", "belgium",
    "europe", "emea", "americas", "latam", "brazil", "mexico", "argentina", "colombia",
    "india", "japan", "korea", "singapore", "malaysia", "thailand", "vietnam", "indonesia",
    "philippines", "australia", "nz", "uae", "dubai", "israel", "egypt", "turkey", "africa",
    # 下面这批是 2026-09-05 补的：外企 ATS（SmartRecruiters）把国家写成 ISO-2 码，adapter 出口
    # 已展开成国名，这里必须认得出来，否则「Remote Romania」这类岗在 regions 含 CN 的源上会被
    # derive_job_scope 的兜底判成 domestic —— 正是 76ce4ff 修掉的那个坑。名单由
    # crawler/adapters/smartrecruiters._ISO2_COUNTRY_NAMES 决定，契约测试逐条对齐。
    "algeria", "bulgaria", "cambodia", "chile", "croatia", "czechia", "denmark", "ecuador",
    "estonia", "finland", "guatemala", "hungary", "latvia", "lithuania", "morocco", "norway",
    "pakistan", "romania", "russia", "serbia", "slovakia", "slovenia", "tunisia", "ukraine",
}
OVERSEAS_LOCATION_PHRASES = (
    "united states", "united kingdom", "new zealand", "south korea", "saudi arabia",
    "sri lanka", "costa rica", "south africa",
    "united arab emirates", "dominican republic", "puerto rico", "aland islands",
)

# 台湾（县市级）。⚠️ 台湾按项目口径**不抓、不归入任一范围**：TW ∉ 任何 source regions
# 且 TW ∉ _GREATER_CHINA，location_in_scope 一律 False。
#
# ⚠️ 收词按「宁可漏判、不可错杀」：**漏判一个台湾岗**只是让它回到 code=None，非远程照样被
# location_in_scope 丢掉（无害）；**错判一个大陆岗为台湾**则是把在招岗静默删掉（有害）。
# 所以凡与大陆地名有重叠风险的，一律只收「繁体裸名」+「简体带后缀名」两种写法：
#   · 新北 → 只收「新北市」：江苏常州有**新北区**（库里 55 行），裸「新北」会把它判成台湾。
#   · 连江 → 只收繁体「連江」：福建福州有**连江县**（库里 4 行），简体裸名一收就误杀。
#   · 台中 / 台南 / 台东 → 只收带后缀的简体名：「邢台南和区」「烟台北…」这类粘连写法含「台南」。
TAIWAN_CJK_MARKERS = (
    "台湾", "臺灣", "台灣", "臺湾",
    "台北", "臺北", "高雄", "新竹", "基隆", "苗栗", "彰化", "南投", "花莲", "花蓮",
    "澎湖", "嘉義", "嘉义市", "嘉义县",
    "新北市", "桃園", "桃园市", "臺中", "台中市", "臺南", "台南市", "臺東", "台东县",
    "雲林", "云林县", "屏東", "屏东县", "宜蘭", "宜兰县", "金門", "金门县", "連江",
)

# 日本（国名 + 主要都府县市，简繁 / 日本汉字三种写法）。
# ⚠️ JP / KR 排在 CN **后面**：这样「青岛市、日本、潍坊市」这类一岗多地写法仍判 CN，
# 不会因为多写了一个国名就把中国岗翻成海外（库里 2 个地点 / 7 行，2026-09-05 实测）。
# 反过来「大阪市」「東京都」这类纯日本写法不含任何中国地名，落到 JP 上不受影响。
JAPAN_CJK_MARKERS = (
    "日本",
    "东京", "東京", "大阪", "京都", "横滨", "橫濱", "横浜", "名古屋", "神户", "神戶", "神戸",
    "札幌", "仙台", "川崎", "福冈", "福岡", "广岛", "廣島", "広島", "长崎", "長崎",
    "熊本", "静冈", "静岡", "新潟", "奈良", "千叶", "千葉", "埼玉", "神奈川", "兵库", "兵庫",
    "爱知", "愛知", "北海道", "冲绳", "沖繩", "沖縄", "横须贺", "橫須賀",
)

# 韩国（国名 + 主要城市 / 道）。
# ⚠️ 刻意不收「大田」「光州」「汉城」：福建有**大田县**、河南潢川古称光州、「武汉城市圈」含「汉城」，
# 收了就会把大陆岗误判成韩国。少认几个韩国城市无害（见上「宁可漏判」）。
KOREA_CJK_MARKERS = (
    "韩国", "韓國", "首尔", "首爾", "釜山", "仁川", "大邱", "蔚山", "京畿道", "济州", "濟州",
)

_COUNTRY_TOKENS = {
    # ⚠️ TW 必须排在 CN 前面（dict 按插入序遍历，先命中先返回）。
    # 台湾按项目口径**不抓、不归入任一范围**：TW ∉ 任何 source regions 且 TW ∉ _GREATER_CHINA，
    # 于是 location_in_scope 一律返回 False。
    # 此前 TW 压根不在本表里 → "Taipei, Taipei shih, Taiwan, Province of China" 这种写法
    # 因为含 "china" 被判成 CN 放行（2026-07-28 Siemens 改成翻全分页后实测捞进 5 个台北岗才暴露）。
    # 原有 test_taiwan_is_not_in_any_active_scope 只覆盖 "Taiwan"/"Taipei, Taiwan"/"台北, 台湾"
    # 这类**不含 china 字样**的写法（code=None 自然落 False），所以一直是绿的、盖不住这个洞。
    "TW": ["taiwan", "taipei", "kaohsiung", "hsinchu", *TAIWAN_CJK_MARKERS],
    # ⚠️「新界」「九龙」**不能**放本表：这里的中文 token 是**子串**匹配，
    # 而重庆有九龙坡区（线上 30 个岗），一放进来「重庆市-九龙坡区」就被判成香港。
    # 它们改放 _STRICT_CJK_PLACES 走整段精确匹配 —— 与 TAIWAN_CJK_MARKERS
    # 只收「新北市」不收「新北」是同一条取舍。
    "HK": ["hong kong", "香港", "hongkong"],
    "MO": ["macau", "macao", "澳门"],
    "CN": [m for m in CHINA_LOCATION_MARKERS if m not in {"hong kong", "香港", "macau", "macao", "澳门"}],
    # ⚠️ JP / KR 必须排在 CN **后面**（TW 相反，必须在前）：
    #   · TW 在前 —— 「台北, 台湾, 中国」这种写法含「中国」，排在 CN 后就会被判成大陆放行；
    #   · JP/KR 在后 —— 「青岛市、日本、潍坊市」这种一岗多地写法要保住 CN，不能因为多写了
    #     一个国名就把中国岗翻成海外。纯日韩写法不含任何中国地名，排在后面照样命中。
    "JP": list(JAPAN_CJK_MARKERS),
    "KR": list(KOREA_CJK_MARKERS),
    "US": [
        "united states", "usa", "u.s.", "u.s.a", "america", "us",
        "new york", "纽约", "san francisco", "旧金山", "sf bay", "bay area",
        "seattle", "西雅图", "sunnyvale", "mountain view", "cupertino", "san jose",
        "santa clara", "palo alto", "austin", "boston", "chicago", "los angeles",
        "washington", "atlanta", "denver", "dallas", "houston", "san diego",
        "redmond", "menlo park",
        # ⚠️ 这里**不要**再放 ", ca" / ", ny" / ", wa" 这类「逗号+州缩写」的 token：
        # 以 "," 开头的 token 在 _contains_token 里走的是**裸子串**，", ca" 会命中
        # ", Capital" / ", Cargo"，", ma" 命中 ", Manulife" / ", Maharashtra"，
        # ", wa" 命中 ", Wan" —— 线上实测 92 行被这么判成美国，其中 43 行是香港地址
        # （"Taikoo, Shing, 12, Taikoo, Wan, Road" / "HK, , , CHEUNG, SHA, WAN, HKCHE"）。
        # 州缩写改由下面 _US_STATE_* 那套「位置受限 + 必须大写」的规则处理。
    ],
    "SG": ["singapore", "sg", "新加坡"],
}
# ⚠️ 州全称在文件下方 _US_STATE_NAMES 定义后才 extend 进 US 词表（那里离州缩写表更近，
#    两张表的取舍能一眼对照）。所以本表在模块加载完之前是不完整的，别在这中间用它。
_GREATER_CHINA = {"CN", "HK", "MO"}

# ---------------------------------------------------------------------------
# 中文行政区地名识别（2026-09-05 加）
#
# 为什么需要：CHINA_LOCATION_MARKERS **以拼音为主**，中文字符的标记只有寥寥十几个直辖市/
# 省会 + 「中国」。所以 "Changchun" 认得、「长春市」认不得。live 实测（香港库 active 岗）：
# 中文地点（非远程）269,431 个岗里 **68,838 个（25.5%）抽不出国家**，缺的是四类写法：
#   省·市间隔号「安徽省·芜湖市」4,478 / 裸市名「长春市」1,250「嘉兴」1,096 /
#   市-区连字符「保定市-莲池区」647 / 省级与自治州「广东省」581「昌吉回族自治州」459
# 这些岗的国内外归属目前**完全靠 source.regions 兜底**——哪天某个源被放开 US，
# 它名下这些岗会静默翻成 overseas，国内供给凭空少一块、且不报错。
#
# 🚫 为什么不能直接写「含 省/市/区/县 后缀 → CN」（这是本段最重要的红线）：
#   新北市→台湾  大阪市→日本  首尔市/蔚山广域市→韩国  平壤市→朝鲜  胡志明市→越南
#   忠州市→韩国（数据里真有「韩国·忠清北道·忠州市」23 个岗）
# 只加 CN 那一半 = 制造归属错误。项目口径写死「台湾不抓、不归入任一范围」。
#
# 🚫 反过来，「非 CN 词表」也不能写得太松，中文地名互为子串的坑同样真实（全是线上实测）：
#   「新北」→ 江苏常州有**新北区**（25 个岗），拿 "新北" 当台湾标记会误杀
#   「朝鲜」→ 吉林有**延边朝鲜族自治州**（32 个岗），拿 "朝鲜" 当朝鲜标记会误杀
#   「连江」→ 福州有**连江县**（4 个岗），而连江县同时是台湾马祖的县名
#   「大田」→ 韩国大田广域市 vs 福建**大田县**；「东京」→ 山东京博这类**跨词子串**
#   所以境外中文地名一律**整段精确匹配**（含后缀的完整形态，如 "新北市" 而非 "新北"），
#   不做子串、不做「名字+任意后缀」。
#
# ✅ 匹配顺序（`derive_country_code` 里逐阶段短路，改动务必保住这个次序）：
#   ① `_COUNTRY_TOKENS`：既有词表，语义一字不动 → 存量行为零回归
#   ② `_STRICT_CJK_PLACES`：境外中文地名，整段精确匹配 → **先把非 CN 排除掉**
#   ③ `_CN_ADMIN_RE`：中文行政区通用规则 → 最后才判 CN
#   ②必须在③之前，否则「大阪市」会被③的通用后缀规则抢走判成 CN。
# ---------------------------------------------------------------------------

# 段分隔符：· ・ 、 , ， / ＼ | - — ~ ; ： 空格 括号 …… 中文地点串常见的全部形态。
_SEGMENT_SPLIT_RE = re.compile(r"[·・.。,，、;；:：/／\\|｜\-—–－~～()（）\[\]【】{}《》<>\s]+")

# 行政区后缀。长的必须排在短的前面（"自治州" 要先于 "州" 命中）。
# 「道」「府」「都」**刻意不收**——那是日韩的行政区（忠清北道 / 京畿道 / 大阪府 / 东京都），
# 收进来就等于把日韩地名判成中国。
_ADMIN_SUFFIXES = (
    "特别行政区", "自治区", "自治州", "自治县", "自治旗", "地区", "新区",
    "省", "市", "区", "县", "州", "盟", "旗",
)

# 非地名：能出现在地点字段、但不指向任何国家。硬塞进 CN 就是造假。
# 「全国」「全部地区」这类保持 code=None，交给 derive_job_scope 的 source.regions 兜底
# （CN 源 → domestic，海外源 → overseas），这比拍脑袋判 CN 诚实。
_NON_PLACE_SEGMENTS = frozenset({
    "全国", "全部", "全部地区", "全国各地", "各地", "多地", "不限", "地点不限", "不限地区",
    "其他", "其它", "其他地区", "其它地区", "待定", "面议", "异地", "全球", "全球各地",
})

# 明确自称「在境外」但没说哪个国家。code 仍是 None（没有国家可给），
# 但 derive_job_scope 必须判 overseas —— 不能让它走 source.regions 兜底被算成国内供给。
_OVERSEAS_UNSPECIFIED_SEGMENTS = frozenset({
    "海外", "国外", "境外", "海外地区", "国外地区", "海外国家", "境外地区",
})

# 境外中文地名：**整段精确匹配**，含后缀的完整形态一并列出（见上面的红线说明）。
# 顺序即优先级；这一阶段整体先于中文行政区通用规则。
_STRICT_CJK_PLACES = {
    # 香港的分区名。整段精确匹配，所以「重庆市-九龙坡区」（段是"九龙坡区"）不会命中。
    "HK": ("新界", "九龙", "九龍", "香港岛", "香港島"),
    # 台湾：项目口径「不抓、不归入任一范围」，判成 TW 即被 location_in_scope 一律拒。
    # ⚠️「新北」只收 "新北市"：江苏常州有新北区（线上 25 个岗）。
    # ⚠️「连江」一个都不收：福州有连江县（线上 4 个岗），台湾连江县靠上面的 TW 词表兜。
    "TW": (
        "台湾", "臺灣", "台湾省", "中国台湾", "新北市", "台中市", "臺中市", "台南市", "臺南市",
        "桃园市", "桃園市", "基隆市", "新竹市", "新竹县", "嘉义市", "嘉義市", "嘉义县",
        "彰化县", "彰化縣", "宜兰县", "宜蘭縣", "花莲县", "花蓮縣", "屏东县", "屏東縣",
        "苗栗县", "苗栗縣", "南投县", "南投縣", "云林县", "雲林縣", "澎湖县", "金门县", "金門縣",
        "台东县", "臺東縣",
    ),
    # 日本。⚠️「东京」只收整段：山东京博这类跨词子串会误判（"山东"+"京博"）。
    "JP": (
        "日本", "东京", "東京", "东京都", "東京都", "大阪", "大阪市", "大阪府",
        "京都", "京都市", "京都府", "横滨", "橫濱", "横滨市", "名古屋", "名古屋市",
        "札幌", "札幌市", "神户", "神戶", "神户市", "福冈", "福岡", "福冈市",
        "广岛", "廣島", "广岛市", "仙台", "仙台市", "千叶", "千葉", "千叶市", "千叶县",
        "埼玉", "埼玉县", "川崎", "川崎市", "北九州", "北九州市", "静冈", "静冈县",
        "新潟", "熊本", "长崎", "長崎", "冲绳", "沖繩", "冲绳县", "奈良", "神奈川", "神奈川县",
    ),
    # 韩国。⚠️「大田」「光州」只收 "…广域市" 的完整形态：福建有大田县，
    # 裸「大田」「光州」在中文里撞得上中国地名/普通词。
    "KR": (
        "韩国", "韓國", "南韩", "首尔", "首爾", "首尔市", "首尔特别市", "汉城",
        "釜山", "釜山市", "釜山广域市", "仁川", "仁川市", "仁川广域市",
        "大邱广域市", "光州广域市", "大田广域市", "蔚山", "蔚山市", "蔚山广域市",
        "世宗市", "世宗特别自治市", "京畿道", "忠清北道", "忠清南道", "全罗北道", "全罗南道",
        "庆尚北道", "庆尚南道", "江原道", "济州道", "济州特别自治道",
    ),
    # 朝鲜。⚠️ 绝不收裸「朝鲜」：吉林有延边朝鲜族自治州、长白朝鲜族自治县（线上 32 个岗）。
    "KP": ("朝鲜民主主义人民共和国", "北朝鲜", "平壤", "平壤市"),
    # 越南：数据里「胡志明市」24 个岗，通用后缀规则会把它判成 CN。
    "VN": ("越南", "胡志明市", "胡志明", "河内", "河内市", "岘港", "海防市"),
    "TH": ("泰国", "曼谷", "曼谷市", "清迈"),
    "MY": ("马来西亚", "吉隆坡", "槟城", "柔佛"),
    "ID": ("印度尼西亚", "印尼", "雅加达", "泗水"),
    "PH": ("菲律宾", "马尼拉"),
    "IN": ("印度", "新德里", "孟买", "班加罗尔"),
    "AE": ("阿联酋", "迪拜", "杜拜", "阿布扎比"),
    # 以下国名/城市来自**线上残留写法实测**（不是背世界地图）：改完之后仍抽不出国家的
    # 6,627 个中文地点岗里，绝大多数就是这些串。它们眼下靠 source.regions 兜底，
    # CN 源下会被算成国内供给 —— 正是本次要治的病。
    # ⚠️「蒙古」只收 "蒙古国"：内蒙古自治区含「蒙古」二字，裸收会把内蒙古判成外国。
    #    整段精确匹配已经能挡（"内蒙古" != "蒙古"），这里再加一层字面保险。
    "US": ("美国", "圣何塞", "帕罗奥多", "帕洛阿尔托", "洛杉矶", "森尼韦尔", "圣克拉拉",
           "贝尔维尤", "费利蒙", "山景城", "尔湾", "奥斯汀", "布鲁克林", "萨克拉门托",
           "华盛顿哥伦比亚特区"),
    "GB": ("英国", "伦敦", "莱斯特"),
    "DE": ("德国", "慕尼黑", "柏林", "杜塞尔多夫", "法兰克福", "斯图加特"),
    "FR": ("法国", "巴黎"),
    "NL": ("荷兰", "阿姆斯特丹", "鹿特丹", "霍夫多尔普"),
    "ES": ("西班牙", "马德里"),
    "IT": ("意大利", "米兰", "罗马"),
    "PL": ("波兰", "华沙"),
    "RU": ("俄罗斯", "俄罗斯联邦", "莫斯科"),
    "MX": ("墨西哥", "墨西哥城", "瓜达拉哈拉"),
    "BR": ("巴西", "圣保罗", "巴西利亚"),
    "SA": ("沙特阿拉伯", "利雅得", "艾卜哈"),
    "TR": ("土耳其", "伊斯坦布尔"),
    "AU": ("澳大利亚", "悉尼", "墨尔本", "布里斯班"),
    "CA": ("加拿大", "多伦多", "温哥华"),
    "ZA": ("南非", "约翰内斯堡"),
    "EG": ("埃及", "开罗"),
    "NG": ("尼日利亚", "拉各斯"),
    "KE": ("肯尼亚", "内罗毕", "奈洛比"),
    "KZ": ("哈萨克斯坦", "阿拉木图", "阿斯塔纳"),
    "UZ": ("乌兹别克斯坦", "塔什干"),
    "TJ": ("塔吉克斯坦",),
    "KG": ("吉尔吉斯斯坦",),
    "PK": ("巴基斯坦", "拉合尔"),
    "BD": ("孟加拉", "孟加拉国", "达卡"),
    "LK": ("斯里兰卡",),
    "KH": ("柬埔寨", "金边"),
    "LA": ("老挝", "万象"),
    "MM": ("缅甸", "仰光"),
    "BN": ("文莱",),
    "MN": ("蒙古国",),
    "ZW": ("津巴布韦",),
    "GN": ("几内亚",),
    "MA": ("摩洛哥", "卡萨布兰卡"),
    "HU": ("匈牙利", "布达佩斯"),
    "CZ": ("捷克", "布拉格", "布拉格直辖市"),
    "SK": ("斯洛伐克",),
    "SI": ("斯洛文尼亚",),
    "RO": ("罗马尼亚", "布加勒斯特"),
    "RS": ("塞尔维亚", "贝尔格莱德"),
    "BG": ("保加利亚", "索非亚"),
    "GR": ("希腊", "雅典"),
    "PT": ("葡萄牙", "里斯本"),
    "SE": ("瑞典", "斯德哥尔摩"),
    "NO": ("挪威", "奥斯陆"),
    "DK": ("丹麦", "哥本哈根", "巴勒鲁普"),
    "FI": ("芬兰", "赫尔辛基"),
    "IE": ("爱尔兰", "都柏林"),
    "AT": ("奥地利", "维也纳", "格拉茨"),
    "CH": ("瑞士", "苏黎世", "日内瓦"),
    "BE": ("比利时", "列日", "梅赫伦", "布鲁塞尔"),
    "LU": ("卢森堡",),
    "UA": ("乌克兰", "基辅"),
    "BY": ("白俄罗斯", "明斯克"),
    "LV": ("拉脱维亚",),
    "EE": ("爱沙尼亚",),
    "IL": ("以色列", "特拉维夫"),
    "AR": ("阿根廷", "布宜诺斯艾利斯"),
    "CL": ("智利", "圣地亚哥"),
    "PE": ("秘鲁", "利马"),
    "CO": ("哥伦比亚", "波哥大"),
    "UY": ("乌拉圭",),
    "VE": ("委内瑞拉",),
    "PA": ("巴拿马",),
    "NI": ("尼加拉瓜", "马那瓜"),
    "EC": ("厄瓜多尔", "基多"),
    "DZ": ("阿尔及利亚",),
    "TZ": ("坦桑尼亚",),
    "ZM": ("赞比亚",),
    "ET": ("埃塞俄比亚",),
    "GH": ("加纳",),
    "CI": ("科特迪瓦", "阿比让"),
    "CM": ("喀麦隆",),
    "SN": ("塞内加尔",),
    "ML": ("马里",),
    "AO": ("安哥拉", "罗安达", "罗安达市"),
    "CD": ("刚果民主共和国", "金沙萨"),
    "CG": ("刚果",),
    "GA": ("加蓬",),
    "UG": ("乌干达",),
    "SL": ("塞拉利昂",),
    "LR": ("利比里亚",),
    "DJ": ("吉布提",),
    "IQ": ("伊拉克", "埃尔比勒"),
    "IR": ("伊朗", "德黑兰"),
    "KW": ("科威特",),
    "QA": ("卡塔尔", "多哈"),
    "OM": ("阿曼",),
    "JO": ("约旦", "安曼"),
    "AZ": ("阿塞拜疆", "巴库"),
    "DO": ("多米尼加", "圣多明各"),
}

# 中国大陆省级 + 地级行政区名（不含后缀）。**枚举而非猜**：这是一份有边界的清单
# （34 省级 + ~333 地级），比「任何后缀都算中国」精确得多，也是「裸市名」那一类
# （长春 / 嘉兴 / 惠州，占 68,838 里相当一部分）唯一能认出来的办法。
# 港澳台不在此表（各有各的 code），台湾更是必须留在 _STRICT_CJK_PLACES 里。
_CN_ADMIN_NAMES = (
    # 直辖市 + 省 + 自治区
    "北京", "天津", "上海", "重庆",
    "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建", "江西",
    "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
    "甘肃", "青海", "台湾省",
    "内蒙古", "广西", "西藏", "宁夏", "新疆",
    "内蒙古自治", "广西壮族", "西藏自治", "宁夏回族", "新疆维吾尔",
    # 河北（雄安是国家级新区，线上 41 个岗写成「雄安新区」/「雄安新区-雄县」）
    "雄安", "石家庄", "唐山", "秦皇岛", "邯郸", "邢台", "保定", "张家口", "承德", "沧州", "廊坊", "衡水",
    # 山西
    "太原", "大同", "阳泉", "长治", "晋城", "朔州", "晋中", "运城", "忻州", "临汾", "吕梁",
    # 内蒙古
    "呼和浩特", "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔", "巴彦淖尔", "乌兰察布",
    "兴安", "锡林郭勒", "阿拉善",
    # 辽宁
    "沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新", "辽阳", "盘锦",
    "铁岭", "朝阳", "葫芦岛",
    # 吉林
    "长春", "四平", "辽源", "通化", "白山", "松原", "白城", "延边", "延边朝鲜族",
    # 黑龙江
    "哈尔滨", "齐齐哈尔", "鸡西", "鹤岗", "双鸭山", "大庆", "伊春", "佳木斯", "七台河",
    "牡丹江", "黑河", "绥化", "大兴安岭",
    # 江苏
    "南京", "无锡", "徐州", "常州", "苏州", "南通", "连云港", "淮安", "盐城", "扬州",
    "镇江", "泰州", "宿迁",
    # 浙江
    "杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水",
    # 安徽
    "合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山", "滁州",
    "阜阳", "宿州", "六安", "亳州", "池州", "宣城",
    # 福建
    "福州", "厦门", "莆田", "三明", "泉州", "漳州", "南平", "龙岩", "宁德",
    # 江西
    "南昌", "景德镇", "萍乡", "九江", "新余", "鹰潭", "赣州", "吉安", "宜春", "抚州", "上饶",
    # 山东
    "济南", "青岛", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安", "威海", "日照",
    "临沂", "德州", "聊城", "滨州", "菏泽",
    # 河南
    "郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳", "许昌", "漯河",
    "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店", "济源",
    # 湖北
    "武汉", "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州", "黄冈", "咸宁",
    "随州", "恩施", "恩施土家族苗族", "仙桃", "潜江", "天门", "神农架",
    # 湖南
    "长沙", "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳", "郴州", "永州",
    "怀化", "娄底", "湘西", "湘西土家族苗族",
    # 广东
    "广州", "韶关", "深圳", "珠海", "汕头", "佛山", "江门", "湛江", "茂名", "肇庆", "惠州",
    "梅州", "汕尾", "河源", "阳江", "清远", "东莞", "中山", "潮州", "揭阳", "云浮",
    # 广西
    "南宁", "柳州", "桂林", "梧州", "北海", "防城港", "钦州", "贵港", "玉林", "百色",
    "贺州", "河池", "来宾", "崇左",
    # 海南
    "海口", "三亚", "三沙", "儋州", "琼海", "文昌", "万宁", "东方", "五指山", "定安",
    "屯昌", "澄迈", "临高", "陵水", "保亭", "白沙", "昌江", "乐东", "琼中",
    # 四川
    "成都", "自贡", "攀枝花", "泸州", "德阳", "绵阳", "广元", "遂宁", "内江", "乐山",
    "南充", "眉山", "宜宾", "广安", "达州", "雅安", "巴中", "资阳", "阿坝", "甘孜", "凉山",
    "阿坝藏族羌族", "甘孜藏族", "凉山彝族",
    # 贵州
    "贵阳", "六盘水", "遵义", "安顺", "毕节", "铜仁", "黔西南", "黔东南", "黔南",
    # 云南
    "昆明", "曲靖", "玉溪", "保山", "昭通", "丽江", "普洱", "临沧", "楚雄", "红河",
    "文山", "西双版纳", "大理", "德宏", "怒江", "迪庆",
    # 西藏
    "拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里",
    # 陕西
    "西安", "铜川", "宝鸡", "咸阳", "渭南", "延安", "汉中", "榆林", "安康", "商洛",
    # 甘肃
    "兰州", "嘉峪关", "金昌", "白银", "天水", "武威", "张掖", "平凉", "酒泉", "庆阳",
    "定西", "陇南", "临夏", "甘南", "临夏回族", "甘南藏族",
    # 青海
    "西宁", "海东", "海北", "黄南", "果洛", "玉树", "海西",
    # 宁夏
    "银川", "石嘴山", "吴忠", "固原", "中卫",
    # 新疆
    "乌鲁木齐", "克拉玛依", "吐鲁番", "哈密", "昌吉", "博尔塔拉", "巴音郭楞", "阿克苏",
    "克孜勒苏", "喀什", "和田", "伊犁", "塔城", "阿勒泰", "石河子", "阿拉尔", "图木舒克",
    "五家渠", "北屯", "铁门关", "双河", "可克达拉", "昆玉", "胡杨河", "新星",
    "昌吉回族", "博尔塔拉蒙古", "巴音郭楞蒙古", "克孜勒苏柯尔克孜", "伊犁哈萨克",
)

_CN_ADMIN_NAME_SET = frozenset(_CN_ADMIN_NAMES)
# 「名字 + 行政区后缀」：既吃「长春市」「广东省」，也吃没有分隔符的「上海市浦东新区」。
# 名字长的排前面，避免 "海南" 抢走 "海南藏族自治州"（两者都是 CN，无害，但语义更准）。
# 民族限定词：「大理白族自治州」「红河哈尼族彝族自治州」「怒江傈僳族自治州」这类写法里，
# 名字与后缀之间隔着一到多个「X族」。要求必须以「族」收尾，是**中国独有**的行政区构词，
# 不会把任何境外地名带进来。
_ETHNIC_QUALIFIER = r"(?:[一-鿿]{1,4}族){0,3}"
_CN_ADMIN_RE = re.compile(
    "(?:"
    + "|".join(re.escape(n) for n in sorted(_CN_ADMIN_NAMES, key=len, reverse=True))
    + ")"
    + _ETHNIC_QUALIFIER
    + "(?:"
    + "|".join(_ADMIN_SUFFIXES)
    + ")"
)


def _segments(text: str):
    return [s for s in _SEGMENT_SPLIT_RE.split(text) if s]


# 预先建好每个国家的 frozenset。derive_country_code 是**逐岗**调用的热路径，
# 原来每次调用给每个国家现建一次 frozenset（~90 个）纯属浪费。
# ⚠️ 刻意保持「按国家顺序逐个试」而不是摊平成「地名 → code」的单张表：
#    摊平会把多国混写串（"印度、越南" / "加纳、赞比亚"）的语义从「表里靠前的国家胜」
#    变成「串里靠前的段胜」，实测 19,419 个真实地点里有 16 个会因此改判 ——
#    lib/geo.js 是逐条镜像的，语义一漂两侧就对不上（跨语言夹具当场抓到了这个）。
_STRICT_CJK_PLACE_SETS = tuple(
    (code, frozenset(places)) for code, places in _STRICT_CJK_PLACES.items()
)


def _strict_cjk_country(segs) -> Optional[str]:
    """境外中文地名：整段精确匹配。子串匹配会踩「新北区/延边朝鲜族/山东京博」的坑。"""
    for code, place_set in _STRICT_CJK_PLACE_SETS:
        if any(seg in place_set for seg in segs):
            return code
    return None


def _looks_like_cn_admin(segs) -> bool:
    """中文行政区通用规则。**只在境外词表全部落空之后才允许调用**（见本段顶部的顺序说明）。"""
    for seg in segs:
        if seg in _NON_PLACE_SEGMENTS or seg in _OVERSEAS_UNSPECIFIED_SEGMENTS:
            continue
        # ① 裸地名整段命中（「嘉兴」「东莞」「济南」）
        if seg in _CN_ADMIN_NAME_SET:
            return True
        # ② 名字 + 行政区后缀（「长春市」「广东省」「上海市浦东新区」「昌吉回族自治州」）
        if _CN_ADMIN_RE.search(seg):
            return True
    return False


def is_overseas_unspecified(location: Optional[str]) -> bool:
    """地点自称「海外」「国外」但没说是哪国。

    没有国家码可给，但**绝不能**让它走 derive_job_scope 的 source.regions 兜底 ——
    CN 源下的「海外」岗会被算成国内供给，撞的是筛选准确性红线。
    """
    if not location:
        return False
    return any(seg in _OVERSEAS_UNSPECIFIED_SEGMENTS for seg in _segments(location.strip()))



# ---------------------------------------------------------------------------
# 美国州名 / 州缩写（2026-09-05 加）
#
# 为什么需要：US 词表只有十几个大城市，认不出州。live 实测（香港库 active 岗）英文地点
# 132,876 个岗里 24,672 个抽不出国家，**其中 11,753 个判成了 domestic** —— 用户筛「国内」
# 会看到 Mossville, Illinois / Irving, Texas / Portage, Michigan / CHARLOTTE, NC。
#
# 🚫 为什么两字母缩写不能裸着认：它们和别国的州/省缩写、和英文单词大面积重名 ——
#   IN=印度 / OR、AND 之类的词、DE=德国、CA=加拿大、GA=格鲁吉亚、TN=印度泰米尔纳德邦。
#   既有测试里就钉着一条 "Chennai, TN, in"（金奈，印度）。
# ✅ 所以只在**「City, ST」这个位置**认，且必须是原串里的**大写**形态：
#   - 结尾的 ", ST"（可带 5 位邮编）："CHARLOTTE, NC" / "Ann, Arbor, MI 48108"
#   - 黏在词尾的 "ST"（某个 adapter 会把逗号吃掉）："AustinTX" / "Santa, ClaraCA"
#   小写的 "…, in" 一律不认，所以 "Chennai, TN, in" 结尾是小写 in ⇒ 不判 US（仍是 None）。
# 本规则整体排在所有词表**之后**，任何显式国名都优先于它。
# ---------------------------------------------------------------------------

_US_STATE_NAMES = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "utah", "vermont",
    "virginia", "west virginia", "wisconsin", "wyoming", "puerto rico", "texas",
    # ⚠️ 刻意不收 "georgia"：与格鲁吉亚同名，认了就会把第比利斯的岗算成美国。
    #    washington / new york 已在上面的 US 词表里（当城市名收的），这里不重复。
)

_US_STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA PR RI SC SD TN TX UT VT VA WA WV WI WY".split()
)

# 「, ST」结尾（可带邮编），或「词尾黏着的 ST」结尾（可带邮编）。都只吃**原串大写**形态。
# ⚠️ ZIP+4 要认「逗号分隔」的写法：某个 adapter 会把 "55403-2542" 写成 "55403, 2542"
#    （线上 "1000, Nicollet, Mall, MinneapolisMN, 55403, 2542" 等 278 个岗）。
_US_STATE_TAIL_RE = re.compile(
    r"(?:(?<=[,\s])|(?<=[a-z]))([A-Z]{2})\s*,?\s*(?:\d{5}(?:\s*[,-]\s*\d{4})?)?\s*$"
)


# 州全称并进 US 词表，走 _contains_token 的词边界语义（"Mossville, Illinois" 即命中）。
_COUNTRY_TOKENS["US"].extend(_US_STATE_NAMES)


def _has_us_state(location: Optional[str]) -> bool:
    """「City, ST」位置上的美国州缩写。必须大写、必须在串尾，避免撞英文单词与别国缩写。"""
    if not location:
        return False
    match = _US_STATE_TAIL_RE.search(location.strip())
    return bool(match) and match.group(1) in _US_STATE_CODES

def _norm(text: Optional[str]) -> str:
    return (text or "").strip().lower()


# token → 已编译正则。之前每次调用都要给每个 token 重新拼一次 pattern 字符串
# （US 词表加了 46 个州全称之后有 200+ 个 token），而 token 表是模块级常量、结果恒定。
# 实测 211 µs/次 → 89 µs/次（19,419 个真实地点 ×3 轮；改动前基线 180 µs），行为逐条不变。
_TOKEN_RE_CACHE: dict = {}


def _token_regex(token: str):
    cached = _TOKEN_RE_CACHE.get(token)
    if cached is None:
        parts = [re.escape(p) for p in re.split(r"[^a-z0-9]+", token.lower()) if p]
        pattern = r"[^a-z0-9]+".join(parts)
        cached = re.compile(r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])") if parts else False
        _TOKEN_RE_CACHE[token] = cached
    return cached


def _contains_token(text: str, token: str) -> bool:
    if any("一" <= ch <= "鿿" for ch in token) or token.startswith(","):
        return token in text
    regex = _token_regex(token)
    if regex is False:
        return False
    return bool(regex.search(text))


def is_china_location(location: Optional[str]) -> bool:
    """Whether a location belongs to greater China, including Hong Kong/Macau."""
    if not location:
        return False
    # 先问 derive_country_code：判得出且不属大中华的（台湾 / 日本 / 韩国 / 美国…）一律否决。
    # 否则「Taipei, Taiwan, China」这种写法因为含 "china" 会被下面的 marker 扫描判成在华 ——
    # 而本函数正是 greenhouse / workday / ashby / smartrecruiters / apple 这些外企 adapter
    # 「只留在华岗」的那道门，台湾岗会从这里漏进国内看板（库里实测 1 行）。
    # 只做减法：判不出国家（code=None）时行为与旧实现一字不变。
    code = derive_country_code(location)
    if code is not None and code not in _GREATER_CHINA:
        return False
    text = location.lower()
    if any(marker in text for marker in _CJK_MARKERS):
        return True
    if _LATIN_MARKER_RE.search(text):
        return True
    norm = re.sub(r"[\s,\-/]+", " ", text)
    return bool(_LATIN_MARKER_RE.search(norm))


def is_remote_location(location: Optional[str]) -> bool:
    if not location:
        return False
    return any(marker in location.lower() for marker in REMOTE_MARKERS)


def _is_overseas_pinned(location: Optional[str]) -> bool:
    if not location:
        return False
    text = location.lower()
    if any(phrase in text for phrase in OVERSEAS_LOCATION_PHRASES):
        return True
    tokens = [t for t in re.split(r"[^a-z]+", text) if t]
    return any(t in OVERSEAS_LOCATION_TOKENS for t in tokens)


def keep_for_china_radar(location: Optional[str]) -> bool:
    """Existing China radar scope: greater China plus remote not pinned overseas."""
    if is_china_location(location):
        return True
    if is_remote_location(location) and not _is_overseas_pinned(location):
        return True
    return False


def derive_country_code(location: Optional[str]) -> Optional[str]:
    """Derive an ISO-2 country/region code from free-form location text.

    四阶段短路，**顺序不可调换**（红线说明见文件中部「中文行政区地名识别」「美国州名」两段）：
      ① `_COUNTRY_TOKENS`    既有词表 + 州全称，语义一字未动 → 存量判定零回归
      ② `_looks_like_cn_admin` 中文行政区规则（**白名单锚定**）
      ③ `_STRICT_CJK_PLACES` 境外中文地名，整段精确匹配
      ④ `_has_us_state`      美国州缩写，位置受限 + 必须大写 → 最后兜底
    ②在③之前是为了让一岗多地写法（"柳州市、南非"）保住 CN —— 那种岗确实有一部分在国内。
    它成立的前提是②必须白名单锚定：「大阪市」里没有大陆地名所以命中不了②，照样落③判 JP。
    ④在最末同理：任何显式国名都必须优先于两字母缩写，否则 "Chennai, TN, in"（金奈，印度）
    会因为 TN 被判成美国。
    """
    text = _norm(location)
    if not text or text in ("unknown", "multiple locations"):
        return None
    for code, tokens in _COUNTRY_TOKENS.items():
        if any(_contains_token(text, token) for token in tokens):
            return code
    segs = _segments(location.strip())
    # ⚠️ 一岗多地写法（"柳州市、南非" / "保定市,俄罗斯"）里**中国优先**：这种岗确实有一部分
    # 在国内，判成境外就把它从国内供给里抹掉了。所以中文行政区规则排在境外词表之前。
    # 这一步之所以安全，全靠③是**白名单锚定**（必须命中大陆省级/地级行政区名）而不是裸后缀
    # 规则 —— "大阪市"/"新北市"/"首尔市"/"胡志明市" 里没有任何大陆地名，命中不了③，
    # 照样落到④判成 JP/TW/KR/VN。**谁要是把③放宽成「任何 X市 → CN」，这个顺序立刻就错**，
    # 届时 tests/fixtures/geo-cases.json 里那批红线用例会当场变红。
    if _looks_like_cn_admin(segs):
        return "CN"
    strict = _strict_cjk_country(segs)
    if strict is not None:
        return strict
    # 州缩写排在最后：任何显式国名/城市都优先于它（"Chennai, TN, in" 因此不会判成 US）。
    if _has_us_state(location):
        return "US"
    return None


def derive_job_scope(location: Optional[str], regions=None) -> str:
    """domestic for greater China; overseas otherwise.

    地点**抽不出国家**时（空 / "Multiple Locations" / 裸「远程」「Remote」），按**源自己的
    regions** 兜底判定；没传 regions 则维持旧默认 domestic，故老调用方行为一字不变。

    ⚠️ 为什么必须看源：裸「远程」默认判 domestic 是**海外扩展之前**的合理默认（那时库里
    只有 CN 源，远程岗几乎必然在国内）。2026-07-02 放开 US/SG/Remote 之后这个默认就反了 ——
    2026-09-04 实测全库 9,873 个「裸远程 + 判 domestic」的在招岗里，**9,863 个来自 regions
    不含 CN 的海外源**（AbbVie 1,512 / ServiceNow 576 / Samsara 483 / NVIDIA 360…），
    只有 10 个来自纯 CN 源。用户筛「国内」时看到的是一片美国远程岗，这是筛选准确性红线。
    分离度 99.9%，所以按源判是干净的。
    （带国家写法的远程「Remote - US」早已由 f306271 修好，这里补的是**裸远程**那一半。）
    """
    code = derive_country_code(location)
    if code is not None:
        return "domestic" if code in _GREATER_CHINA else "overseas"
    # 下面两条都是「抽不出国家码、但地点已经说明白它在境外」——**都必须排在 source.regions
    # 兜底之前**，兜底只该服务「真的什么都没说」的地点（裸「远程」/ 空 / Multiple Locations）。
    # 两条各治一种写法，缺一不可：
    #
    # ① 地点自报「海外」「国外」——没有国家可给，但绝不能走 regions 兜底：
    #    CN 源下的「海外」岗会被算成国内供给（线上 1,119 个 active 岗是这么写的）。
    if is_overseas_unspecified(location):
        return "overseas"
    # ② 地点里**明确钉着一个境外地名**（"Remote Germany" / "India (Remote)" / "Minato-ku, Japan"）：
    #    少了这一层，给外企源补 CN（迁移 232）会让它名下所有海外远程岗一起变成国内岗 ——
    #    2026-09-05 实测那批源上有 121 个（艾伯维 102 / 大陆集团 13 / Grab 4 / Expeditors 1 / 育碧 1）。
    #    注意顺序：code 优先。地点能判出国家就以国家为准，这里只管「有地名、但不在 geo 的国家词典里」。
    if _is_overseas_pinned(location):
        return "overseas"
    if regions:
        if "CN" not in {str(r).strip() for r in regions}:
            return "overseas"
    return "domestic"


def location_in_scope(location: Optional[str], regions) -> bool:
    """Whether location is inside source regions such as CN/US/SG/Remote."""
    regions = {str(r) for r in (regions or {"CN"})}
    code = derive_country_code(location)
    if code is not None:
        if code in regions:
            return True
        if "CN" in regions and code in _GREATER_CHINA:
            return True
        return False
    if is_remote_location(location):
        return "Remote" in regions or "CN" in regions
    return False

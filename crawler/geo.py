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
    "铜川", "宝鸡", "咸阳", "渭南", "延安", "汉中", "榆林", "安康", "商洛",
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
}
OVERSEAS_LOCATION_PHRASES = (
    "united states", "united kingdom", "new zealand", "south korea", "saudi arabia",
    "sri lanka", "costa rica", "south africa",
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
        "redmond", "menlo park", ", ca", ", ny", ", wa", ", tx", ", ma",
    ],
    "SG": ["singapore", "sg", "新加坡"],
}
_GREATER_CHINA = {"CN", "HK", "MO"}


def _norm(text: Optional[str]) -> str:
    return (text or "").strip().lower()


def _contains_token(text: str, token: str) -> bool:
    if any("一" <= ch <= "鿿" for ch in token) or token.startswith(","):
        return token in text
    parts = [re.escape(p) for p in re.split(r"[^a-z0-9]+", token.lower()) if p]
    if not parts:
        return False
    pattern = r"[^a-z0-9]+".join(parts)
    return bool(re.search(r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])", text))


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
    """Derive an ISO-2 country/region code from free-form location text."""
    text = _norm(location)
    if not text or text in ("unknown", "multiple locations"):
        return None
    for code, tokens in _COUNTRY_TOKENS.items():
        if any(_contains_token(text, token) for token in tokens):
            return code
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

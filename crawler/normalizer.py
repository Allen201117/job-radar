import hashlib
import html
import json
import re
from datetime import date, datetime, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlparse

from adapters.base import RawJob
from grad_class import extract_grad_class
from geo import (
    CHINA_LOCATION_MARKERS,
    ISO_ALPHA2_CODES,
    OVERSEAS_LOCATION_PHRASES,
    OVERSEAS_LOCATION_TOKENS,
    REMOTE_MARKERS,
    _GREATER_CHINA,
    _REJECTED_COUNTRY_CODES,
    _is_overseas_pinned,
    cn_name_is_part_of_another_place,
    cn_place_province,
    derive_country_code,
    derive_job_scope,
    is_china_location,
    is_rejected_location,
    is_remote_location,
    keep_for_china_radar,
    location_cn_places,
    location_in_scope,
    title_city_location,
)
from sponsorship import sponsorship_signal


NAVIGATION_TITLES = {
    "首页",
    "首 页",
    "全部岗位",
    "岗位搜索",
    "社会招聘",
    "校园招聘",
    "实习生招聘",
    "博士招聘",
    "招聘帮助",
    "关于百度",
    "使用百度前必读",
    "发展在京东",
    "科技人才招聘",
    "了解海尔",
    "login",
    "faqs & support",
    "english",
    "deutsch",
    "español",
    "français",
    "nederlands",
    "portuguese",
    "čestina",
    "中文 (简体)",
    "中文 (繁体)",
    "日本語",
    "job search",
    "all jobs",
    "ai recommendations",
    "professional",
    "campus",
    "intern",
    "stay connected",
    "logout",
}

CITY_ALIASES = {
    "北京": "北京",
    "北京市": "北京",
    "beijing": "北京",
    "上海": "上海",
    "上海市": "上海",
    "shanghai": "上海",
    "深圳": "深圳",
    "深圳市": "深圳",
    "shenzhen": "深圳",
    "广州": "广州",
    "广州市": "广州",
    "guangzhou": "广州",
    "杭州": "杭州",
    "杭州市": "杭州",
    "hangzhou": "杭州",
    "南京": "南京",
    "南京市": "南京",
    "nanjing": "南京",
    "苏州": "苏州",
    "苏州市": "苏州",
    "suzhou": "苏州",
    "成都": "成都",
    "成都市": "成都",
    "chengdu": "成都",
    "武汉": "武汉",
    "武汉市": "武汉",
    "wuhan": "武汉",
    "西安": "西安",
    "西安市": "西安",
    "xi'an": "西安",
    "xian": "西安",
    # 与 lib/china-keyword-expansion.js 的 CITY_ALIASES 逐条同表（两端漂了会让同一个岗位
    # 在爬虫落库与前端筛选下判成两个城市）。拼音只收唯一的：泰州/台州、福州/抚州 同音，不收。
    "无锡": "无锡",
    "无锡市": "无锡",
    "wuxi": "无锡",
    "合肥": "合肥",
    "合肥市": "合肥",
    "hefei": "合肥",
    "宁波": "宁波",
    "宁波市": "宁波",
    "ningbo": "宁波",
    "东莞": "东莞",
    "东莞市": "东莞",
    "dongguan": "东莞",
    "佛山": "佛山",
    "佛山市": "佛山",
    "foshan": "佛山",
    "珠海": "珠海",
    "珠海市": "珠海",
    "zhuhai": "珠海",
    "惠州": "惠州",
    "惠州市": "惠州",
    "huizhou": "惠州",
    "湛江": "湛江",
    "湛江市": "湛江",
    "zhanjiang": "湛江",
    "青岛": "青岛",
    "青岛市": "青岛",
    "qingdao": "青岛",
    "南昌": "南昌",
    "南昌市": "南昌",
    "nanchang": "南昌",
    "南宁": "南宁",
    "南宁市": "南宁",
    "nanning": "南宁",
    "海口": "海口",
    "海口市": "海口",
    "haikou": "海口",
    "长春": "长春",
    "长春市": "长春",
    "changchun": "长春",
    "绍兴": "绍兴",
    "绍兴市": "绍兴",
    "shaoxing": "绍兴",
    "连云港": "连云港",
    "连云港市": "连云港",
    "lianyungang": "连云港",
    "泰州": "泰州",
    "泰州市": "泰州",
    "福州": "福州",
    "福州市": "福州",
    "香港": "香港",
    "香港特别行政区": "香港",
    "hong kong": "香港",
    "新加坡": "新加坡",
    "singapore": "新加坡",
    "全国": "全国",
    "全国多地": "全国",
    "多地": "全国",
    "远程": "远程",
    "remote": "远程",
}


def strip_nul(value):
    """剥掉 NUL(0x00)。非字符串原样返回。

    Postgres 的 text 类型不允许 NUL —— psycopg2 会直接抛
    `ValueError: A string literal cannot contain NUL (0x00) characters`，
    **整个源这一轮抓取全部失败**（不是丢一条，是丢一批）。
    2026-07-28 实测 laiyifen.zhiye.com（来伊份）的岗位文本里混着 NUL，
    每天固定挂 2 次，连挂多日。清洗器里的 `re.sub(r"\\s+", " ")` 治不了它：
    \\x00 不属于 \\s，会原样穿透到写库那一刻才炸。

    只剥 NUL：其它控制字符 Postgres 存得下，动了反而改变正文。
    """
    if not isinstance(value, str):
        return value
    return value.replace("\x00", "") if "\x00" in value else value


# 标题里的「 - 」分隔：连字符两侧都有空白才算（紧贴写法是中文「部门-角色-方向」的紧凑复合标题，从不拆）。
_TITLE_SEP_RE = re.compile(r"\s+[-–—]\s+")
_TITLE_TAIL_WORD_SPLIT_RE = re.compile(r"[^0-9a-z一-鿿]+")
_TITLE_TAIL_CJK_RE = re.compile(r"[一-鿿]")
_TITLE_TAIL_ADMIN_SUFFIX_RE = re.compile(r"(?:特别行政区|自治区|自治州|省|市)$")
# 方位词单独成段时是销售大区（"Territory Account Executive - South"），不是地点——哪怕地点字段里
# 恰好有这个词（"South San Francisco, CA"）。
_TITLE_TAIL_COMPASS_WORDS = frozenset({
    "north", "south", "east", "west", "central", "northern", "southern", "eastern", "western",
    "northeast", "northwest", "southeast", "southwest", "midwest",
})
_TITLE_OPEN_BRACKETS = "(（[【"
_TITLE_CLOSE_BRACKETS = ")）]】"


def _title_tail_repeats_location(tail: str, locations) -> bool:
    """标题尾段是不是只在重复这个岗自己的地点字段：尾段的**每个词**都得在地点里找得到。

    西文按整词比（"CA" 要地点里真有 "CA"，不做州名换算）；中文去掉 省/市 这类后缀后按子串比
    （「上海」对得上「上海市-浦东新区」「中国上海」）。任何一个词对不上就不算——
    "Shanghai (Hybrid)"、"North America"、「上海研发中心」都留在标题里。
    尾段整段是 CITY_ALIASES 的键时再按别名比一次（标题写 Singapore、地点字段给的是「新加坡」）。
    """
    loc_text = " ".join(loc for loc in locations if loc).lower()
    if not loc_text:
        return False
    alias = CITY_ALIASES.get(tail.strip().lower())
    if alias and alias.lower() in loc_text:
        return True
    words = [w for w in _TITLE_TAIL_WORD_SPLIT_RE.split(tail.lower()) if w]
    if not words or all(w in _TITLE_TAIL_COMPASS_WORDS for w in words):
        return False
    loc_words = set(_TITLE_TAIL_WORD_SPLIT_RE.split(loc_text))
    for word in words:
        if _TITLE_TAIL_CJK_RE.search(word):
            core = _TITLE_TAIL_ADMIN_SUFFIX_RE.sub("", word)
            if word not in loc_text and (len(core) < 2 or core not in loc_text):
                return False
        elif word not in loc_words:
            return False
    return True


def title_first_segment(title: Optional[str]) -> str:
    """「 - 」分段标题的第一段；不分段就是整条（去首尾空白）。"""
    return _TITLE_SEP_RE.split((title or "").strip(), maxsplit=1)[0]


def clean_title(title: str, *locations: Optional[str]) -> str:
    """清洗岗位标题：去首尾空白、去多余空格；尾部的 " - 地点" 只在**与该岗的地点字段重复**时才去掉。

    locations = 这个岗自己的地点（adapter 原文 + clean_location 之后的，哪个对得上都算）。不传就什么都不截。

    🚫 别退回「见到 " - " 就把后面全截掉」（2026-10-10 之前的写法 `re.sub(r"\\s+[-–—]\\s+.*$", "", t)`）：
    ❌ 财通证券「杭州金城路证券营业部 - 副总经理」「… - 财富顾问」「… - 业务副总经理」入库后三行都叫
       「杭州金城路证券营业部」；Greenhouse「Software Engineer - Computer Vision」只剩「Software Engineer」；
       「Machine Learning Researcher - Intern」丢了 Intern，而招聘类型的实习判定只认标题。
    ✅ 根因：那条正则只看分隔符、不看截掉的是什么。live 实测见 crawler/test_normalizer.py 的
       CleanTitleTailTest 文件头——被它截掉的绝大多数不是地点，是岗位名 / 方向 / 团队。
    ✅ 现行判据不猜「这像不像地名」，只问「这段信息地点字段里是不是已经有了」：有 = 截掉零损失；
       没有（方向、团队、销售大区、地点字段没给）= 一律保留。从尾部逐段判，遇到第一段不是地点就停，
       所以「Engineer - Payments - Shanghai」留下「Engineer - Payments」，第一段永远不动。
       括号里的「 - 」不是分段："Software Engineer (Remote - US)" 从那里截会留下半个括号，整条保留。
    地点字段为空时保留尾巴还有个用处：normalize 里的标题城市兜底（location_or_title_city）读得到它。
    ⚠️ 标题保留完整之后，读标题的地方要认得「 - 」后面是业务线不是岗位名：职能分类与方向认领在
       lib/china-keyword-expansion.js 的 _titleLeadSegment（Python 镜像 china_keyword_expansion._title_lead_segment），
       死链巡检去页面里找标题用 audit_dead_links._title_key。新增读标题的判定逻辑时照此处理。
    """
    t = strip_nul(title).strip()
    t = re.sub(r"\s+", " ", t)
    while True:
        last = None
        for last in _TITLE_SEP_RE.finditer(t):
            pass
        if last is None:
            return t
        tail = t[last.end():]
        closes = sum(tail.count(ch) for ch in _TITLE_CLOSE_BRACKETS)
        if closes > sum(tail.count(ch) for ch in _TITLE_OPEN_BRACKETS):
            return t
        if not _title_tail_repeats_location(tail, locations):
            return t
        t = t[:last.start()]


_HAS_DIGIT_RE = re.compile(r"\d")
# 门牌打头：首段第一个词以数字开头（"1090 73rd Ave NE" / "12F-13F" / "46-056 Kamehameha Hwy"）。
_HOUSE_NUMBER_LEAD_RE = re.compile(r"^\d")
# 站点编号 + 冒号打头（奥的斯 / 开利："CAI19: UTEC-Huntington" / "ARG02 : Chiclana 3345"），冒号后面才是地址。
_SITE_CODE_LEAD_RE = re.compile(r"^[A-Za-z]+\d\w*\s*:")
# 邮编只认 5 位（美 / 德 / 法 / 西…，可带美式 -4 位）和 6 位（中 / 印 / 新）。
# 4 位的不认：和门牌号、套间号（"Ste 2401"）分不开。
_POSTCODE = r"(?:\d{5}(?:-\d{4})?|\d{6})"
_POSTCODE_HEAD_RE = re.compile(rf"^{_POSTCODE}(?=\s|$)\s*")
_POSTCODE_TAIL_RE = re.compile(rf"(?:^|(?<=\s)){_POSTCODE}$")
_UNIT_WORDS = r"(?:suite|ste|unit|apt|spc|space|room|rm|floor|bldg|building)"
# 不带数字的套间 / 单元号（"Suite C" / "Unit A" / "SPC A"）：同样属于门牌，不是城市。
_UNIT_SEGMENT_RE = re.compile(rf"^{_UNIT_WORDS}\.?\s+\S+$", re.I)
# 套间号 / 信箱号后面直接跟着城市、中间没逗号（Target "Ste 80 Hattiesburg" / "NCD-0375 Brooklyn Park"）。
# 信箱号只认「字母-数字」这一种写法："17 Kai Cheung Road" / "26th Floor" / "T1 Office Tower" 后面那几个词
# 是街名 / 楼层 / 楼名，不是城市。
_UNIT_THEN_CITY_RE = re.compile(
    rf"^(?:(?:{_UNIT_WORDS}\.?\s+#?[\w-]+|[A-Za-z]+-\d+)\s+)+(?P<city>\D+)$", re.I)


def _is_street_level(segment: str) -> bool:
    return bool(_HAS_DIGIT_RE.search(segment) or _UNIT_SEGMENT_RE.match(segment))


def _without_postcode(segment: str) -> Optional[str]:
    """「MN 55432-3407」→「MN」、「46802 USA」→「USA」、「78190」→「」；不是「邮编 ± 地名」返回 None。"""
    for pattern in (_POSTCODE_TAIL_RE, _POSTCODE_HEAD_RE):
        rest = pattern.sub("", segment).strip()
        if rest != segment and not _HAS_DIGIT_RE.search(rest):
            return rest
    return None


def strip_street_address(location: str) -> str:
    """地点字段是整段门牌地址时，只留城市及其后面的部分；认不出就原样返回。

    ❌ 现象（2026-10-11 香港库）：Target 4,078 个在招岗的地点是「1000 Nicollet Mall, Minneapolis,MN 55403-2542」
       这类整段地址——对方在 ATS 里把「地点名」配成了门店地址（三星 / 富达 / 奥的斯 / 开利 / Sweetgreen 同样）。
       洞察抽屉取第一段当城市，写出「主要在 1000、7000、900」。
    ✅ 判据只看结构、不猜街道词：按逗号分段，**最后一个带数字的段**（门牌 / 楼层 / 信箱号）之后才是城市。
       那一段若只是「邮编 ± 地名」（"MN 55432-3407" / "46802 USA" / "35107 Allendorf"），先去掉邮编再判。
    ⚠️ 只有看得出「门牌在前、城市在后」才动，三种证据任一：首段以门牌号开头 / 首段是「站点编号:」/
       最后一个带数字的段是邮编、且前面另有带数字的段。马士基「CNSZH19, Shenzhen, 5th floor, Block A, …」
       「Suzhou Plant 2, Jiangsu, China」这类城市在前的写法一律不碰——截错了丢的是城市，宁可留着长地址。
    ⚠️ 截完没剩下东西（"1 New York Plaza" 整条只有门牌）也原样返回。
    国家 / 求职范围不受影响：normalize 用 geo_basis，截短后判不出国家时会退回原文。
    """
    if not _HAS_DIGIT_RE.search(location):
        return location
    if ";" in location:  # 一岗多地各自是一段地址（"347 Post Rd, Westport, CT 06880; Greenwich, CT"）
        parts = [part.strip() for part in location.split(";") if part.strip()]
        stripped = [strip_street_address(part) for part in parts]
        return "; ".join(stripped) if stripped != parts else location
    segments = [s.strip() for s in location.split(",")]
    if len(segments) < 2:
        return location
    numbered = [i for i, s in enumerate(segments) if _HAS_DIGIT_RE.search(s)]
    # 邮编要另有一段带数字的门牌作伴才算地址的证据：「Arden Hills, MN, US, 55112」只是城市后面挂了邮编，不动。
    bare = _without_postcode(segments[numbered[-1]]) if len(numbered) > 1 else None
    if bare is not None:
        segments[numbered[-1]] = bare
    elif not (_HOUSE_NUMBER_LEAD_RE.match(segments[0]) or _SITE_CODE_LEAD_RE.match(segments[0])):
        return location
    # max() 不会取空：去掉邮编的那条路要求另有一段带数字，另一条路首段自己就带数字。
    last_street = max(i for i, s in enumerate(segments) if _is_street_level(s))
    tail = [s for s in segments[last_street + 1:] if s]
    # 只看首段之后的段：首段「G3515 Miller Rd」里编号后面跟的是街名。
    glued = _UNIT_THEN_CITY_RE.match(segments[last_street]) if last_street > 0 else None
    if glued:
        tail.insert(0, glued.group("city").strip())
    return ", ".join(tail) if tail else location


# 多地并列写进库的连接符：与标题城市兜底（geo.title_city_location「连云港/苏州」）同一种写法，
# 读侧（/today 城市门、/jobs 城市筛选、全文检索的相邻双字）早就按它逐个城市匹配。
MULTI_PLACE_SEP = "/"
# 别名表里这两个目标值不是地点：与城市并存时城市优先（改前按别名表顺序也是城市在前）。
_NON_PLACE_ALIAS_TARGETS = frozenset({"全国", "远程"})
_LATIN_CITY_ALIASES = {
    alias: city for alias, city in CITY_ALIASES.items()
    if alias.isascii() and city not in _NON_PLACE_ALIAS_TARGETS
}
# 拼音按整词认（"xian" 不认 "Xiangyang"），后面跟着 Road / Rd / Street / Lu / Dadao… 的是路名不是城市
# （workday live：上海的门牌地址「…, West, Nanjing, Road, …」；拼音写法「Nanjing Xi Lu」）。
# 多认一个城市是把岗位推给不在那里的人，所以比 normalize_city 的子串严。
_LATIN_CITY_RE = re.compile(
    r"(?<![a-z])(?:" + "|".join(re.escape(a) for a in sorted(_LATIN_CITY_ALIASES, key=len, reverse=True)) + r")(?![a-z])"
    r"(?!(?:[\s,]+(?:east|west|north|south|middle|central|e|w|n|s|dong|xi|nan|bei|zhong))?"
    r"[\s,]+(?:road|rd|street|st|avenue|ave|boulevard|blvd|lu|dadao|jie|dajie)(?![a-z]))"
)
# 别名表里、省-地级映射表外的中文城市（新加坡）。
_OFF_GAZETTEER_CITIES = tuple(sorted({
    city for alias, city in CITY_ALIASES.items()
    if alias == city and not alias.isascii() and city not in _NON_PLACE_ALIAS_TARGETS
    and cn_place_province(city) is None
}))


def _scan_places(location: Optional[str]) -> list:
    """地点串里并列写着的地方 → [(键, 写出去的名字)]，按出现顺序、同一个地方只留第一次出现的写法。

    键 = 规范短名（「保定」「保定市」同一个键），只用来判「是不是同一个地方」。
    写出去的名字：别名表里的城市用规范名（「深圳市」→ 深圳）；别名表外的保留原文写法
    （「保定市」「阿里地区」「阿坝藏族羌族自治州」）——这类地方单独出现时库里一直是原样写法，用户目标填
    「保定」「保定市」都匹配得上（读侧是子串），并列时也得一样；裸写的「阿里」「兴安」再清洗一遍还认不回来。
    """
    text = re.sub(r"\s+", " ", strip_nul(str(location or ""))).strip()
    hits = []                             # (位置, 键, 写出去的名字, 所在省, 是不是省级)
    for pos, name, province, is_province, written in location_cn_places(text):
        city = CITY_ALIASES.get(name)
        hits.append((pos, city or name, city or written, province, is_province))
    for m in _LATIN_CITY_RE.finditer(text.lower()):
        city = _LATIN_CITY_ALIASES[m.group()]
        hits.append((m.start(), city, city, cn_place_province(city), False))
    for city in _OFF_GAZETTEER_CITIES:
        pos = text.find(city)
        if pos >= 0:
            hits.append((pos, city, city, None, False))
    hits.sort(key=lambda hit: hit[0])
    city_provinces = {province for _, _, _, province, is_province in hits if province and not is_province}
    places, seen = [], set()
    for _, key, shown, province, is_province in hits:
        if is_province and province in city_provinces:
            continue                      # 省被本省城市盖住 = 同一个地点的上下级
        if key not in seen:
            seen.add(key)
            places.append((key, shown))
    return places


def location_places(location: Optional[str]) -> list:
    """地点串里并列写着哪几个地方（没写到城市的省保留省名），按出现顺序去重。

    同一个地点的上下级只算一个：「广东省,深圳市,南山区」→ [深圳]（省被本省城市盖住，区县不在词表里）。
    中文地名的认法见 geo.location_cn_places；拼音 / 英文只认 CITY_ALIASES 里的城市；写法见 _scan_places。
    """
    return [shown for _, shown in _scan_places(location)]


def location_place_keys(location: Optional[str]) -> set:
    """同上，但给的是判「是不是同一个地方」用的键（「保定」「保定市」是同一个）。"""
    return {key for key, _ in _scan_places(location)}


# 折叠时哪些拼音 / 英文别名不算数：只排除「看得出是别的词或路名的一部分」的，其余照认（2026-10-12 live 逐条核过）。
# 比上面认「并列地点」的 _LATIN_CITY_RE 松——那条是往结果里加城市，要两边都是空格 / 标点；这条是不把原来折对的改丢：
#   · 前面粘着字母的不认（「C|hangzhou」常州、「Z|hangzhou」漳州、「Tong|xian|g」桐乡），驼峰的大写处除外
#     （workday 把几段粘着写：「ChinaShandong|Qingdao|266000」）；
#   · 后面跟着小写字母的不认（「Xian|yue」）；跟着大写字母的是粘写，照认（「Xian|China」「Suzhou|Jiangsu」「SINGAPORE|UNITS」）；
#   · xian 后面是 g / yang / ning / tao / ju / you 的不认，不分大小写：xiang… 是另一个音节（湘潭 / 襄阳 / 桐乡），
#     XianYang 咸阳、XianNing 咸宁、XianTao 仙桃、XianJu 仙居、XianYou 仙游；
#   · 后面是路名的不认：Road / Street / Avenue / Dadao 这类整词，或「方位词 + St / Lu / Jie」（「Nanjing Xi Lu」）。
#     光秃秃的 St / Lu / Jie 不算证据（「Shanghai, St. Regis」）。
# 要喂原文：大小写是判断边界的依据。
_ROAD_DIRECTION = r"(?:east|west|north|south|middle|central|e|w|n|s|dong|xi|nan|bei|zhong)"
_LATIN_FOLD_RE = re.compile(
    r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))(?i:"
    + "|".join(re.escape(a) + (r"(?!g|yang|ning|tao|ju|you)" if a == "xian" else "")
               for a in sorted(_LATIN_CITY_ALIASES, key=len, reverse=True))
    + r")(?![a-z])"
    r"(?!(?i:(?:[\s,]+" + _ROAD_DIRECTION + r")?[\s,]+(?:road|rd|street|avenue|ave|boulevard|blvd|dadao|dajie)"
    r"|[\s,]+" + _ROAD_DIRECTION + r"[\s,]+(?:st|lu|jie))(?![A-Za-z]))"
)


def _fold_city(loc: str) -> str:
    """入库清洗用的折叠：与 normalize_city 同一张别名表、同一个顺序，只是拼音 / 英文城市名要过 _LATIN_FOLD_RE
    （「Changzhou」里的 hangzhou、「Xinxiang」里的 xian 不算，后面跟着 Road 的是路名）。中文别名、「remote」仍按子串。"""
    key = loc.lower()
    if key in CITY_ALIASES:
        return CITY_ALIASES[key]
    latin = {m.group().lower() for m in _LATIN_FOLD_RE.finditer(loc)}
    for alias, city in CITY_ALIASES.items():
        if (alias in latin) if alias in _LATIN_CITY_ALIASES else (alias in key):
            return city
    return loc


def clean_location(location: Optional[str]) -> Optional[str]:
    """清洗地点字段：整段门牌地址先截成城市段；单个地点折成别名表里的城市名；多地并列的逐个折、用「/」连起来。

    🚫 多地并列不许整串折成一个城市（2026-10-11）：
    ❌ `normalize_city` 是子串折叠——串里只要出现别名表里的城市就整串换成它，换成哪个取决于别名表顺序：
       「北京市 广东·深圳市 上海市」→「北京」、「中山市,广州市」→「广州」、「吉林·长春市 辽宁·沈阳市」→「长春」。
       读侧「地点非空且对不上目标城市」是硬拒（lib/opportunities/eligibility.ts locationState），
       所以一个在北京 / 深圳 / 上海都招的岗只有北京的用户看得到。
    ✅ 只动「会被折叠、且串里并列写着不止一个地方」的行：
       · 串里没有别名表里的城市 → 原样返回（改前就不折，每个城市都匹配得上）；
       · 只写了一个地方（含上下级写法）→ 与改前逐字相同。

    🚫 串里有别名城市的那几个字，不等于岗位在那个城市（2026-10-12）：
    ❌ 「黑龙江省·牡丹江市·西安区」→ 西安、「宁波杭州湾新区」→ 杭州、「Changzhou, Jiangsu, China」→ 杭州
       （hangzhou 是 changzhou 的子串）、「Beijing East Road, Shanghai」→ 北京：岗位被写成一个它不在的城市，
       推给了不在那里的人，真正所在城市的人反而被硬拒。
    ✅ 只在能证明折错的时候纠正，证明不了就维持折叠（不把原来对的城市改丢）：
       · 拼音 / 英文别名：看得出是别的词或路名的一部分的不认（_LATIN_FOLD_RE）；认不出城市的英文串原样入库，
         国家照样判得出；
       · 中文：严格识别（location_places）在串里认出了别的地方、没认出折出来的城市，而且那几个字每一处都只是
         别的地名 / 路名的一部分（geo.cn_name_is_part_of_another_place：后面是区 / 路 / 街、跨在别的地名上、
         紧跟在另一个城市后面的「X湾」）→ 用严格识别的结果（牡丹江市 / 宁波）；
       · 其余照旧。严格识别只在段首和省名后面认地名，它没认出来不等于折错：「华东区上海」「四川天府新区成都片区」
         「可在北京 天津 青岛」「广州深圳等地」里的上海 / 成都 / 北京 / 深圳都是真的。
    """
    if not location:
        return None
    loc = strip_nul(location).strip()
    loc = re.sub(r"\s+", " ", loc)
    if loc.lower() in ("unknown", "multiple locations", "various", ""):
        return None
    locality = strip_street_address(loc)
    if locality == loc:
        return _fold_cities(loc)
    city = _fold_address(locality)
    if city == locality:
        # 截掉门牌后认不出城市别名、整段地址却认得出（城市名只写在街名 / 楼名里）：保住原先折出来的城市，
        # 不让一个本来筛得到「上海」的岗因为截短而筛不到。
        whole = _fold_address(loc)
        if whole != loc:
            return whole
    return city


def _fold_cities(loc: str) -> str:
    """别名折叠（单个地点 / 多地并列 / 折错纠正），规则见 clean_location 的说明。"""
    folded = _fold_city(loc)
    if folded == loc:
        return folded
    places = location_places(loc)
    if folded in places:
        return MULTI_PLACE_SEP.join(places)       # 只写了一个地方时就是 folded 本身
    if places and folded not in _NON_PLACE_ALIAS_TARGETS and cn_name_is_part_of_another_place(loc, folded):
        return MULTI_PLACE_SEP.join(places)
    return folded


def _fold_address(text: str) -> str:
    """一段门牌地址的别名折叠：地址只是一个地点，写到的城市不止一个时以最后那个为准。

    地址从小写到大（楼 → 路 → 区 → 城市），前面出现的城市名是楼名 / 路名：奥的斯武汉办公室在
    「Hong Kong Center, Wusheng Road, Qiaokou District, Wuhan, Hubei, China」，按多地并列折会写成「香港/武汉」、
    国家判成香港。分号隔开的是几处地址（一岗多地），照常按多地折。
    """
    if ";" in text:
        return _fold_cities(text)
    places = location_places(text)
    return places[-1] if places else _fold_city(text)


def keeps_every_place(location: str, places) -> bool:
    """location 过完清洗之后，places 里的每个地点是不是都还在（清洗认不出的地点算丢了）。"""
    cleaned = clean_location(location)
    if not cleaned:
        return False
    if cleaned == re.sub(r"\s+", " ", strip_nul(location)).strip():
        return True                       # 串里没有别名表里的城市：原样入库，每个地点都匹配得上
    kept = location_place_keys(cleaned)
    for place in places:
        named = location_place_keys(place)
        if not named or not kept.issuperset(named):
            return False
    return True


def join_places(names) -> Optional[str]:
    """adapter 手里是「这个岗在哪几个城市」的列表时，交给 RawJob.location 的写法。

    每个城市清洗后都还在 → 用「、」连起来全部交出去（clean_location 会逐个折成「北京/上海」）。
    下面两种情况只交第一个，即 2026-10-11 前各 adapter 的做法：
      · 有清洗认不出的（境外城市、不带城市名的写法）：并进来只会被丢掉，「圣何塞、北京」还会折成北京、
        把原来写库的第一个城市挤掉；
      · 并起来国家会变：国家码只有一个、按词表顺序取，「约翰内斯堡、曼谷」会从 ZA 变成 TH，
        列表里有台北的还会被出口整行拒收。内地与港澳并列不算换国家（都在国内范围）。
    """
    seen = []
    for name in names or ():
        name = str(name or "").strip()
        if name and name not in seen:
            seen.append(name)
    if not seen:
        return None
    if len(seen) == 1:
        return seen[0]
    # 每个名字要么清洗认得出，要么至少判得出国家：都不是的（部门名、台湾词表刻意不收的裸「台中」）
    # 在「列表里没有别名表城市 → 清洗原样保留」的情况下会原样进库。
    if not all(location_place_keys(name) or derive_country_code(name) for name in seen):
        return seen[0]
    joined = "、".join(seen)
    if not keeps_every_place(joined, seen):
        return seen[0]
    before, after = derive_country_code(seen[0]), derive_country_code(joined)
    if before != after and not (before in _GREATER_CHINA and after in _GREATER_CHINA):
        return seen[0]
    return joined


def geo_basis(raw_location: Optional[str], cleaned: Optional[str]) -> Optional[str]:
    """判国家 / 求职范围用的地点文本：展示用别名把国家信息吃掉时，退回别名之前的原文。

    `normalize_city` 是**子串**折叠：地点里只要出现 "remote" 就整串变成「远程」——
    "United States - Remote" / "Remote Germany" / "China - Remote" 全都成了同一个「远程」，
    derive_country_code 拿到的只剩一个没有国家的词，于是按 source.regions 兜底，
    regions 含 CN 的外企源就把美国远程岗判成 domestic。
    2026-09-23 香港库实测：workday 在招岗 country_code 为空却判 domestic 的 6,526 行里
    4,383 行（67%）存的就是「远程」，路径原文是 United-States---Remote / Remote-Mexico /
    UK-Remote …；smartrecruiters 在 adapter 出口把 "Remote de" 展开成 "Remote Germany"
    （见其 _ISO2_COUNTRY_NAMES 注释）也是被这一步抹掉的。

    只在「别名后的文本判不出国家」时才看原文：CITY_ALIASES 的目标值里只有「远程」判不出国家
    （其余都是大陆城市 / 香港 / 新加坡），所以本函数**只改变被折叠成「远程」的那批行**，
    其它地点逐字走旧路径。展示用的 location 列不动。
    """
    if not cleaned or derive_country_code(cleaned) is not None:
        return cleaned
    raw = re.sub(r"\s+", " ", strip_nul(raw_location or "")).strip()
    return raw or cleaned


def scope_depends_on_regions(location: Optional[str]) -> bool:
    """这个地点的 job_scope 是不是只能按 source.regions 猜（没说国家、也没钉在境外）。

    定义成「CN 源和纯海外源会给出不同答案」，而不是把 derive_job_scope 的判断步骤抄一遍：
    derive_job_scope 以后多一道判据，这里自动跟上，两处不会漂移。
    """
    return derive_job_scope(location, {"CN"}) != derive_job_scope(location, {"US"})


def needs_declared_country(raw_location: Optional[str]) -> bool:
    """adapter 要不要去问对方「这个岗在哪国」（见 RawJob.country_code）。

    与 normalize 判国家用的是同一份文本（geo_basis），所以 normalize 会采信自报国家的岗，adapter
    一定问过。唯一的多问：地点为空时 normalize 还会从标题认城市（location_or_title_city），
    标题认出城市就以城市为准，问来的国家用不上——多一次请求，不会判错。
    """
    return scope_depends_on_regions(geo_basis(raw_location, clean_location(raw_location)))


_ISO_ALPHA2 = frozenset(ISO_ALPHA2_CODES)


def _declared_country(raw: RawJob) -> Optional[str]:
    code = (getattr(raw, "country_code", None) or "").strip().upper()
    return code if code in _ISO_ALPHA2 else None


def _country_and_scope(raw: RawJob, geo_location: Optional[str], regions) -> tuple:
    """(country_code, job_scope)。地点能说清的一律以地点为准（与改前逐字相同）；
    只有地点说不清、原本要按 source.regions 猜的，才改用对方 ATS 自报的国家。"""
    declared = _declared_country(raw)
    if declared and scope_depends_on_regions(geo_location):
        return declared, ("domestic" if declared in _GREATER_CHINA else "overseas")
    return derive_country_code(geo_location), derive_job_scope(geo_location, source_regions(regions))


def clean_summary(summary: Optional[str], max_chars: int = 400) -> Optional[str]:
    """截断摘要到 max_chars 字，在词边界截断。"""
    if not summary:
        return None
    s = strip_nul(summary).strip()
    # 先解 HTML 实体（greenhouse 等接口 content 是实体编码的 &lt;p&gt;…，不解码会原样显示乱码）。
    # 解两遍兜底双重编码（&amp;lt; → &lt; → <）。
    s = html.unescape(html.unescape(s))
    s = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", s, flags=re.IGNORECASE)  # 去脚本/样式块
    s = re.sub(r"<[^>]+>", " ", s)  # 去 HTML 标签
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= max_chars:
        return s
    # 在词边界截断
    truncated = s[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.8:
        truncated = truncated[:last_space]
    return truncated.strip() + "…"


def clean_salary(salary_text: Optional[str]) -> Optional[str]:
    """清洗薪资文本，不过滤内容。"""
    if not salary_text:
        return None
    s = strip_nul(salary_text).strip()
    if s.lower() in ("competitive", "negotiable", "面议", "薪资面议", ""):
        return s
    return s


def source_regions(regions=None) -> set[str]:
    if not regions:
        return {"CN"}
    if isinstance(regions, str):
        text = regions.strip()
        regions = text[1:-1].split(",") if text.startswith("{") and text.endswith("}") else text.split(",")
    return {str(r).strip() for r in regions if str(r).strip()} or {"CN"}


def location_or_title_city(location: Optional[str], title: Optional[str]) -> Optional[str]:
    """写库用的地点：adapter 给了就用它（已过 clean_location）；给空了才从标题认城市。

    物化进 location 而不是读时现算：/today 召回的城市门、stage-2 的 locationState、/jobs 城市筛选、
    卡片展示都直接读 location 列，只在一处派生就不会有哪条读路径漏掉兜底。判据见 geo.title_city_location。
    run.py（normalize）与 discovery._upsert_raw_jobs 两条写库链都走这里，app 侧镜像在 lib/jobs-store/write.ts。
    """
    return location or title_city_location(title)


def location_in_source_regions(location: Optional[str], regions=None) -> bool:
    return location_in_scope(location, source_regions(regions))


def make_content_hash(title: str, location: Optional[str], summary: Optional[str]) -> str:
    """生成岗位内容 hash，用于判断是否变化。"""
    raw = f"{title}|{location or ''}|{summary or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize(raw: RawJob, *, source_id: str, company: str, regions=None) -> dict:
    location = clean_location(raw.location)
    title = clean_title(raw.title, raw.location, location)
    full_summary = clean_summary(raw.summary)
    salary = clean_salary(raw.salary_text)
    job_type = (
        raw.job_type
        if is_recruitment_type(raw.job_type)
        else (extract_job_type(title, full_summary) or raw.job_type)
    )
    # hash 按 adapter 给的地点算：标题城市是标题的纯函数、不带新信息，这样上线不会让存量行的 hash 集体翻一遍。
    content_hash = make_content_hash(title, location, full_summary)
    location = location_or_title_city(location, title)
    # 必须排在标题兜底之后：country_code / job_scope 要按最终写进库的地点算（标题城市 → CN）。
    geo_location = geo_basis(raw.location, location)
    country_code, job_scope = _country_and_scope(raw, geo_location, regions)
    experience = raw.experience or extract_experience(raw.summary)
    education = raw.education or extract_education(raw.summary)
    deadline = raw.deadline or extract_deadline(raw.summary)

    # 出口统一剥 NUL：title/location/summary/salary 已在各自 clean_* 里剥过（content_hash 也因此
    # 建立在干净文本上），这里兜住不过清洗器的字段——company / jd_url / experience / education /
    # deadline 等任何一个带 NUL 都会让整源写库炸掉（见 strip_nul 注释）。
    return {k: strip_nul(v) for k, v in {
        "source_id": source_id,
        "company": raw.company or company,
        "title": title,
        "location": location,
        "country_code": country_code,
        "job_scope": job_scope,
        "job_type": job_type,
        # 届别只认硬信号（2027届/27届/2027校招/Class of 2027…），抽不出留 None。
        # 绝不靠入库时间兜底——8 月同时在抓 2027 届新岗与 2026 届收尾岗，猜错=把往届岗
        # 标成当季让用户白投一轮。留白不隐藏：无届别的岗照常展示（详见 crawler/grad_class.py）。
        "grad_class": extract_grad_class(title, job_type, full_summary),
        "summary": full_summary,
        "sponsorship_signal": sponsorship_signal(" ".join(x for x in (raw.title, full_summary) if x)),
        "jd_url": raw.jd_url,
        "apply_url": raw.apply_url,
        "salary_text": salary,
        "posted_at": raw.posted_at,
        "experience": experience,
        "education": education,
        "deadline": deadline,
        "content_hash": content_hash,
        "status": "active",
    }.items()}


# 整词 intern / internship(s)。re.ASCII 让 \b 只认 ASCII 字母数字下划线 —— 与 JS 那边同一条正则的语义一致
# （lib/china-keyword-expansion.js 的 hasInternSignal）。不带它时 Python 把汉字也当词字符，「商务intern」里
# 「务」和 i 之间没有边界，整条不命中。2026-10-11 全库在招岗对拍：两端判法不同的 6 个（猿辅导 4、VAST 1、
# 启元机器人 1），全是实习岗；internal / international 贴着汉字照样不命中（见 test_job_type_en）。
INTERN_WORD_RE = re.compile(r"\bintern(?:ship)?s?\b", re.I | re.A)


def extract_job_type(title: str, summary: Optional[str] = None) -> Optional[str]:
    """从标题和摘要中推断岗位类型。"""
    text = f"{title} {summary or ''}".lower()
    title_text = str(title or "").lower()

    # 层0：实习**只认标题**，且优先于下面所有看全文的规则。两个方向的坑都在这一层堵：
    #   ① 实习被抢走：校招 / 留学生专项 / 管培生 三条规则都看「标题+整段正文」且原本排在实习之前，
    #      而实习 JD 正文常写「面向 2027 届应届生」「留学生亦可」→ `研发实习生` 被标成校招、
    #      `运维实习生` 被标成留学生专项，实习用户在实习专区收不到这些岗。
    #   ② 社招被误标实习：正文里「有大厂实习经历者优先」是社招 JD 高频词，看全文会把
    #      `高级后端工程师` 标成实习 —— 错标实习的危害更大（会把资深岗推给实习生，
    #      见 recruitmentCategory 层1「实习自报最权威」）。
    # 取舍：宁可漏判「标题没写但正文写明」的少数实习岗，也不能把社招错标成实习。
    # 读时侧 recruitmentCategory 还有 url 门户层可以兜底。
    if "实习" in title_text or INTERN_WORD_RE.search(title_text):
        if "暑期实习" in text or re.search(r"summer(?:\s+\d{4})?\s+intern(ship)?s?\b", text, re.I):
            return "暑期实习"
        if any(w in text for w in ("日常实习", "daily intern", "off-cycle intern")):
            return "日常实习"
        return "实习"
    if any(w in text for w in ("管培生", "管理培训生", "graduate program", "management trainee")):
        return "管培生"
    if any(w in text for w in ("留学生", "海外学生", "overseas student", "returnee")):
        return "留学生专项"
    # 校招只认强标记；砍掉弱词 "graduate"(=硕士学历) / "campus"(=办公园区/智慧校园) —— 它们在整段
    # JD 正文里高频误命中，把要经验的社招岗写成校招（与前端 normalizeChinaJobType 同款收紧）。
    if any(w in text for w in ("校招", "校园招聘", "应届", "new grad")):
        return "校招"
    if re.search(r"\b(university\s+graduate|entry[-\s]?level)\b", text, re.I):
        return "校招"
    # （原本这里有一条「看全文判实习」的兜底，已上移到层0 并收紧成只认标题——
    #   保留在这里会让正文的「有实习经历者优先」把社招岗标成实习。见层0 注释。）
    if any(
        w in text
        for w in ("投研", "研究员", "研究岗", "行业研究", "股票研究", "equity research", "investment research")
    ):
        return "研究岗"
    if any(w in text for w in ("兼职", "part time", "part-time")):
        return "兼职"
    if any(w in text for w in ("社招", "社会招聘", "experienced", "professional")):
        return "社招"
    if re.search(r"\b(senior|staff|principal|lead|distinguished)\b", text, re.I):
        return "社招"
    if "全职" in text:
        return "全职"
    return None


# adapter 直填的 job_type 到底是「真招聘类型」(社招/校招/实习…)还是「职能/类别名」(研发/业务类/编码)？
# 用途：run.py 据此决定信任 adapter 直填(真类型来自来源 recruitType/渠道，最可信)还是退回正文推断
# (adapter 把职能名塞进 job_type 时，如 feishu/bytedance 的 job_category)。与前端 sourceDeclaredCategory 同口径。
# 刻意不含"全职/兼职"(=用工模式而非招聘类型) —— 让它们退回正文推断，便于被正文里的"应届"等细化。
_RECRUIT_TYPE_WORDS = (
    "实习", "intern", "校招", "校园招聘", "应届", "管培", "管理培训生", "留学生", "毕业生",
    "社招", "社会招聘", "社会招募", "campus", "new grad", "graduate program",
    "experienced", "professional", "研究岗", "投研",
)


def is_recruitment_type(value: Optional[str]) -> bool:
    """value 是否为可识别的招聘类型取值（用于判断能否信任 adapter 直填的 job_type）。"""
    if not value:
        return False
    t = str(value).strip().lower()
    return any(w in t for w in _RECRUIT_TYPE_WORDS)


def _strip_html(text: Optional[str]) -> str:
    """去 HTML 标签 + 折叠空白（结构化抽取的统一预处理）。"""
    if not text:
        return ""
    s = re.sub(r"<[^>]+>", " ", str(text))
    return re.sub(r"\s+", " ", s).strip()


def _fmt_years(m) -> str:
    """把经验正则的命中格式化成 'a-b年' 或 'a年+'。"""
    g2 = m.group(2) if m.re.groups >= 2 else None
    return f"{m.group(1)}-{g2}年" if g2 else f"{m.group(1)}年+"


def extract_experience(text: Optional[str]) -> Optional[str]:
    """从完整 JD 抽取经验要求（如 '3-5年' / '5年+' / '应届/不限'）；抽不到返回 None。
    与前端 JobCard.extractExperience 同口径，但跑在未截断的全文上。"""
    base = _strip_html(text)
    if not base:
        return None
    t = re.sub(r"\s+", "", base)  # 去空格（中文 JD 习惯，且利于英文 '3-5 years' 匹配）
    if re.search(r"应届|无经验要求|经验不限|不限经验|no experience|entry level|entrylevel", t, re.I):
        return "应届/不限"
    m = re.search(r"(\d+)[-~至到](\d+)年", t) or re.search(r"(\d+)年(?:以上)?(?:工作)?经验", t)
    if m:
        return _fmt_years(m)
    m = re.search(r"(\d+)[-~to]+(\d+)years?", t, re.I) or re.search(r"(\d+)\+?years?(?:ofexperience)?", t, re.I)
    if m:
        return _fmt_years(m)
    if re.search(r"\b(principal|distinguished)\b", base, re.I):
        return "12年+"
    if re.search(r"\b(staff|lead)\b", base, re.I):
        return "8年+"
    if re.search(r"\bsenior\b", base, re.I):
        return "5年+"
    if re.search(r"\b(mid[-\s]?level|intermediate)\b", base, re.I):
        return "3年+"
    if re.search(r"\bjunior\b", base, re.I):
        return "应届/不限"
    return None


def extract_education(text: Optional[str]) -> Optional[str]:
    """从完整 JD 抽取学历要求（博士/硕士/本科/大专/不限）；抽不到返回 None。"""
    base = _strip_html(text)
    if not base:
        return None
    t = re.sub(r"\s+", "", base)
    if re.search(r"博士|ph\.?d|doctorofphilosophy|doctora", t, re.I):
        return "博士"
    if re.search(r"硕士|研究生|master'?s?|m\.?s\.?|m\.?eng|m\.?sc", t, re.I):
        return "硕士"
    if re.search(r"本科|学士|bachelor'?s?|b\.?s\.?|b\.?a\.?|b\.?sc|undergrad", t, re.I):
        return "本科"
    if re.search(r"大专|专科|associate('?s)?degree", t, re.I):
        return "大专"
    if re.search(r"学历不限|不限学历", base):
        return "不限"
    return None


# ⛔ 正文里的「截止 / 截至 + 日期」多数不是投递截止日，判不出的一律不抽（2026-10-10 立）。
# ❌ 现象：一汽 16 个岗的正文写「以上时间计算截至2026年6月1日」（工龄基准日），被抽成截止日 2026-6-1；
#    全库 30,507 行「长期有效」里，库里正文真写着「长期有效 / 长期招聘」的只有 43 行，其余几乎都是
#    英文 JD 里的 long-term（福利条款）/ rolling（Rolling Forecast）触发的。
# ✅ 判据：① 「长期有效」只认明确的说法，不认裸的 long term / rolling；
#    ② 日期前（同一句、往前 14 个字）出现资格条件词 → 它算的是年龄 / 工龄的时点，跳过；
#    ③ 「截止 / 截至」必须带报名类前缀，或紧跟「日期 / 时间」——裸的「截至2022年9月30日，用户数已达…」
#       是统计时点；deadline 这个词本身指向够明确，不要求前缀。
#    同一套资格条件词在 announcements/deadline.py 立过一次（公告正文的同一种误抽）。
# ⚠️ 与前端 lib/job-fields.ts 的 extractDeadline 同口径，两端共读 tests/fixtures/deadline-text-cases.json。
# 📌 同日补两处（先在 15,666 段真实正文上与上面这版逐条对拍：库里正文能触发旧规则的 3,094 个在招岗 +
#    greenhouse / ashby / lever 95 个源重拉的 12,451 段未截断正文 + 逐岗取回的 121 段官网全文）：
#    ① 中文「长期有效 / 长期招聘」也要看前后文。上面写「库里正文真写着的只有 43 行」，没往下看它们写的是什么：
#       同日复核库里正文含这两个词的在招岗 55 行，是招聘声明的只有 3 行，其余 52 行是「建立长期有效合作关系」
#       「以长期招聘为目的的公关活动」一类。现在只认：后接「岗位 / 职位」、括号里单独一句、后接「招满即止 /
#       欢迎投递」、主语是岗位 / 招聘且到句末、「截止日期：/ 招聘时间：」这类标签之后。rolling basis 同一句要有招聘类词
#       （全文里 71 处，3 处说的是实习生入职时间、项目确认）。全文重放：旧规则标 2,939 行 → 招聘声明 81 行。
#    ② 「截止 + 报名类词 + 时间 / 日期」也算（「本岗位截止投递时间为2026年10月31日」）：五矿 13 个岗正文这么写，
#       与平台自己给的下线时间逐个相同（13/13），是真截止日，上一版从正文抽不到。
#       （这 13 行库里的值是平台给的、不靠正文，所以这一处当前不改变库里任何一行。）
#    两端逐字一致靠三件事：正则都带 re.A（\b、\d、忽略大小写按 ASCII 算，和 JS 一样——否则全角数字的日期
#    Python 认、JS 不认）；年份只收 2000–2100（JS 的 Date.UTC 把 0–99 年当成 19xx，3000-01-01 这类占位也顺带挡掉）；
#    JS 那边先做和 _strip_html 一样的预处理。
_OPEN_ENDED_CN = re.compile(r"长期(?:有效|招聘)")
_OPEN_ENDED_CN_TAIL = re.compile(r"[，,、；; ]{0,2}(?:招满即止|招满为止|欢迎(?:随时)?(?:投递|应聘|报名)|随时投递)")
_OPEN_ENDED_CN_SUBJECT = re.compile(r"(?:岗位|职位|招聘(?:信息|公告|启事|需求)?)(?:为|是|属|系|均为|[：:])? ?$")
_OPEN_ENDED_CN_END = re.compile(r"中?(?:$|[ ，,。.；;！!、）)】\]])")
_OPEN_ENDED_CN_LABEL = re.compile(
    r"(?:截止日期|截止时间|(?:招聘|岗位|职位)有效期|招聘期限|招聘时间|招聘周期|报名时间|投递时间|申请时间)"
    r"(?:为|是|[：:】\]])? ?$")
# 括号前是证件 / 合同：「持有教师资格证（长期有效）」说的是证，不是岗位。
_OPEN_ENDED_CN_NOT_POSTING = re.compile(r"(?:证|证书|证件|执照|驾照|护照|签证|合同|协议|资质|资格)$")
_OPEN_ENDED_EN = re.compile(r"until filled|rolling (?:basis|applications?|admissions?)", re.I | re.A)
# hire / hiring 才是招聘动作；hires / hired 多是「新员工」（New hires start on a rolling basis 说的是入职）。
_HIRING_EN = re.compile(
    r"applicat|appl(?:y|ies|ied|ying)\b|resumes?\b|candidates?\b|recruit|\bhir(?:e|ing)\b|interview|admission",
    re.I | re.A)
_EN_SENTENCE_END = ".!?;。；！？"
_DEADLINE_CANDIDATE = re.compile(
    r"(截止|截至|deadline)([^0-9]{0,8})(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", re.I | re.A)
_DEADLINE_QUALIFY = re.compile(
    r"计算|有效期|年龄|周岁|学历|学位|工作经[历验]|工作年限|工龄|服务期|户籍|缴费|资格审查|毕业|出生")
_DEADLINE_APPLY = re.compile(r"报名|投递|申请|应聘|网申|简历|招聘|招募")
_DEADLINE_LOOKBACK = 14
_SENTENCE_BREAK = re.compile(r"[。；;！!？?\n]")


def _same_sentence(base: str, start: int, end: int) -> str:
    """命中处所在的那一句：往前 80 字、往后 40 字，各自到最近的句末标点为止。"""
    before = base[max(0, start - 80):start]
    before = before[max(before.rfind(ch) for ch in _EN_SENTENCE_END) + 1:]
    after = base[end:end + 40]
    cuts = [i for i in (after.find(ch) for ch in _EN_SENTENCE_END) if i >= 0]
    return before + " " + (after[:min(cuts)] if cuts else after)


def _declares_open_ended(base: str) -> bool:
    """正文是不是在声明「这个岗长期招聘 / 招满为止」，而不是碰巧用了这几个词。"""
    for m in _OPEN_ENDED_CN.finditer(base):
        before, after = base[max(0, m.start() - 8):m.start()], base[m.end():m.end() + 10]
        if before.endswith("中"):
            continue  # 中长期招聘规划
        if after.startswith(("岗位", "职位")) and _OPEN_ENDED_CN_END.match(after[2:]):
            return True  # 长期招聘岗位）——后面还接着「的简历筛选」就是招聘岗的工作内容
        lead = before.rstrip(" ")
        opener, closer = lead[-1:], after.lstrip(" ")[:1]
        if (opener and opener in "（(【[" and closer and closer in "）)】]"
                and not _OPEN_ENDED_CN_NOT_POSTING.search(lead[:-1])):
            return True  # （长期有效）
        if _OPEN_ENDED_CN_TAIL.match(after):
            return True
        if _OPEN_ENDED_CN_SUBJECT.search(before) and _OPEN_ENDED_CN_END.match(after):
            return True
        if _OPEN_ENDED_CN_LABEL.search(before):
            return True
    for m in _OPEN_ENDED_EN.finditer(base):
        if not m.group(0).lower().endswith("basis"):
            return True  # until filled / rolling applications / rolling admissions
        if _HIRING_EN.search(_same_sentence(base, m.start(), m.end())):
            return True
    return False


def extract_deadline(text: Optional[str]) -> Optional[str]:
    """从完整 JD 抽取投递截止（ISO 日期 或 '长期有效'）；抽不到返回 None。"""
    base = _strip_html(text)
    if not base:
        return None
    if _declares_open_ended(base):
        return "长期有效"
    for m in _DEADLINE_CANDIDATE.finditer(base):
        before = _SENTENCE_BREAK.split(base[max(0, m.start() - _DEADLINE_LOOKBACK):m.start()])[-1]
        if _DEADLINE_QUALIFY.search(before):
            continue
        gap = m.group(2)
        applied = _DEADLINE_APPLY.match(gap)   # 截止投递时间为… → 去掉报名类词后同样要紧跟「时间 / 日期」
        label = gap[applied.end():] if applied else gap
        if m.group(1).lower() != "deadline" and not (
                _DEADLINE_APPLY.search(before) or label.startswith(("日期", "时间"))):
            continue
        if not 2000 <= int(m.group(3)) <= 2100:
            continue   # 3000-01-01 这类占位、年份抄错的 → 不是能投的截止日
        try:
            return date(int(m.group(3)), int(m.group(4)), int(m.group(5))).isoformat()
        except ValueError:
            continue   # 13 月 / 40 日这类 → 当作没抽到，接着找下一处
    return None


# 各招聘接口里常见的"发布/更新时间"字段名（防御式：命中哪个用哪个，缺失则 None，不伪造）。
# 已 live 确认（2026-06-02，浏览器拦截 /api/v1/search/job/posts）：Feishu/Lark 招聘平台
# —— 字节 jobs.bytedance.com + 飞书系 *.jobs.feishu.cn（蔚来/小鹏/地平线/小米）—— 顶层字段就叫
# `publish_time`（epoch 毫秒），10/10 岗位均有值。其余字段名为其它平台保留的兜底候选。
PUBLISH_TIME_FIELDS = (
    "publish_time", "publishTime", "first_publish_time", "online_time", "onlineTime",
    "create_time", "createTime", "update_time", "updateTime", "modify_time",
    "publish_date", "post_time", "posted_at", "pub_time",
)


def coerce_iso_date(value) -> Optional[str]:
    """把 epoch(ms/s) 或带分隔符的日期字符串归一成 ISO date（YYYY-MM-DD）；无法识别返回 None。"""
    if value is None or value == "":
        return None
    try:
        n = float(value)
        if n > 1e12:  # 毫秒
            n = n / 1000.0
        if n > 1e9:   # 秒级 epoch
            return datetime.fromtimestamp(n, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        # 离谱的大数：Linux/macOS 抛 ValueError/OverflowError，Windows 超过约公元 3000 年抛 OSError(EINVAL)——
        # 不接住的话一个脏字段会让整个 adapter 的解析抛出，而不是「无法识别返回 None」。
        pass
    m = re.search(r"(\d{4})\D{1,3}(\d{1,2})\D{1,3}(\d{1,2})", str(value))
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def pick_publish_date(post: dict) -> Optional[str]:
    """从招聘接口 post 里挑出发布日期（防御式遍历常见字段名）。缺失返回 None。"""
    if not isinstance(post, dict):
        return None
    for field in PUBLISH_TIME_FIELDS:
        value = post.get(field)
        if value:
            iso = coerce_iso_date(value)
            if iso:
                return iso
    return None


def _iter_ld_nodes(data):
    """递归遍历 JSON-LD：dict 自身 + 其 @graph；list 逐项。"""
    if isinstance(data, list):
        for item in data:
            yield from _iter_ld_nodes(item)
    elif isinstance(data, dict):
        yield data
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_ld_nodes(item)


def extract_jobposting_ld(html_text: Optional[str]) -> dict:
    """解析详情页 <script type="application/ld+json"> 中的 schema.org JobPosting（02 spec §3.2）：
    datePosted → posted_at（官方发布时间）、validThrough → deadline。均归一为 ISO date。
    这是「拿官方时间」的主抓手：官方结构化数据 > adapter 直填 > 正文正则。
    容忍 @graph 数组 / 对象数组 / 单对象 / @type 为数组；找不到或解析失败 → {posted_at:None, deadline:None}。"""
    out = {"posted_at": None, "deadline": None}
    if not html_text:
        return out
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_text, re.I | re.S
    ):
        block = m.group(1).strip()
        if not block:
            continue
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        for node in _iter_ld_nodes(data):
            if not isinstance(node, dict):
                continue
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            if "JobPosting" not in types:
                continue
            if not out["posted_at"]:
                out["posted_at"] = coerce_iso_date(node.get("datePosted"))
            if not out["deadline"]:
                out["deadline"] = coerce_iso_date(node.get("validThrough"))
            if out["posted_at"] and out["deadline"]:
                return out
    return out


def resolve_official_times(detail_html=None, adapter_posted=None, adapter_deadline=None, body_text=None):
    """按 02 spec §3.2 优先级合并官方时间：**官方结构化(JSON-LD) > adapter 直填 > 正文正则**。

    - `posted_at`（官方发布时间，高可信）：JSON-LD `datePosted` > adapter 直填；**刻意不取正文正则**——
      §4 规定 posted_at 须来自官方/结构化，拿不到即 NULL，否则会污染「官网近期发布」(NEWLY_DISCOVERED) 判定。
    - `deadline`（截止时间，低风险）：JSON-LD `validThrough` > adapter 直填 > 正文正则。

    `detail_html` 缺失或无 JobPosting → 自然回退 adapter/正文（纯增益，offline 可接）。源能力（哪些源详情页带
    JSON-LD）见 docs/opportunity-timing-radar-specs/source-jsonld-capability.md：仅 Workday 外站 HTML + 个别
    bespoke ATS 带服务端 JSON-LD；国内 SPA 源（moka/zhiye/hotjob/feishu/byd…）全 JS 渲染、抓不到。"""
    ld = extract_jobposting_ld(detail_html) if detail_html else {"posted_at": None, "deadline": None}
    posted = ld["posted_at"] or (coerce_iso_date(adapter_posted) if adapter_posted else None)
    deadline = (ld["deadline"]
                or (coerce_iso_date(adapter_deadline) if adapter_deadline else None)
                or extract_deadline(body_text))
    return {"posted_at": posted, "deadline": deadline}


def normalize_city(value: str) -> str:
    key = (value or "").strip().lower()
    if key in CITY_ALIASES:
        return CITY_ALIASES[key]
    for alias, city in CITY_ALIASES.items():
        if alias.lower() in key:
            return city
    return value


def extract_posted_at(text: Optional[str]) -> Optional[str]:
    """尝试从文本中提取发布日期。返回 ISO 格式字符串或 None。"""
    if not text:
        return None
    # 常见中文日期格式：2024-03-15
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    # 2024/03/15
    m = re.search(r"(\d{4}/\d{2}/\d{2})", text)
    if m:
        return m.group(1).replace("/", "-")
    return None


def validate_job_quality(raw: RawJob, source_url: str) -> tuple[bool, str]:
    """Return whether a parsed row is a real job detail candidate."""
    title = (raw.title or "").strip()
    jd_url = (raw.jd_url or "").strip()

    if not title:
        return False, "missing title"
    if not jd_url:
        return False, "missing jd_url"
    # 台湾：项目口径不抓、不归入任一范围。这条挡在**所有 adapter 汇合之后**的唯一出口上
    # （run.py 对每个 raw job 一律先过 validate_job_quality 再 normalize/写库），不依赖
    # 某个 adapter 记得自己调 location_in_source_regions——2026-09-18 实测两类根因都不是
    # 「adapter 调用了但判错」，而是「压根没走到那道复核」（workday trusted 分支整批跳过
    # per-job 复核；feishu/hotjob/wt/beisen/xiaomi_feishu 这类纯本土源默认全在国内、从不
    # 调用该复核）。详见 geo.is_rejected_location 的注释与实测台账。
    # 地点文本说不清、对方 ATS 自报台湾的，同样拒收（与 normalize 采信自报国家的条件一致）。
    if is_rejected_location(raw.location) or (
        _declared_country(raw) in _REJECTED_COUNTRY_CODES and needs_declared_country(raw.location)
    ):
        return False, "rejected region (taiwan)"

    parsed = urlparse(jd_url)
    source = urlparse(source_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False, "invalid jd_url"

    parsed_key = _url_key(parsed)
    source_key = _url_key(source)
    job_query_names = {
        "id", "code", "jobid", "jobcode", "positionid", "positioncode",
        "postid", "reqid", "requestid", "requisitionid", "vacancyid",
    }
    job_query_keys = {
        key for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        if re.sub(r"[^a-z0-9]", "", key.casefold()) in job_query_names
    }
    if parsed_key == source_key and not job_query_keys:
        return False, "jd_url equals source url"

    compact_title = re.sub(r"\s+", "", title).lower()
    title_lower = title.lower()
    nav_titles = {re.sub(r"\s+", "", t).lower() for t in NAVIGATION_TITLES}
    if compact_title in nav_titles or title_lower in NAVIGATION_TITLES:
        return False, "navigation title"

    path = (parsed.path or "/").rstrip("/") or "/"
    # SPA hash 路由（path 为 '/'，真实岗位路由在 fragment，如携程
    # careers.ctrip.com/#/experienced/job-detail/{id}）：用 fragment 当有效路径参与
    # homepage/navigation 判断，否则 path='/' 会把 hash 详情页误判成首页拦掉。
    # 非 hash 源 path 非空（含 moka /apply/{slug}/{orgId}）→ 此分支不触发、零影响。
    frag = (parsed.fragment or "").strip()
    if path == "/" and frag:
        path = ("/" + frag.lstrip("#/")).rstrip("/") or "/"
    path_lower = path.lower()
    if path == "/":
        return False, "homepage is not a job detail"

    navigation_paths = (
        "/home",
        "/airecommendations",
        "/web/static/",
        "/static/index.html",
        "/recruithelp",
        "/client/home/",
        "/client/library/",
        "/client/techtalent/",
        "/externaljobs/login",
        "/externaljobs/redirect",
        "/siemens/position/index",
        "/siemens/user/",
        "/company/jobs/faq.html",
    )
    if any(marker in path_lower for marker in navigation_paths):
        return False, "navigation url"

    # Workday 站名常叫 "SearchJobs"（如 MSD 默沙东），其岗位**详情**路径形如
    # /searchjobs/job/{loc}/{title}_{reqid}，含真实 /job/ 段。把 /searchjobs 当子串一律拦截
    # 会误杀这些真详情页（已入源质量验证揪出 MSD 20 岗被全误拒）；仅当它是**搜索落地页**
    # （无 /job/ 详情段，含 SPA hash 的 #/searchJobs）才判导航。
    if "/searchjobs" in path_lower and "/job/" not in path_lower:
        return False, "navigation url"

    return True, ""


def _url_key(parsed) -> str:
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "/").rstrip("/") or "/"
    # SPA hash 路由（如 Moka 的 {base}#/job/{id}）per-job 与列表页同 host+path，仅 fragment 不同；
    # 纳入 fragment 才能区分二者（非 SPA 源无 fragment，key 不变，零影响）。
    frag = (parsed.fragment or "").strip()
    if frag:
        return f"{host}{path}#{frag}"
    return f"{host}{path}"


# canonical_jd_url tracking 参数（小写比较）——只收纯统计/广告参数，绝不收 from/source/ref/channel
# 这类可能是 ATS 深链业务参数的词，避免把两个不同岗位误并成一个。
_TRACKING_PARAM_KEYS = {
    "spm", "scm", "bd_vid", "gclid", "fbclid", "msclkid", "yclid",
    "hmsr", "hmpl", "hmcu", "hmkw", "hmci", "_ga", "gio_link_id",
}


def _is_tracking_key(key: str) -> bool:
    k = key.lower()
    return k.startswith("utm_") or k in _TRACKING_PARAM_KEYS


def canonicalize_jd_url(url):
    """把同一岗位的链接变体（tracking 参数 / 尾斜杠）归一到同一把冲突键。

    保守规则：含 '#'(SPA hash 路由 Moka/北森/飞书/携程) → 整串原样返回，绝不动 fragment
    （这些源的岗位身份就在 fragment 里）。否则去 query 里的 tracking 参数 + 规范化尾斜杠。
    ⚠️ 与 lib/canonical-url.js 的 canonicalizeJdUrl 与 supabase/migrations 的 SQL
    canonicalize_jd_url() 逐字一致；改规则三处同改、tests/canonical-url.test.js +
    本仓 test_canonical.py 两套测试同步补。"""
    if url is None:
        return None
    s = str(url).strip()
    if not s:
        return s
    if "#" in s:
        return s
    qpos = s.find("?")
    if qpos >= 0:
        base, query = s[:qpos], s[qpos + 1:]
    else:
        base, query = s, ""
    if query:
        kept = [p for p in query.split("&") if p and not _is_tracking_key(p.split("=", 1)[0])]
        query = "&".join(kept)
    base = re.sub(r"/+$", "", base)
    return base + "?" + query if query else base

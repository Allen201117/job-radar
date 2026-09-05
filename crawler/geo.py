import re
from typing import Optional


CHINA_LOCATION_MARKERS = (
    "china", "中国", "prc", "greater china",
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

_COUNTRY_TOKENS = {
    # ⚠️ TW 必须排在 CN 前面（dict 按插入序遍历，先命中先返回）。
    # 台湾按项目口径**不抓、不归入任一范围**：TW ∉ 任何 source regions 且 TW ∉ _GREATER_CHINA，
    # 于是 location_in_scope 一律返回 False。
    # 此前 TW 压根不在本表里 → "Taipei, Taipei shih, Taiwan, Province of China" 这种写法
    # 因为含 "china" 被判成 CN 放行（2026-07-28 Siemens 改成翻全分页后实测捞进 5 个台北岗才暴露）。
    # 原有 test_taiwan_is_not_in_any_active_scope 只覆盖 "Taiwan"/"Taipei, Taiwan"/"台北, 台湾"
    # 这类**不含 china 字样**的写法（code=None 自然落 False），所以一直是绿的、盖不住这个洞。
    "TW": ["taiwan", "台湾", "臺灣", "taipei", "台北", "臺北", "kaohsiung", "高雄", "hsinchu", "新竹"],
    "HK": ["hong kong", "香港", "hongkong"],
    "MO": ["macau", "macao", "澳门"],
    "CN": [m for m in CHINA_LOCATION_MARKERS if m not in {"hong kong", "香港", "macau", "macao", "澳门"}],
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
    # 抽不出国家码、但地点里**明确钉着一个境外地名**（"Remote Germany" / "India (Remote)" /
    # "Minato-ku, Japan"）时，不许再走源兜底 —— 兜底只该服务「真的什么都没说」的地点（裸「远程」/
    # 空 / Multiple Locations）。少了这一层，给外企源补 CN 会让它名下所有海外远程岗一起变成国内岗：
    # 2026-09-05 实测这批源上有 121 个（艾伯维 102 / 大陆集团 13 / Grab 4 / Expeditors 1 / 育碧 1）。
    # 注意顺序：code 优先。地点能判出国家就以国家为准，这里只管「有地名、但不在 geo 的国家词典里」。
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

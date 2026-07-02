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
}
OVERSEAS_LOCATION_PHRASES = (
    "united states", "united kingdom", "new zealand", "south korea", "saudi arabia",
    "sri lanka", "costa rica", "south africa",
)

_COUNTRY_TOKENS = {
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
    "SG": ["singapore", "新加坡"],
}
_GREATER_CHINA = {"CN", "HK", "MO"}


def _norm(text: Optional[str]) -> str:
    return (text or "").strip().lower()


def _contains_token(text: str, token: str) -> bool:
    if any("一" <= ch <= "鿿" for ch in token) or token.startswith(","):
        return token in text
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", text))


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


def derive_job_scope(location: Optional[str]) -> str:
    """domestic for greater China and unknown/bare remote; overseas otherwise."""
    code = derive_country_code(location)
    if code is None:
        return "domestic"
    return "domestic" if code in _GREATER_CHINA else "overseas"


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

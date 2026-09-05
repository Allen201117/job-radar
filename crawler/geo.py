import re
from typing import Optional


CHINA_LOCATION_MARKERS = (
    "china", "中国", "prc", "greater china",
    # ISO-2 国家码。外企 ATS（SmartRecruiters / Greenhouse 等）的 location.country 直接给
    # 小写国别码，城市名却是**空格分词的拼音**（"He Fei Shi" / "Ning Bo Shi" / "Zhe Jiang Sheng"），
    # 拼音表按 \b 匹配一个都对不上 —— 大陆集团 29 个中国岗里 8 个（28%）就这么被判成 None。
    # 认这个码是**对方自己声明的国别**，不是我们猜的；全库 596 行含独立 "cn" 词的 active 岗
    # 逐行核过，现判定 100% 已经是 CN，加它零误伤（2026-09-05 live 实测）。
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


def derive_job_scope(location: Optional[str]) -> str:
    """domestic for greater China and location-less jobs; bare remote counts as overseas.

    ⚠️ 「没写国家的远程岗」曾一律算 domestic，等于把外企的远程岗当成中国供给：
    2026-09-05 live 实测全库 9,873 个 active 岗地点是光秃秃的「远程」，逐个核过
    **一个中国岗都没有** —— 前 30 家全是 AbbVie / ServiceNow / NVIDIA / Pfizer 这类外企，
    连唯一一家本土公司（腾讯 7 个）的 jd_url 里也明写着 Warsaw / Thailand / Vietnam。
    这批岗占 domestic 总量 327,086 的 3.0%，属「指标诚实」红线里的注水。

    同时这修好了一个**从来没生效过的筛选项**：lib/job-scope.ts 的 Remote 档要求
    `job_scope='overseas' and country_code is null`，而旧规则永远产不出这个组合 ——
    live 实测该组合 0 行，即用户勾「海外 + 远程」必然空手而归。

    地点为空/unknown 仍算 domestic：本土 ATS（moka 等）大量岗位不填地点，
    把它们推去海外会让国内看板凭空少掉一批真岗。
    """
    code = derive_country_code(location)
    if code is None:
        return "overseas" if is_remote_location(location) else "domestic"
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

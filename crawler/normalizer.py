import hashlib
import re
from typing import Optional
from urllib.parse import urlparse

from adapters.base import RawJob


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


def clean_title(title: str) -> str:
    """清洗岗位标题：去首尾空白、去多余空格、去尾部 " - 地点" 后缀。

    仅当连字符两侧都有空白时才截断（英文 "Title - City" 写法），
    避免误伤中文 "部门-角色-方向" 这类紧凑复合标题。
    """
    t = title.strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+[-–—]\s+.*$", "", t).strip()
    return t


def clean_location(location: Optional[str]) -> Optional[str]:
    """清洗地点字段。"""
    if not location:
        return None
    loc = location.strip()
    loc = re.sub(r"\s+", " ", loc)
    if loc.lower() in ("unknown", "multiple locations", "various", ""):
        return None
    return normalize_city(loc)


def clean_summary(summary: Optional[str], max_chars: int = 250) -> Optional[str]:
    """截断摘要到 max_chars 字，在词边界截断。"""
    if not summary:
        return None
    s = summary.strip()
    s = re.sub(r"<[^>]+>", " ", s)  # 去 HTML 标签
    s = re.sub(r"\s+", " ", s)
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
    s = salary_text.strip()
    if s.lower() in ("competitive", "negotiable", "面议", "薪资面议", ""):
        return s
    return s


def make_content_hash(title: str, location: Optional[str], summary: Optional[str]) -> str:
    """生成岗位内容 hash，用于判断是否变化。"""
    raw = f"{title}|{location or ''}|{summary or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def extract_job_type(title: str, summary: Optional[str] = None) -> Optional[str]:
    """从标题和摘要中推断岗位类型。"""
    text = f"{title} {summary or ''}".lower()
    if any(w in text for w in ("暑期实习", "summer intern", "summer internship")):
        return "暑期实习"
    if any(w in text for w in ("日常实习", "daily intern", "off-cycle intern")):
        return "日常实习"
    if any(w in text for w in ("管培生", "管理培训生", "graduate program", "management trainee")):
        return "管培生"
    if any(w in text for w in ("留学生", "海外学生", "overseas student", "returnee")):
        return "留学生专项"
    if any(w in text for w in ("校招", "校园招聘", "应届", "campus", "graduate", "new grad")):
        return "校招"
    if any(w in text for w in ("实习", "intern", "internship")):
        return "实习"
    if any(
        w in text
        for w in ("投研", "研究员", "研究岗", "行业研究", "股票研究", "equity research", "investment research")
    ):
        return "研究岗"
    if any(w in text for w in ("兼职", "part time", "part-time")):
        return "兼职"
    if any(w in text for w in ("社招", "社会招聘", "experienced", "professional")):
        return "社招"
    if "全职" in text:
        return "全职"
    return None


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

    parsed = urlparse(jd_url)
    source = urlparse(source_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False, "invalid jd_url"

    parsed_key = _url_key(parsed)
    source_key = _url_key(source)
    if parsed_key == source_key:
        return False, "jd_url equals source url"

    compact_title = re.sub(r"\s+", "", title).lower()
    title_lower = title.lower()
    nav_titles = {re.sub(r"\s+", "", t).lower() for t in NAVIGATION_TITLES}
    if compact_title in nav_titles or title_lower in NAVIGATION_TITLES:
        return False, "navigation title"

    path = (parsed.path or "/").rstrip("/") or "/"
    path_lower = path.lower()
    if path == "/":
        return False, "homepage is not a job detail"

    navigation_paths = (
        "/home",
        "/searchjobs",
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

    return True, ""


def _url_key(parsed) -> str:
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "/").rstrip("/") or "/"
    return f"{host}{path}"

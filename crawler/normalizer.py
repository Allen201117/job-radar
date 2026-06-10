import hashlib
import html
import re
from datetime import datetime, timezone
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


def clean_summary(summary: Optional[str], max_chars: int = 400) -> Optional[str]:
    """截断摘要到 max_chars 字，在词边界截断。"""
    if not summary:
        return None
    s = summary.strip()
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
    return None


def extract_education(text: Optional[str]) -> Optional[str]:
    """从完整 JD 抽取学历要求（博士/硕士/本科/大专/不限）；抽不到返回 None。"""
    base = _strip_html(text)
    if not base:
        return None
    if re.search(r"博士|ph\.?d|doctora", base, re.I):
        return "博士"
    if re.search(r"硕士|研究生|master", base, re.I):
        return "硕士"
    if re.search(r"本科|学士|bachelor|undergrad", base, re.I):
        return "本科"
    if re.search(r"大专|专科", base):
        return "大专"
    if re.search(r"学历不限|不限学历", base):
        return "不限"
    return None


def extract_deadline(text: Optional[str]) -> Optional[str]:
    """从完整 JD 抽取投递截止（ISO 日期 或 '长期有效'）；抽不到返回 None。"""
    base = _strip_html(text)
    if not base:
        return None
    if re.search(r"长期有效|长期招聘|long[\s-]?term|rolling|until filled", base, re.I):
        return "长期有效"
    m = re.search(
        r"(?:截止|截至|申请截止|投递截止|deadline)[^0-9]{0,8}(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2})",
        base, re.I,
    )
    if m:
        d = re.sub(r"[年月]", "-", m.group(1))
        d = re.sub(r"[./]", "-", d)
        return re.sub(r"-+$", "", d)
    return None


CHINA_LOCATION_MARKERS = (
    "china", "中国", "prc", "greater china",
    # 一/新一线 + 主要工业城市（外企 ATS 地点常只给城市/省名，不带 "China"）
    "beijing", "shanghai", "shenzhen", "guangzhou", "hangzhou", "chengdu",
    "nanjing", "suzhou", "wuhan", "xi'an", "xian", "foshan", "dongguan",
    "tianjin", "chongqing", "wuxi", "ningbo", "qingdao", "dalian", "xiamen",
    "hefei", "changsha", "zhengzhou", "jinan", "kunming", "shijiazhuang",
    "changchun", "harbin", "shenyang", "nanchang", "fuzhou", "nanning",
    "guiyang", "lanzhou", "taiyuan", "wenzhou", "zhuhai", "yantai", "xuzhou",
    "changzhou", "nantong", "weifang", "luoyang", "huizhou",
    # 省 / 自治区（pinyin，独立 token，无歧义）
    "jiangsu", "zhejiang", "guangdong", "sichuan", "shandong", "henan",
    "hebei", "hunan", "hubei", "anhui", "fujian", "jiangxi", "liaoning",
    "shaanxi", "shanxi", "yunnan", "guizhou", "gansu", "hainan", "jilin",
    "heilongjiang", "qinghai", "ningxia", "xinjiang", "guangxi",
    "nei mongol", "inner mongolia",
    "北京", "上海", "深圳", "广州", "杭州", "成都", "南京", "苏州", "武汉", "西安", "佛山",
    "天津", "重庆", "无锡", "宁波", "青岛", "大连", "厦门", "合肥", "长沙", "郑州",
    "hong kong", "香港", "macau", "macao", "澳门",
)


# latin marker 用词边界匹配，避免子串误命中（如 'macao' 命中 'Humacao' 波多黎各、'xian' 命中别词）；
# CJK marker 无词边界概念，用子串。
_CJK_MARKERS = tuple(m for m in CHINA_LOCATION_MARKERS if any("一" <= ch <= "鿿" for ch in m))
_LATIN_MARKERS = tuple(m for m in CHINA_LOCATION_MARKERS if m not in _CJK_MARKERS)
_LATIN_MARKER_RE = re.compile(r"\b(?:" + "|".join(re.escape(m) for m in _LATIN_MARKERS) + r")\b")


def is_china_location(location: Optional[str]) -> bool:
    """判断地点是否属于大中华区（含港澳）。用于把外企 ATS 看板裁到在华岗位。
    latin 关键词用词边界（防 'macao'→'Humacao' 等子串误命中），中文关键词用子串。"""
    if not location:
        return False
    text = location.lower()
    if any(marker in text for marker in _CJK_MARKERS):
        return True
    if _LATIN_MARKER_RE.search(text):
        return True
    # 归一逗号/连字符/多空白为单空格，让 "Hong, Kong"、"Hong-Kong"（路径拆分产物）也能被
    # "hong kong" 词边界正则命中。不影响 'Humacao' 误判（单词无分隔符，词边界仍拦得住）。
    norm = re.sub(r"[\s,\-/]+", " ", text)
    return bool(_LATIN_MARKER_RE.search(norm))


REMOTE_MARKERS = ("remote", "anywhere", "distributed", "work from home", "wfh", "远程", "远端")

# 明确绑定到海外地点的标记（用于把 "Remote - US" 这类 base 海外的 remote 排除）
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


def is_remote_location(location: Optional[str]) -> bool:
    if not location:
        return False
    return any(marker in location.lower() for marker in REMOTE_MARKERS)


def _is_overseas_pinned(location: Optional[str]) -> bool:
    """地点是否明确绑定到某个海外国家/地区（用于排除海外 remote）。"""
    if not location:
        return False
    text = location.lower()
    if any(phrase in text for phrase in OVERSEAS_LOCATION_PHRASES):
        return True
    tokens = [t for t in re.split(r"[^a-z]+", text) if t]
    return any(t in OVERSEAS_LOCATION_TOKENS for t in tokens)


def keep_for_china_radar(location: Optional[str]) -> bool:
    """在华雷达保留口径：大中华区岗位 + 不绑定海外地点的 remote 岗位；排除 base 海外（含海外 remote）。"""
    if is_china_location(location):
        return True
    if is_remote_location(location) and not _is_overseas_pinned(location):
        return True
    return False


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
    except (TypeError, ValueError):
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
    # SPA hash 路由（如 Moka 的 {base}#/job/{id}）per-job 与列表页同 host+path，仅 fragment 不同；
    # 纳入 fragment 才能区分二者（非 SPA 源无 fragment，key 不变，零影响）。
    frag = (parsed.fragment or "").strip()
    if frag:
        return f"{host}{path}#{frag}"
    return f"{host}{path}"

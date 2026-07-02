import hashlib
import html
import json
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from adapters.base import RawJob
from geo import (
    CHINA_LOCATION_MARKERS,
    OVERSEAS_LOCATION_PHRASES,
    OVERSEAS_LOCATION_TOKENS,
    REMOTE_MARKERS,
    _is_overseas_pinned,
    derive_country_code,
    derive_job_scope,
    is_china_location,
    is_remote_location,
    keep_for_china_radar,
    location_in_scope,
)


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


def source_regions(regions=None) -> set[str]:
    if not regions:
        return {"CN"}
    if isinstance(regions, str):
        text = regions.strip()
        regions = text[1:-1].split(",") if text.startswith("{") and text.endswith("}") else text.split(",")
    return {str(r).strip() for r in regions if str(r).strip()} or {"CN"}


def location_in_source_regions(location: Optional[str], regions=None) -> bool:
    return location_in_scope(location, source_regions(regions))


def make_content_hash(title: str, location: Optional[str], summary: Optional[str]) -> str:
    """生成岗位内容 hash，用于判断是否变化。"""
    raw = f"{title}|{location or ''}|{summary or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize(raw: RawJob, *, source_id: str, company: str) -> dict:
    title = clean_title(raw.title)
    location = clean_location(raw.location)
    full_summary = clean_summary(raw.summary)
    salary = clean_salary(raw.salary_text)
    job_type = (
        raw.job_type
        if is_recruitment_type(raw.job_type)
        else (extract_job_type(title, full_summary) or raw.job_type)
    )
    content_hash = make_content_hash(title, location, full_summary)
    experience = raw.experience or extract_experience(raw.summary)
    education = raw.education or extract_education(raw.summary)
    deadline = raw.deadline or extract_deadline(raw.summary)

    return {
        "source_id": source_id,
        "company": raw.company or company,
        "title": title,
        "location": location,
        "country_code": derive_country_code(location),
        "job_scope": derive_job_scope(location),
        "job_type": job_type,
        "summary": full_summary,
        "jd_url": raw.jd_url,
        "apply_url": raw.apply_url,
        "salary_text": salary,
        "posted_at": raw.posted_at,
        "experience": experience,
        "education": education,
        "deadline": deadline,
        "content_hash": content_hash,
        "status": "active",
    }


def extract_job_type(title: str, summary: Optional[str] = None) -> Optional[str]:
    """从标题和摘要中推断岗位类型。"""
    text = f"{title} {summary or ''}".lower()
    if "暑期实习" in text or re.search(r"summer(?:\s+\d{4})?\s+intern(ship)?s?\b", text, re.I):
        return "暑期实习"
    if any(w in text for w in ("日常实习", "daily intern", "off-cycle intern")):
        return "日常实习"
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

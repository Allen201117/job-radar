"""企业 logo 抓取的纯函数（域名解析 / 平台域名排除 / 占位指纹 / data URI / 图片宽度）。

不打网络，便于单测（crawler/test_logo_util.py）。抓取编排在 fetch_company_logos.py。
"""
from __future__ import annotations

import base64
import hashlib
import struct
from typing import Optional
from urllib.parse import urlparse

# 招聘托管 / 共享 ATS 平台域名：取其根域名会拿到平台自己的 logo，不是公司的 → 必须排除。
PLATFORM_DOMAINS = {
    "feishu.cn", "mioffice.cn", "mokahr.com", "zhiye.com",
    "greenhouse.io", "lever.co", "myworkdayjobs.com", "workday.com",
    "ashbyhq.com", "smartrecruiters.com", "teamtailor.com", "pinpointhq.com",
}
# 子串命中即视为平台（北森系多变体域名）。
_PLATFORM_SUBSTRINGS = ("beisen", "italent")

# 命中平台域名的公司 → 用这张手工「公司名→品牌域名」覆盖表兜底。key 用 lower(trim(company))。
COMPANY_DOMAIN_OVERRIDES = {
    "蔚来": "nio.com", "nio": "nio.com",
    "小鹏": "xpeng.com", "小鹏汽车": "xpeng.com", "xpeng": "xpeng.com",
    "理想": "lixiang.com", "理想汽车": "lixiang.com", "li auto": "lixiang.com", "lixiang": "lixiang.com",
    "地平线": "horizon.cc", "horizon": "horizon.cc",
    "小米": "mi.com", "小米集团": "mi.com", "xiaomi": "mi.com",
}

# 中国等多级公共后缀：注册域名要多取一段（com.cn 等）。
_MULTI_LEVEL_SUFFIXES = {
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn",
    "com.hk", "com.tw", "co.jp", "co.uk", "co.kr", "com.sg",
}


def registrable_domain(host: str) -> str:
    """从 host 取「注册域名」（去子域）。talent.baidu.com→baidu.com；nio.jobs.feishu.cn→feishu.cn。"""
    if not host:
        return ""
    host = host.strip().lower()
    host = host.split("@")[-1].split(":")[0].rstrip(".")  # 去认证段 / 端口 / 尾点
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    last2 = ".".join(parts[-2:])
    if last2 in _MULTI_LEVEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_platform_domain(domain: str) -> bool:
    if not domain:
        return False
    domain = domain.strip().lower()
    if domain in PLATFORM_DOMAINS:
        return True
    return any(s in domain for s in _PLATFORM_SUBSTRINGS)


def _host_from_source(source_url: str) -> str:
    """从 source_url 取 host，兼容无 scheme（如 talent.baidu.com/xx）。"""
    if not source_url:
        return ""
    parsed = urlparse(source_url)
    if parsed.netloc:
        return parsed.netloc
    # 无 scheme：path 首段当 host
    return parsed.path.split("/")[0]


def _slug_from_ats(source_url: str) -> Optional[str]:
    """greenhouse / lever 的公司 slug：.../boards/{slug}/... 或 .../postings/{slug}。"""
    try:
        parts = [p for p in urlparse(source_url).path.split("/") if p]
    except Exception:
        return None
    for marker in ("boards", "postings"):
        if marker in parts:
            i = parts.index(marker)
            if i + 1 < len(parts):
                return parts[i + 1]
    return None


def domain_for_company(company: str, source_url: str, override_map: Optional[dict] = None) -> Optional[str]:
    """按优先级推导品牌域名：覆盖表 > 非平台的 source host 注册域名 > greenhouse/lever slug 猜 {slug}.com > None。"""
    override_map = COMPANY_DOMAIN_OVERRIDES if override_map is None else override_map
    key = (company or "").strip().lower()
    if key in override_map:
        return override_map[key]
    domain = registrable_domain(_host_from_source(source_url))
    if domain and not is_platform_domain(domain):
        return domain
    if domain in ("greenhouse.io", "lever.co"):
        slug = _slug_from_ats(source_url)
        if slug:
            return f"{slug.lower()}.com"
    return None


def is_placeholder(img_bytes: bytes, placeholder_md5_set) -> bool:
    """md5 命中占位指纹集（icon.horse 对任何域名都返回占位图，靠此过滤）。空内容也算占位。"""
    if not img_bytes:
        return True
    return hashlib.md5(img_bytes).hexdigest() in placeholder_md5_set


def normalize_mime(content_type: Optional[str], img_bytes: bytes = b"") -> str:
    """把 content-type 归一为 data URI 用的 mime；不可信时按内容嗅探。"""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in ("image/vnd.microsoft.icon", "image/icon"):
        return "image/x-icon"
    if ct in ("image/png", "image/svg+xml", "image/jpeg", "image/gif", "image/webp", "image/x-icon"):
        return ct
    # content-type 缺失/异常 → 内容嗅探
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if img_bytes[:4] == b"\x00\x00\x01\x00":
        return "image/x-icon"
    head = img_bytes[:256].lower()
    if head[:5] == b"<?xml" or b"<svg" in head:
        return "image/svg+xml"
    if img_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return "image/png"


def build_data_uri(content_type: Optional[str], img_bytes: bytes) -> str:
    mime = normalize_mime(content_type, img_bytes)
    b64 = base64.b64encode(img_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def image_width(img_bytes: bytes) -> Optional[int]:
    """best-effort 取像素宽（PNG 读 IHDR / ICO 读第一个目录项），拿不到返回 None。不依赖 Pillow。"""
    if not img_bytes:
        return None
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n" and len(img_bytes) >= 24:
        try:
            return struct.unpack(">I", img_bytes[16:20])[0]
        except Exception:
            return None
    if img_bytes[:4] == b"\x00\x00\x01\x00" and len(img_bytes) >= 7:
        w = img_bytes[6]  # ICO 目录项 width，0 表示 256
        return 256 if w == 0 else w
    return None

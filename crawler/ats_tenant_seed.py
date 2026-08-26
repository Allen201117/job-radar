"""已验证 ATS 租户快照的候选种子读取与去重，不执行网络或数据库写入。"""
import csv
import io
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import must_apply


_DATA_DIR = Path(__file__).resolve().parent / "data" / "ats_tenants"
_SNAPSHOTS = (
    ("moka.csv", "moka"),
    ("beisen.csv", "beisen"),
    ("beisen_legacy.csv", "beisen"),
)


def parse_tenant_rows(csv_text: str, platform: str) -> list[dict]:
    """解析一份上游 CSV → 规范租户行；跳过 name、slug、url 任一缺失的行。"""
    rows = []
    try:
        reader = csv.DictReader(io.StringIO(str(csv_text or "")))
    except Exception:
        return rows
    for row in reader:
        name = str((row or {}).get("name") or "").strip()
        slug = str((row or {}).get("slug") or "").strip()
        url = str((row or {}).get("url") or "").strip()
        if not name or not slug or not url:
            continue
        rows.append({
            "name": name,
            "slug": slug,
            "url": url,
            "platform": str(platform or "").strip().lower(),
        })
    return rows


def tenant_key(platform: str, url: str) -> Optional[str]:
    """从 ATS 租户 URL 提取跨入口稳定的去重键。"""
    parsed = urlparse(str(url or "").strip())
    host = str(parsed.hostname or "").lower().rstrip(".")
    if not host:
        return None
    platform = str(platform or "").strip().lower()
    if platform == "moka":
        if host == "app.mokahr.com" or host.endswith(".mokahr.com"):
            # 租户身份在 path 的 /social-recruitment/<tenant>/<id> 段，不在 host 上。
            # ⚠️ hire-r1.mokahr.com 是**多租户共享 host**（Tesla APAC / HEYTEA / Klook /
            # Bitget 等 13 家都挂在它下面），拿子域当键会把这 13 家折叠成同一个
            # moka:hire-r1，去重时静默丢掉 12 家。所以必须优先按 path 取。
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2:
                return "moka:%s" % parts[1].casefold()
            if host.endswith(".mokahr.com") and host != "app.mokahr.com":
                return "moka:%s" % host[:-(len(".mokahr.com"))].casefold()
    elif platform == "beisen" and host.endswith(".zhiye.com"):
        slug = host[:-(len(".zhiye.com"))]
        if slug and "." not in slug:
            return "beisen:%s" % slug.casefold()
    return None


def filter_new_tenants(tenants: list[dict], existing_source_urls: list[str]) -> list[dict]:
    """剔除已有 source 的同租户入口，并合并快照内重复租户。"""
    existing_keys = {
        key
        for url in existing_source_urls or []
        for platform in ("moka", "beisen")
        for key in [tenant_key(platform, url)]
        if key
    }
    rows = []
    seen = set()
    for tenant in tenants or []:
        key = tenant_key(tenant.get("platform"), tenant.get("url"))
        if key and (key in existing_keys or key in seen):
            continue
        if key:
            seen.add(key)
        rows.append(dict(tenant))
    return rows


def must_apply_domain_stems() -> dict:
    """必投公司域名主体 → 中文公司名，用来把英文租户名对上中文必投清单。

    上游快照的 name 是英文（Foxconn / Procter & Gamble China），必投 pattern 是中文
    （%富士康% / %宝洁%），**直接按名字匹配永远匹配不上**——「必投优先」会变成
    一个看起来在工作、实际全程没生效的假象。这里用已核验域名表搭桥：
    富士康 → foxconn.com → foxconn，正好对上租户 slug。
    """
    try:
        import logo_util

        overrides = logo_util.COMPANY_DOMAIN_OVERRIDES or {}
    except Exception:
        return {}
    stems = {}
    # ⚠️ 只取**必投清单里**公司的域名，不能拿 logo_util 全表（545 条覆盖所有库内公司）——
    # 否则 3SBio、Asymchem 这些非必投公司也会被判成「必投命中」而插队。
    for companies in must_apply.by_industry().values():
        for entry in companies or []:
            name = str((entry or {}).get("name") or "").strip()
            domain = overrides.get(name.lower())
            stem = str(domain or "").strip().lower().split(".")[0]
            # 太短的主体（如 pg、gm）拿去撞 slug 容易张冠李戴，交给名字匹配那一路兜。
            if len(stem) >= 4 and stem not in stems:
                stems[stem] = name
    return stems


def _hits_must_apply(tenant: dict, must_apply_patterns: list[str], domain_stems: dict) -> bool:
    if must_apply.match_company_against_patterns(
        tenant.get("name"), must_apply_patterns
    ):
        return True
    key = tenant_key(tenant.get("platform"), tenant.get("url"))
    if not key:
        return False
    # tenant_key 形如 "moka:foxconn" / "beisen:vivo"，取冒号后的 slug 去撞域名主体。
    return key.split(":", 1)[-1].lower() in (domain_stems or {})


def rank_tenants(tenants: list[dict], must_apply_patterns: list[str]) -> list[dict]:
    """必投公司优先，其余按平台与公司名稳定排序。"""
    domain_stems = must_apply_domain_stems()
    return sorted(
        (dict(tenant) for tenant in tenants or []),
        key=lambda tenant: (
            0 if _hits_must_apply(tenant, must_apply_patterns, domain_stems) else 1,
            str(tenant.get("platform") or "").casefold(),
            str(tenant.get("name") or "").casefold(),
        ),
    )


def load_upstream_tenants() -> list[dict]:
    """读取本地快照；单个文件缺失时静默跳过。"""
    rows = []
    for filename, platform in _SNAPSHOTS:
        try:
            csv_text = (_DATA_DIR / filename).read_text(encoding="utf-8-sig")
        except OSError:
            continue
        rows.extend(parse_tenant_rows(csv_text, platform))
    return rows

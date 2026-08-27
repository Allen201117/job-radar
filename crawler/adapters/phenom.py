"""
Phenom People 通用适配器。同一平台两条取数路径，按响应特征自动选路（不按域名写白名单）：

A. 公开 REST `/api/jobs`（默认，AMD / PepsiCo 等租户开着）
   source_url = https://{host}/api/jobs   （host 形如 careers.amd.com）
   jd_url = https://{host}/jobs/{slug}

B. Phenom widgets（`POST /widgets`，ddoKey=refineSearch）
   部分租户压根没开 /api/jobs（实测 careers.dhl.com 恒定 HTTP 500 "A server error occurred"，
   而同刻 careers.amd.com/api/jobs 200 正常 → 是租户没开，不是我们参数写错）。
   widgets 是 Phenom 站点自身的取数接口，无需 CSRF / cookie / 登录。
   jd_url = https://{host}{site}/job/{jobSeqNo}/{slug}（slug 是装饰，任意值都能打开）

大量外企巨头的「自建门户」其实是 Phenom（AMD / L'Oréal / DHL / 多家 Fortune 500），
workday/oracle/greenhouse/eightfold 都抓不到。一套适配覆盖任意 Phenom 租户——新增公司只加一行 sources。
服务「在华外企」：服务端按 location / country facet 收窄到大中华区，parse 再用 regions 兜底。
注意 data.apply_url / applyUrl 多指向 icims、avature 等登录页，违反 jd_url 质量门，不可用。
"""
import json
import logging
from typing import Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlparse

import httpx

import normalizer
from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap


logger = logging.getLogger(__name__)


def _job_summary(d: dict) -> Optional[str]:
    """从 Phenom /api/jobs 列表项的 data 直接组装 JD 正文（已 live 验证含完整 description ~4k 字
    + responsibilities + qualifications）。无需逐岗 detail（Phenom 逐岗页是 SPA 壳、httpx 拿不到正文），
    列表自带正文即够 ≥60 字门。HTML 由 run.py 的 normalizer.clean_summary 统一清洗+截断。"""
    parts = [d.get("description"), d.get("responsibilities"), d.get("qualifications")]
    text = "\n".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
    return text or None


def _widgets_summary(row: dict) -> Optional[str]:
    """widgets 行的 JD 正文：**先**放 Phenom 自带的岗位综述（detail 的 ai_summary /
    列表行的 ml_job_parser.descriptionTeaser，都是直述岗位职责的干净短文），**再**接完整 description。

    顺序是刻意的：clean_summary 只留前 400 字，而不少租户的 description 开头是集团样板话
    （DHL 实测前 ~190 字全是 equal-opportunity 声明），直接用会让卡片正文全是废话；
    完整正文仍拼在后面，留给 normalizer 从中抽经验/学历/截止（那一步读未截断的原文）。

    ⚠️ detail 里的 `descriptionTeaser` 是被截断的 HTML 碎片（实测清洗后只剩 32 字、过不了 ≥60 字门），
    只有列表行的 descriptionTeaser 是完整句子——所以两者分开取，不合并成一个字段名。
    """
    detail = row.get("_detail") if isinstance(row.get("_detail"), dict) else {}
    parser = detail.get("ml_job_parser") or row.get("ml_job_parser") or {}
    if not isinstance(parser, dict):
        parser = {}
    parts = [
        detail.get("ai_summary"),
        parser.get("descriptionTeaser"),
        detail.get("description") or detail.get("ml_Description"),
        row.get("descriptionTeaser") if not detail else None,  # 无 detail 时的兜底（列表行是完整句子）
    ]
    seen = set()
    kept = []
    for p in parts:
        if not isinstance(p, str):
            continue
        p = p.strip()
        if not p or p in seen:
            continue
        seen.add(p)
        kept.append(p)
    return "\n".join(kept) or None


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# Phenom 站点常由 Akamai/CDN 前置，用常见浏览器 UA 更稳。
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_WIDGETS_PATH = "/widgets"
# Phenom 站点路径约定 /{country}/{lang}，多国站点的英文全球版即 /global/en（→ lang=en_global）。
_DEFAULT_SITE_PATH = "/global/en"
_WIDGETS_FACET_FIELDS = ["country", "state", "city", "category", "type"]


class _ApiJobsUnavailable(Exception):
    """`/api/jobs` 在该租户上不可用（未开通 / 5xx / 返回的不是岗位 JSON）。带上原始异常供回退失败时上抛。"""

    def __init__(self, original: BaseException):
        super().__init__(str(original))
        self.original = original


class PhenomAdapter(BaseAdapter):
    name = "phenom"
    max_pages = 20                              # 100/页 → 单地点最多 2000 岗
    china_locations = ("China", "Hong Kong")    # 服务端按地点收窄到大中华区
    overseas_locations = {
        "US": ("United States",),
        "SG": ("Singapore",),
        "Remote": ("Remote",),
    }

    # widgets 的 country facet 认「标准化国家全名」，字面量必须一字不差：
    # 实测 "China" / "Hong Kong" / "United States" 都返 0，正确写法见下。
    # 同一 region 的多个写法一次性全传（facet 是 OR，未知字面量返 0 不报错，
    # 实测混传已验证 = 只命中真值），这样跨租户字面量差异不用逐个探、也不用按域名分支。
    country_facets = {
        "CN": ("China, People's Republic of", "China", "China Mainland"),
        "HK": ("Hong Kong, China", "Hong Kong", "Hong Kong SAR"),
        "MO": ("Macao, China", "Macau, China", "Macao", "Macau"),
        "US": ("United States of America", "United States", "USA"),
        "SG": ("Singapore",),
    }
    widgets_page_size = 100
    # DHL 中国区 121 岗，逐岗 detail 约 0.4s → 全量富化约 1 分钟，cap 200 足以覆盖整源。
    # 快档 daily 通过 CRAWL_DETAIL_CAP=0 跳过（此时用列表自带的 ml_job_parser 摘要，仍过 ≥60 字门）。
    _DETAIL_CAP = 200

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        p = urlparse(source_url)
        host = f"{p.scheme}://{p.netloc}"
        if p.path.rstrip("/").endswith(_WIDGETS_PATH):
            return self._fetch_widgets(source_url, host)
        try:
            return self._fetch_api_jobs(source_url, host)
        except _ApiJobsUnavailable as exc:
            # 该租户没开 /api/jobs → 回退 widgets。仅在 /api/jobs **一条都没抓到** 时触发，
            # 且 widgets 也抓不到岗时原样上抛原始错误——不让「换条路」把真故障吞成静默空结果。
            logger.info("phenom: %s 的 /api/jobs 不可用（%s），回退 widgets", host, exc)
            payload = self._fetch_widgets(host + _WIDGETS_PATH, host)
            if not json.loads(payload).get("jobs"):
                self.reported_total = None
                self.fetch_complete = False
                raise exc.original
            return payload

    # ---------- A. 公开 REST /api/jobs ----------

    def _fetch_api_jobs(self, source_url: str, host: str) -> str:
        api = source_url.split("?")[0]
        headers = {"User-Agent": _BROWSER_UA, "Accept": "application/json"}
        collected: List[dict] = []
        seen = set()
        locations = self._locations_for_regions()
        location_totals: List[int] = []
        for loc in locations:
            loc_total: Optional[int] = None
            for page in range(self.max_pages):
                params = {"location": loc, "limit": 100, "offset": page * 100}
                try:
                    r = httpx.get(api, params=params, headers=headers, timeout=self.timeout)
                    r.raise_for_status()
                    body = r.json()
                    jobs = body.get("jobs", []) or []
                except Exception as exc:
                    # 首个请求就失败（还一条没抓到）→ 判定该租户没开这条 API，交给 fetch() 回退 widgets。
                    # 抓到过数据之后的失败沿用旧行为：原样上抛，由 run.py 记 failed（别把半截结果当成功）。
                    if not collected and not location_totals and page == 0 and loc == locations[0]:
                        raise _ApiJobsUnavailable(exc) from exc
                    raise
                if loc_total is None:
                    loc_total = _int_or_none(body.get("totalCount"))
                    if loc_total is None:
                        loc_total = _int_or_none(body.get("count"))
                if not jobs:
                    break
                for j in jobs:
                    data = j.get("data", {}) if isinstance(j, dict) else {}
                    slug = str(data.get("slug") or data.get("req_id") or "").strip()
                    if slug and slug not in seen:
                        seen.add(slug)
                        collected.append(data)
                total = loc_total or 0
                if len(jobs) < 100 or (page + 1) * 100 >= total:
                    break
            if loc_total is not None:
                location_totals.append(loc_total)
        if len(location_totals) == len(locations):
            self.reported_total = sum(location_totals)
        self.fetch_complete = (
            self.reported_total is not None and len(collected) >= self.reported_total
        )
        return json.dumps({"_host": host, "jobs": collected}, ensure_ascii=False)

    # ---------- B. Phenom widgets ----------

    @staticmethod
    def _site_path(widgets_url: str) -> str:
        """站点路径（决定 Referer / jd_url 前缀 / lang / country）。默认 /global/en，
        可用 source_url 的 ?site=/us/en 覆盖（不同租户站点路径不同，别写死）。"""
        query = dict(parse_qsl(urlparse(widgets_url).query, keep_blank_values=True))
        site = (query.get("site") or "").strip() or _DEFAULT_SITE_PATH
        return "/" + site.strip("/")

    @staticmethod
    def _locale_from_site(site_path: str) -> Tuple[str, str]:
        """Phenom 约定 /{country}/{lang} → (country, "{lang}_{country}")。/global/en → ("global", "en_global")。"""
        parts = [p for p in site_path.split("/") if p]
        country = parts[0] if parts else "global"
        lang = parts[1] if len(parts) > 1 else "en"
        return country, f"{lang}_{country}"

    def _country_facets_for_regions(self) -> List[str]:
        """country facet 由 sources.regions **逐项** 派生，不写死：CN→中国大陆，HK/MO/US/SG 各自 opt-in。

        ⚠️ 与 /api/jobs 分支不同口径，是刻意的：那边 regions=={CN} 会连带抓 Hong Kong
        （china_locations 写死了两个地点），这边严格按 regions 逐项来。想连港澳一起抓，
        把源的 regions 配成 {CN,HK}（normalizer.location_in_scope 对含 CN 的源本就放行大中华区，
        抓回来不会被后置过滤掉）。
        Remote 不是国家、widgets 没有对应 facet → 跳过（诚实盲区）；一个都派生不出时回退 CN。"""
        regions = normalizer.source_regions(getattr(self, "regions", None))
        out: List[str] = []
        for region in sorted(regions):
            for label in self.country_facets.get(region, ()):
                if label not in out:
                    out.append(label)
        return out or list(self.country_facets["CN"])

    def _widgets_body(self, ddo_key: str, page_name: str, site_path: str, **extra) -> dict:
        country, lang = self._locale_from_site(site_path)
        body = {
            "lang": lang,
            "deviceType": "desktop",
            "country": country,
            "pageName": page_name,
            "ddoKey": ddo_key,
            "sortBy": "",
            "subsearch": "",
            "keywords": "",
            "global": True,
        }
        body.update(extra)
        return body

    def _fetch_widgets(self, widgets_url: str, host: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        site = self._site_path(widgets_url)
        endpoint = host + _WIDGETS_PATH
        countries = self._country_facets_for_regions()
        size = self.widgets_page_size
        headers = {
            "User-Agent": _BROWSER_UA,
            "Content-Type": "application/json",
            "Accept": "application/json",
            # widgets 只认「从自己站内发起」的请求语义；且 careers 根路径会按来访 IP 地理跳转
            # （探测时被跳到 /apac/tw），所以 Referer 必须显式带站点路径，别用裸域名。
            "Referer": f"{host}{site}/search-results",
        }
        with httpx.Client(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            def fetch_page(page: int) -> PageResult:
                body = self._widgets_body(
                    "refineSearch", "search-results", site,
                    **{
                        "from": page * size,
                        "size": size,
                        "jobs": True,
                        "counts": True,
                        "all_fields": list(_WIDGETS_FACET_FIELDS),
                        "selected_fields": {"country": list(countries)},
                        "locationData": {},
                    },
                )
                r = client.post(endpoint, json=body)
                r.raise_for_status()
                refine = (r.json() or {}).get("refineSearch") or {}
                data = refine.get("data") or {}
                items = [j for j in (data.get("jobs") or []) if isinstance(j, dict)]
                # ⚠️ 总数在 refineSearch.totalHits，不在 data 里（data.jobs 只有本页那几条）。
                return PageResult(items=items, total=_int_or_none(refine.get("totalHits")))

            rows, total, complete = paginate_all(
                fetch_page, page_size=size, first_page=0, max_pages=self.max_pages,
                delay_seconds=0.2, logger=logger, label=f"phenom-widgets:{urlparse(host).netloc}",
            )
            self.reported_total = total
            self.fetch_complete = complete

            cap = resolve_detail_cap(self._DETAIL_CAP)
            for row in (rows[:cap] if cap else []):
                detail = self._job_detail(client, endpoint, site, row)
                if detail:
                    row["_detail"] = detail
        return json.dumps({"_host": host, "_site": site, "_mode": "widgets", "jobs": rows},
                          ensure_ascii=False)

    def _job_detail(self, client: httpx.Client, endpoint: str, site: str, row: dict) -> Optional[dict]:
        """逐岗 JD 正文（ddoKey=jobDetail，纯 httpx 零浏览器）。
        顺带就是天然的撤岗信号：岗位不存在时 hits/totalHits=0、data 为空（对应逐岗页 HTTP 410）。"""
        seq = str(row.get("jobSeqNo") or "").strip()
        if not seq:
            return None
        body = self._widgets_body(
            "jobDetail", "job-details", site,
            **{"jobSeqNo": seq, "jobId": str(row.get("jobId") or "").strip(),
               "username": "", "isSDGEnabled": False},
        )
        try:
            r = client.post(endpoint, json=body)
            if r.status_code >= 400:
                return None
            detail = (r.json() or {}).get("jobDetail") or {}
            if not _int_or_none(detail.get("hits")):
                return None
            job = (detail.get("data") or {}).get("job")
            return job if isinstance(job, dict) else None
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            return None  # 单岗富化失败不炸整源：正文回落列表行自带摘要

    # ---------- 解析（两条路径共用出口） ----------

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        if data.get("_mode") == "widgets":
            return self._parse_widgets(data)
        return self._parse_api_jobs(data)

    def _parse_api_jobs(self, data: dict) -> List[RawJob]:
        host = data.get("_host", "")
        out: List[RawJob] = []
        seen_urls = set()
        for d in data.get("jobs", []):
            if not isinstance(d, dict):
                continue
            title = (d.get("title") or "").strip()
            slug = str(d.get("slug") or d.get("req_id") or "").strip()
            if not title or not slug:
                continue
            loc = ", ".join(x for x in (d.get("city"), d.get("state"), d.get("country")) if x) \
                or (d.get("location_name") or None)
            # 服务端已按地点收窄，这里按 regions 兜底（排除 location 模糊召回的串入岗）
            if not normalizer.location_in_source_regions(loc, getattr(self, "regions", None)):
                continue
            jd_url = f"{host}/jobs/{slug}"
            if jd_url in seen_urls:
                continue
            seen_urls.add(jd_url)
            out.append(RawJob(
                company="",  # 由 sources.company 兜底
                title=title,
                location=loc,
                job_type=None,  # 由 normalizer 从标题抽取社招/校招/实习
                summary=_job_summary(d),  # 列表自带完整 JD 正文 → 直接入库，治 0% 覆盖薄卡
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=(d.get("posted_date") or None),
            ))
        return out

    def _parse_widgets(self, data: dict) -> List[RawJob]:
        host = data.get("_host", "")
        site = data.get("_site") or _DEFAULT_SITE_PATH
        out: List[RawJob] = []
        seen_urls = set()
        for row in data.get("jobs", []):
            if not isinstance(row, dict):
                continue
            title = (row.get("title") or "").strip()
            seq = str(row.get("jobSeqNo") or "").strip()
            if not title or not seq:
                continue
            loc = ", ".join(x for x in (row.get("city"), row.get("state"), row.get("country")) if x) \
                or (row.get("location") or row.get("cityStateCountry") or None)
            if not normalizer.location_in_source_regions(loc, getattr(self, "regions", None)):
                continue
            # slug 只是装饰位（实测填 x 也能正常打开），用 jobSeqNo 保证唯一且稳定。
            jd_url = f"{host}{site}/job/{seq}/{seq}"
            if jd_url in seen_urls:
                continue
            seen_urls.add(jd_url)
            out.append(RawJob(
                company="",  # 由 sources.company 兜底
                title=title,
                location=loc,
                job_type=None,
                summary=_widgets_summary(row),
                jd_url=jd_url,
                apply_url=jd_url,  # applyUrl 指向 avature/icims 登录页，不合质量门
                posted_at=normalizer.coerce_iso_date(row.get("postedDate")),
            ))
        return out

    def _locations_for_regions(self) -> Iterable[str]:
        regions = normalizer.source_regions(getattr(self, "regions", None))
        if regions == {"CN"}:
            return self.china_locations
        out = []
        if "CN" in regions:
            out.extend(self.china_locations)
        for region in sorted(regions):
            out.extend(self.overseas_locations.get(region, ()))
        return tuple(dict.fromkeys(out)) or self.china_locations

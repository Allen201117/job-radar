"""
通用 Workday 适配器（公开 CXS API，无需鉴权）。

source_url = https://{host}/wday/cxs/{tenant}/{site}/jobs   （host 形如 {tenant}.wd{N}.myworkdayjobs.com）
大量在华跨国企业（外企100强主力：NVIDIA / 制造 / 金融 / 消费…）用 Workday，greenhouse/lever 抓不到。
一套适配覆盖任意 Workday 租户 —— 新增公司只需加一行 sources（source_url 填 CXS jobs 端点）。

服务「在华外企」：用 Workday 的 location facet **服务端**过滤到大中华区（China/Hong Kong/Macau），
只抓在华岗位，避免全球岗位灌入（list 接口 locationsText 常是「N Locations」不可靠，故用 facet）。
public jd_url = {host}/en-US/{site}{externalPath}
  （Workday 公开站 SPA 路由 = origin + /{locale}/{site} + externalPath；externalPath 形如
   /job/{location}/{title}_{JR-id}，必须保留**全路径**、只补 en-US locale 前缀。曾误改为
   /details/{slug}（丢掉 /job/{location}/ 段）→ 公开站清一色 404「岗位不存在」，已修回，存量坏链由迁移 148 清。）
CXS detail enrichment 仍用 {cxs_base}{externalPath}（enrich.py:_detail_workday 靠 jd_url 里的 /job/ 段反推端点）。
"""
import json
import logging
import re
import time
from typing import List, Optional
from urllib.parse import urlparse

import httpx

import normalizer
from geo import derive_country_code
from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap

logger = logging.getLogger(__name__)

# 大中华区 facet 关键词（China / Mainland China / Greater China / Hong Kong / Macau…）
_GREATER_CHINA = ("china", "中国", "hong kong", "香港", "macau", "macao", "澳门")
# 台湾不属本雷达「在华」口径，排除
_TAIWAN = ("taiwan", "台湾", "台灣", "chinese taipei")
_REGION_FACET_KEYWORDS = {
    "US": ("united states", "usa", "u.s.", "u.s.a."),
    "SG": ("singapore", "新加坡"),
    "Remote": ("remote", "anywhere", "distributed"),
}
# 国家级 US 聚合项（locationCountry / Location_Country / locationHierarchy1 … 下的「United States of America」）。
# 有它 = facet 已能一次拿全美国岗（2026-09-23 实测 68 源抓到/自报 ≈1.00），城市级宽松通道对它们只加请求不加岗。
_US_COUNTRY_DESCRIPTORS = frozenset({"united states of america", "united states", "usa", "u.s.", "u.s.a."})
_COUNTRY_LEVEL_PARAM = re.compile(r"country|hierarchy", re.I)
# 宽松通道只看地点类 param（租户命名五花八门：locations / primaryLocation / Location / …RegionStateProvince）。
_LOCATION_PARAM = re.compile(r"loc|country|state|province|region|hierarchy", re.I)
# appliedFacets[param] 单次提交的 id 数上限：实测 ThermoFisher 250 个 OK、300 个 400；
# Mondelez 300 个 OK、904 个（未分块）500——阈值随租户浮动，150 留足安全边界（<250 的已知下限的 60%）。
_FACET_ID_CHUNK = 150

_SEARCH_TEXT_BY_REGION = {
    "CN": ("China", "Hong Kong", "Macau"),
    "US": ("United States", "USA"),
    "SG": ("Singapore",),
    "Remote": ("Remote",),
}


def _post_list(source_url, body, headers, timeout):
    """Workday 列表请求遇 429 时仅按 Retry-After 退避重试一次。"""
    response = httpx.post(source_url, json=body, headers=headers, timeout=timeout)
    if response.status_code == 429:
        try:
            retry_after = float(response.headers.get("Retry-After", 5))
        except (TypeError, ValueError):
            retry_after = 5
        time.sleep(min(30, max(0, retry_after)))
        response = httpx.post(source_url, json=body, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response


def _is_china_facet(desc: str) -> bool:
    """是否大中华区 facet 项：含 China/HK/Macau 关键词、排除台湾。
    允许城市级（'China, Beijing'）—— 不同租户把可选叶子放在国家级或城市级 param，按 param 分组后逐组试探。"""
    d = str(desc or "").strip().lower()
    if not d or any(t in d for t in _TAIWAN):
        return False
    return any(k in d for k in _GREATER_CHINA)


def _contains_facet_keyword(desc: str, keyword: str) -> bool:
    if any("一" <= ch <= "鿿" for ch in keyword):
        return keyword in desc
    parts = [re.escape(p) for p in re.split(r"[^a-z0-9]+", keyword.lower()) if p]
    if not parts:
        return False
    pattern = r"[\s,\-/]+".join(parts)
    return bool(re.search(r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])", desc))


def _is_facet_in_regions(desc: str, regions) -> bool:
    d = str(desc or "").strip().lower()
    if not d or any(t in d for t in _TAIWAN):
        return False
    regions = normalizer.source_regions(regions)
    if "CN" in regions and _is_china_facet(d):
        return True
    for region in regions:
        if any(_contains_facet_keyword(d, kw) for kw in _REGION_FACET_KEYWORDS.get(region, ())):
            return True
    return False


def _search_texts_for_regions(regions):
    out = []
    for region in sorted(normalizer.source_regions(regions)):
        out.extend(_SEARCH_TEXT_BY_REGION.get(region, ()))
    return tuple(dict.fromkeys(out)) or _SEARCH_TEXT_BY_REGION["CN"]


class WorkdayAdapter(BaseAdapter):
    name = "workday"
    max_pages = 100  # 每页 20 → 每个 facet/keyword 安全上限 2000，靠短页自然收尾

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检

    def _parse_endpoint(self, source_url: str):
        p = urlparse(source_url)
        self._host = f"{p.scheme}://{p.netloc}"
        # CXS detail 端点 = {host}/wday/cxs/{tenant}/{site}{externalPath}（= source_url 去掉尾部 /jobs）。
        self._cxs_base = re.sub(r"/jobs/?$", "", source_url)
        parts = [x for x in (p.path or "").split("/") if x]
        # 期望 ['wday','cxs',{tenant},{site},'jobs'] → site 是 cxs 后第 2 段
        try:
            i = parts.index("cxs")
            self._site = parts[i + 2]
        except (ValueError, IndexError):
            self._site = parts[-2] if len(parts) >= 2 else ""

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        self._parse_endpoint(source_url)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        # 1) 取 facets，按 param 分组收集大中华区候选 id
        r = _post_list(
            source_url, {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
            headers, self.timeout,
        )
        regions = normalizer.source_regions(getattr(self, "regions", None))
        facets = r.json().get("facets", [])
        candidates = self._facet_candidates_for_regions(facets, regions)

        # 2) facet 路径：把**每个**大中华区 facet 组各自分页、并集去重。
        # 不靠 Workday 的 `total` 字段选「最佳单组」—— 实测该字段极不可靠（NVIDIA 报 total=180 实际可翻 600+），
        # 靠它选组/比较会误判。改为「所有 china facet 组并集」：每组都是合法在华过滤，OR 起来即全部在华岗，
        # 这些是**可信在华**岗（parse 不再过滤）。同 param 多 id 一次 OR 提交；不同 param 分别提交后并集。
        trusted: List[dict] = []
        seen = set()
        any_capped = self._collect_facet_posts(source_url, headers, candidates, seen, trusted)

        # 2b) 城市级 US 叶子宽松通道：不少租户的 location facet 只有城市级叶子，且不写国名全称——
        # 'Austin, TX, US'（Postman）/ 'US, Oregon, Hillsboro'（Intel）/ 'Beaverton, Oregon'（Nike）/
        # 'San Jose, CA'（Micron）。上面的字面关键词一个都认不出，而第 3 步的文本兜底只在 facet 取到 <25 岗
        # 时才跑——这些源靠在华/新加坡 facet 早就过了 25，美国岗整片漏掉（2026-09-23 实测 Micron/阿斯利康
        # 各只抓到 1 个、Nike 0 个）。这里交给 geo 的美国地名词典（州全称/州缩写，有双向回归测试）认叶子。
        # ⚠️ 这些岗**不进 trusted**：叶子是 geo 猜的不是租户声明的，逐岗再过 regions（同文本兜底），
        #    宁可漏判不可错放。⚠️ 已有国家级 US facet 的源不走这条（见 _has_us_country_facet）。
        text_posts: List[dict] = []
        loose = self._loose_us_facet_candidates(facets, regions)
        if loose:
            try:
                any_capped = self._collect_facet_posts(source_url, headers, loose, seen, text_posts) or any_capped
            except Exception as e:
                # 这条是补充召回：它一次断连就 raise，会把前面已抓到的在华岗连同整源一起扔掉（同顺丰那块碑）。
                # 2026-09-23 对拍时 Regeneron 真撞过一次 Server disconnected。保住已抓的，如实记没抓全。
                logger.warning("workday %s: city-level US facet pass failed, kept %d posts: %r",
                               self._host, len(text_posts), e)
                any_capped = True

        # 3) searchText 文本补充：部分租户的在华地点埋在**嵌套/截断**的 location facet 里，facet 只露出
        # 部分叶子（如 GE HealthCare 的 locationMainGroup 只有 Hong Kong、漏掉上海 22 岗）。facet 取到的太少
        # （<25，或压根没 facet）就用 Workday searchText 按 'China'/'Hong Kong'/'Macau' 文本召回把漏的捞回；
        # 这些是**待过滤**岗（searchText 会带入母国/描述含 China 的非华岗），由 parse 按 is_china_location 严格过滤。
        # facet 已足够多（NVIDIA/BMS 数百岗）则跳过补充：补充只增不减、out ⊇ trusted，绝不回退召回。
        # 门槛只数 trusted、不数 2b 的宽松岗——保证加了 2b 之后，原来会跑兜底的源照旧跑。
        if len(trusted) < 25:
            for q in _search_texts_for_regions(regions):
                def fetch_page(page: int) -> PageResult:
                    body = {"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": q}
                    rr = _post_list(source_url, body, headers, self.timeout)
                    posts = rr.json().get("jobPostings", []) or []
                    return PageResult(items=posts, total=None)

                posts, _total, complete = paginate_all(
                    fetch_page,
                    page_size=20,
                    first_page=0,
                    max_pages=self.max_pages,
                    logger=None,
                    label=f"workday:{self._host}:search:{q}",
                )
                if not complete:
                    any_capped = True
                for p in posts:
                    key = p.get("externalPath") or p.get("title")
                    if key and key not in seen:
                        seen.add(key)
                        text_posts.append(p)

        # 4) 逐岗 detail 抓 jobDescription —— list 接口不含描述，外企卡片 JD 因此全空。
        #    GET {host}{externalPath} → jobPostingInfo.jobDescription（HTML；run.py 的 clean_summary 去标签解实体，
        #    且 summary 有正文后 extract_job_type/experience/education 能从中推断）。只抓将保留的在华岗
        #    （trusted 全保留；text_posts 取在华的），单源封顶防夜间全量被拖垮；失败该岗无摘要、不影响入库。
        self._enrich_descriptions(trusted, headers, filter_by_regions=False, regions=regions)
        self._enrich_descriptions(text_posts, headers, filter_by_regions=True, regions=regions)
        self.reported_total = len(trusted) + len(text_posts)
        self.fetch_complete = not any_capped

        return json.dumps({
            "_host": self._host, "_site": self._site,
            "trusted_posts": trusted, "text_posts": text_posts,
        }, ensure_ascii=False)

    def _collect_facet_posts(self, source_url, headers, candidates: dict, seen: set, out: List[dict]) -> bool:
        """按 {param: [id...]} 逐组分块翻页，新岗并入 out（按 externalPath 去重）。返回是否有组撞了翻页上限。"""
        any_capped = False
        for param, ids in candidates.items():
            if not ids:
                continue
            # ⚠️ appliedFacets[param] 里塞太多 id 会撞租户后端上限——实测 ThermoFisher 250 个 id 还
            # 200，300 个就 400；Mondelez 300 个还 200，904 个（不分块）500。阈值随租户/id 长度浮动，
            # 不是我们猜错了字面量（单 id 请求恒 200），是请求本身太大。分块提交、按块翻页并集去重，
            # 留足安全边界（2026-09-14~18 ThermoFisher/Mondelez 连续 failed 即此）。
            for chunk_start in range(0, len(ids), _FACET_ID_CHUNK):
                chunk = ids[chunk_start:chunk_start + _FACET_ID_CHUNK]

                def fetch_page(page: int, _chunk=chunk, _param=param) -> PageResult:
                    body = {"appliedFacets": {_param: _chunk}, "limit": 20, "offset": page * 20, "searchText": ""}
                    rr = _post_list(source_url, body, headers, self.timeout)
                    posts = rr.json().get("jobPostings", []) or []
                    return PageResult(items=posts, total=None)

                posts, _total, complete = paginate_all(
                    fetch_page,
                    page_size=20,
                    first_page=0,
                    max_pages=self.max_pages,
                    logger=None,
                    label=f"workday:{self._host}:{param}:{chunk_start}",
                )
                if not complete:
                    any_capped = True
                for p in posts:
                    key = p.get("externalPath") or p.get("title")
                    if key and key not in seen:
                        seen.add(key)
                        out.append(p)
        return any_capped

    @staticmethod
    def _iter_facet_values(facets):
        """深搜 facets，逐个产出 (facetParameter, value)。"""
        def walk(node):
            if isinstance(node, dict):
                param = node.get("facetParameter")
                for v in node.get("values", []) or []:
                    yield param, v
                    yield from walk(v)
            elif isinstance(node, list):
                for x in node:
                    yield from walk(x)
        yield from walk(facets)

    @staticmethod
    def _has_us_country_facet(facets) -> bool:
        """租户有没有国家级 US 聚合项（country / hierarchy 类 param 下、descriptor 恰为美国国名）。
        ⚠️ 要连 param 一起看：罗氏的 `locations` 下也有一个叫「United States of America」的叶子，
        它只挂 4 个岗（地点就写着国名），不是国家聚合——按 descriptor 单看会把罗氏误判成「已抓全」。"""
        for param, v in WorkdayAdapter._iter_facet_values(facets):
            if (param and v.get("id") and _COUNTRY_LEVEL_PARAM.search(param)
                    and str(v.get("descriptor") or "").strip().lower() in _US_COUNTRY_DESCRIPTORS):
                return True
        return False

    @staticmethod
    def _loose_us_facet_candidates(facets, regions) -> dict:
        """城市级 US 叶子：地点类 param 下、字面关键词没认出、但 geo 判为 US 的叶子 id，按 param 分组。
        regions 不含 US 或租户已有国家级 US facet 时返回空。"""
        regions = normalizer.source_regions(regions)
        if "US" not in regions or WorkdayAdapter._has_us_country_facet(facets):
            return {}
        groups: dict = {}
        for param, v in WorkdayAdapter._iter_facet_values(facets):
            desc = v.get("descriptor") or ""
            if not (param and v.get("id") and _LOCATION_PARAM.search(param)):
                continue
            if _is_facet_in_regions(desc, regions) or derive_country_code(desc) != "US":
                continue
            ids = groups.setdefault(param, [])
            if v["id"] not in ids:
                ids.append(v["id"])
        return groups

    _DETAIL_CAP = 300  # 单源逐岗 detail 抓取上限：覆盖绝大多数源；超大租户部分覆盖，避免拖垮夜间全量

    def _enrich_descriptions(self, posts: List[dict], headers: dict, filter_by_regions: bool, regions=None):
        """对将保留的岗位逐个 GET detail 端点，把 jobDescription 挂到 post['_jd']（供 parse 取作 summary）。"""
        n = 0
        for p in posts:
            if n >= resolve_detail_cap(self._DETAIL_CAP):
                break
            if not isinstance(p, dict):
                continue
            ep = (p.get("externalPath") or "").strip()
            if not ep:
                continue
            if filter_by_regions:
                loc = self._loc_from_path(ep) or p.get("locationsText")
                if not normalizer.location_in_source_regions(loc, regions):
                    continue
            try:
                d = httpx.get(f"{self._cxs_base}{ep}", headers=headers, timeout=self.timeout)
                if d.status_code < 300:
                    desc = (d.json().get("jobPostingInfo", {}) or {}).get("jobDescription")
                    if desc:
                        p["_jd"] = desc
                    n += 1
            except Exception:
                continue

    @staticmethod
    def _facet_candidates_for_regions(facets, regions) -> dict:
        """深搜 facets，按 facetParameter 分组收集 regions 相关叶子 id。
        返回 {param: [id...]}。**不跨 param 合并** —— 不同租户的可选叶子放在 locationHierarchy1 /
        locationCountry / locations 等不同 param，且 locationCountry 的国家聚合项常不可直接选（应用返回 0）。
        因此分组后由 _pick_best_facet 逐组试探、取命中最多的单组，自适应各租户 facet 结构。"""
        groups: dict = {}

        def walk(node):
            if isinstance(node, dict):
                param = node.get("facetParameter")
                for v in node.get("values", []) or []:
                    if param and v.get("id") and _is_facet_in_regions(v.get("descriptor", ""), regions):
                        ids = groups.setdefault(param, [])
                        if v["id"] not in ids:
                            ids.append(v["id"])
                for v in node.get("values", []) or []:
                    walk(v)
            elif isinstance(node, list):
                for x in node:
                    walk(x)

        for f in facets:
            walk(f)
        return groups

    @staticmethod
    def _china_facet_candidates(facets) -> dict:
        return WorkdayAdapter._facet_candidates_for_regions(facets, {"CN"})

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        host = data.get("_host", "")
        site = data.get("_site", "")

        out: List[RawJob] = []
        seen_urls = set()

        def emit(p, trusted):
            if not isinstance(p, dict):
                return
            title = (p.get("title") or "").strip()
            ep = (p.get("externalPath") or "").strip()
            if not title or not ep:
                return
            location = self._loc_from_path(ep) or (p.get("locationsText") or None)
            # trusted（facet 已服务端过滤）全部在华直接收；text_posts（searchText 文本召回）按 location 严格
            # 判定在华（大陆/港/澳）—— 外企 Workday 的 "Remote" 多指母国远程而非中国，故用 is_china_location，
            # 避免泄漏非华岗（如 "Remote - Delhi" / Haifa）。
            if not trusted and not normalizer.location_in_source_regions(
                location, getattr(self, "regions", None)
            ):
                return
            # 保留 CXS externalPath 全路径（/job/{location}/{title}_{id}），只补 locale 前缀 —— 这是
            # Workday 公开站的真实 SPA 路由。截成 /details/{slug} 会丢 location 段导致公开站 404。
            jd_url = f"{host}/en-US/{site}{ep}"
            if jd_url in seen_urls:
                return
            seen_urls.add(jd_url)
            out.append(RawJob(
                company="",  # 由 sources.company 兜底
                title=title,
                location=location,
                job_type=None,  # run.py 会用 extract_job_type(title, summary) 从正文推断
                summary=p.get("_jd"),  # detail 端点抓到的 jobDescription（HTML）；run.py clean_summary 去标签
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=None,  # postedOn 是相对文案（"Posted Yesterday"），不伪造日期
            ))

        # 向后兼容：旧形态 {"posts", "_china_filtered"}；新形态 {"trusted_posts","text_posts"}
        if "posts" in data:
            cf = data.get("_china_filtered")
            for p in data.get("posts", []):
                emit(p, trusted=bool(cf))
        else:
            for p in data.get("trusted_posts", []):
                emit(p, trusted=True)
            for p in data.get("text_posts", []):
                emit(p, trusted=False)
        return out

    @staticmethod
    def _loc_from_path(ep: str) -> Optional[str]:
        # externalPath: /job/China-Beijing/Title_JRxxxx → 第 2 段 "China-Beijing" → "China, Beijing"
        parts = [x for x in ep.split("/") if x]
        if len(parts) >= 2 and parts[0].lower() == "job":
            seg = _SPLIT_COUNTRY_RE.sub(lambda m: m.group(0).replace("-", " "), parts[1])
            seg = seg.replace("-", ", ").strip()
            return _normalize_iso3_country(_normalize_cn_country(seg)) or None
        return None


# 多词国名在路径里是连字符（'United-Kingdom---Remote'），上面的 replace('-', ', ') 会把它劈成
# 'United, Kingdom'，而 geo 的 OVERSEAS_LOCATION_PHRASES 是**整词组子串**匹配 → 认不出来 →
# 按 regions 兜底判 domestic（2026-09-23 live：United Kingdom 一类约 180 个在招岗，
# 另有 Saudi Arabia / South Africa / Costa Rica）。劈开之前先把国名里的连字符还原成空格。
# 'united states' 不在此列：geo 的 US 词表按词边界匹配，'United, States' 本来就认得，
# 收进来只会白白改写上万个美国岗的地点文本。
_SPLIT_COUNTRY_PHRASES = tuple(
    p for p in normalizer.OVERSEAS_LOCATION_PHRASES if " " in p and p != "united states"
)
_SPLIT_COUNTRY_RE = re.compile(
    r"(?i)(?<![a-z])(?:" + "|".join(re.escape(p).replace(r"\ ", "-") for p in _SPLIT_COUNTRY_PHRASES)
    + r")(?![a-z])"
)


def _normalize_cn_country(seg: str) -> str:
    """把 Workday externalPath 地点段里的 CHN/CN 国家缩写归一为 China。
    Workday 不同租户写法不一：'Xiamen, CHN' / 'XiamenCHN'（粘连）/ 'Sanshui, CN'。归一后地点展示更干净，
    且 facet=False 回退时 is_china_location 能正确识别为在华。仅匹配独立词或粘连城市尾的国家码，
    避免误伤含 'chn' 的词（如 München→munchen 实为 'chen' 不含 'chn'，且此处只动 CHN/CN 词边界）。"""
    if not seg:
        return seg
    # 粘连：XiamenCHN → Xiamen, China（城市小写尾 + 大写国家码 + 串尾）
    seg = re.sub(r"(?<=[a-z])(CHN|CN)$", r", China", seg)
    # 独立词：'Sanshui, CHN' / 'CN, Shanghai' → China
    seg = re.sub(r"(?i)\b(?:CHN|CN)\b", "China", seg)
    return seg.strip()


# externalPath 地点段里的 ISO-3166 alpha-3 国别码 → geo 认得的英文国名。
# 不展开的话 geo 按词边界一个都认不出来（'SingaporeSGP' / 'London, GBR' / 'USAVAReston'），
# derive_country_code=None → derive_job_scope 按 source.regions 兜底 → regions 含 CN 的源
# 把伦敦 / 曼谷 / 华沙 / 弗吉尼亚的岗判成 domestic（trusted 分支不做 per-job 地区复核，拦不住）。
# ⚠️ 只收「live 路径里真见过、且确实是国别码」的（2026-09-23 扫全部 123,143 个在招 workday 岗）。
#    刻意**不收**的撞车码，都是库里真见过的反例：
#      PHL = 费城（'US---PHL-OFFICE--WAREHOUSE…'）不是菲律宾；
#      NOR = 美国站点编号（'CAV17-NOR-Fairfax-…-VA-22031-USA'）不是挪威；
#      ANA = Santa Ana（'SANTA-ANA-CA'）；NAS = 海军航空站（'USA---NAS-JRB-New-Orleans-LA'）。
#    只认**大写**：小写的 can / col / ind / aus / fin 是英文词。
# ⚠️ 每加一个码都必须让 geo 判得出（大中华三地 → domestic，其余 → overseas），
#    crawler/test_foreign_ats.py 的契约测试逐条验。台湾展开后由 validate_job_quality 统一拒收。
_ISO3_COUNTRY_NAMES = {
    "HKG": "Hong Kong", "TWN": "Taiwan", "SGP": "Singapore",
    "CAN": "Canada", "MEX": "Mexico", "CRI": "Costa Rica", "BRA": "Brazil",
    "ARG": "Argentina", "COL": "Colombia",
    "GBR": "United Kingdom", "IRL": "Ireland", "DEU": "Germany", "FRA": "France",
    "ITA": "Italy", "ESP": "Spain", "POL": "Poland", "CZE": "Czechia", "HUN": "Hungary",
    "ROU": "Romania", "CHE": "Switzerland", "DNK": "Denmark", "FIN": "Finland",
    "IND": "India", "THA": "Thailand", "MYS": "Malaysia", "IDN": "Indonesia",
    "JPN": "Japan", "KOR": "South Korea", "AUS": "Australia", "ZAF": "South Africa",
}
_ISO3_ALT = "|".join(sorted(_ISO3_COUNTRY_NAMES))
_ISO3_GLUED_TAIL_RE = re.compile(r"(?<=[a-z])(" + _ISO3_ALT + r")$")
_ISO3_WORD_RE = re.compile(r"(?<![A-Za-z0-9])(" + _ISO3_ALT + r")(?![A-Za-z0-9])")
# 'USAVAReston' / 'USAIllinoisItasca60143'：国别码粘在**开头**、后面紧跟大写的州码或州名。
_USA_GLUED_HEAD_RE = re.compile(r"^USA(?=[A-Z])")


def _normalize_iso3_country(seg: str) -> str:
    """把 externalPath 地点段里的 alpha-3 国别码展开成国名（CHN 由 _normalize_cn_country 管）。
    'SingaporeSGP' → 'Singapore, Singapore'；'London, GBR' → 'London, United Kingdom'；
    'USAVAReston' → 'USA, VAReston'。"""
    if not seg:
        return seg
    seg = _USA_GLUED_HEAD_RE.sub("USA, ", seg)
    seg = _ISO3_GLUED_TAIL_RE.sub(lambda m: ", " + _ISO3_COUNTRY_NAMES[m.group(1)], seg)
    seg = _ISO3_WORD_RE.sub(lambda m: _ISO3_COUNTRY_NAMES[m.group(1)], seg)
    return seg.strip()

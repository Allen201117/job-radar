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
from .base import (
    BaseAdapter, DEFAULT_LIST_CAP, RawJob, RepetitionBrake, _env_int, exc_brief, resolve_detail_cap,
    resolve_list_cap,
)

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
# 列表接口的两条硬边界（2026-10-12 逐条实测，101 个启用源 293 个翻页查询）：
#   · 单页最多 20 条：limit=50 / 100 直接回 400；
#   · 一个查询最多给 2000 条：首页自报的 total 封顶在 2000；offset 翻过末尾（或 >= 2000）时**不回空页，
#     回的是第一页**（Target offset=2000 / 2020 / 2500 / 4000 四次都与 offset=0 逐条相同；
#     Diageo total=40 时 offset=40 起同样回第一页）。total 小于 2000 时是准的（280 个正常收尾的查询 0 个对不上）。
_PAGE_SIZE = 20
_QUERY_ROW_CAP = 2000
# 撞上限后按 facet 计数把一个查询切成几块，每块的计数和不超过这个数（留一成给切分与翻页之间的上新）。
_SPLIT_BLOCK_ROWS = 1800
# 最多连切几层（国家 → 州 → 用工类型 …）。再往下每层只多几个请求，但一路切不动说明这个租户的 facet 不适合切。
_SPLIT_MAX_DEPTH = 3
# _page_through 的三种结局
_ENDED, _FULL, _CUT = "ended", "full", "cut"

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


_GREATER_CHINA_CODES = frozenset({"CN", "HK", "MO"})


def _declared_country(info) -> Optional[str]:
    """detail 里对方自报的国家（ISO-2），给地点文本说不清国家的岗用（见 _resolve_declared_countries）。

    主依据是 jobRequisitionLocation.country.alpha2Code：2026-09-23 实测 1,053 个 detail 全都带它。
    **不用** jobPostingInfo.country：它会错——赛默飞「Remote, Georgia」写成格鲁吉亚（招聘地点是
    US - Atlanta, GA）、诺华美国远程岗写成瑞士、强生 New Brunswick (NJ) 写成加拿大。

    ⚠️ 宁可漏判：岗位的任何一处地点（自报国家 / 主地点 / 附加地点）沾大中华就判大中华。
    这批岗原本按 regions 兜底，外企源几乎都是 domestic；自报只该把「确实全在境外」的岗挪出去，
    不能因为招聘主地点在曼谷，就把同时挂着天津的岗（恩智浦，实测）挪出国内。
    """
    if not isinstance(info, dict):
        return None
    req = info.get("jobRequisitionLocation") or {}
    alpha2 = str((req.get("country") or {}).get("alpha2Code") or "").strip().upper()
    texts = [info.get("location"), req.get("descriptor"), (info.get("country") or {}).get("descriptor")]
    texts.extend(info.get("additionalLocations") or [])
    codes = [alpha2] + [derive_country_code(t) for t in texts if isinstance(t, str) and t.strip()]
    for code in codes:
        if code in _GREATER_CHINA_CODES:
            return code
    return alpha2 if re.fullmatch(r"[A-Z]{2}", alpha2) else None


def _search_texts_for_regions(regions):
    out = []
    for region in sorted(normalizer.source_regions(regions)):
        out.extend(_SEARCH_TEXT_BY_REGION.get(region, ()))
    return tuple(dict.fromkeys(out)) or _SEARCH_TEXT_BY_REGION["CN"]


def _post_key(p):
    return p.get("externalPath") or p.get("title")


def _facet_counts(facets) -> dict:
    """{param: {id: count}}。一个维度下每个取值的 count 受**其它**已选维度的过滤影响、不受本维度影响，
    且是准的（2026-10-12 Target：带国家过滤后 51 个州逐个翻完，每个州翻到的条数都等于它的 count）。"""
    out: dict = {}
    for param, v in WorkdayAdapter._iter_facet_values(facets):
        if param and v.get("id") and isinstance(v.get("count"), int):
            out.setdefault(param, {})[v["id"]] = v["count"]
    return out


def _declared_rows(applied: dict, counts: dict) -> Optional[int]:
    """这个查询对方自报有多少岗（首页 total 封顶在 2000，超过时只能从 facet 计数读）。
    每个已选维度的「已选取值计数和」都是一个上界（同一个岗挂多个取值会重复计），取最小的；
    只选了一个取值时就是准数。没有已选维度、或已选取值不在计数里 → None（不知道）。"""
    best = None
    for param, ids in applied.items():
        known = counts.get(param) or {}
        if not ids or any(i not in known for i in ids):
            continue
        n = sum(known[i] for i in ids)
        best = n if best is None else min(best, n)
    return best


def _pack_facet_ids(pairs, capacity: Optional[int] = None, max_ids: int = _FACET_ID_CHUNK) -> List[list]:
    """把 (id, 计数) 装成几块：每块计数和 <= capacity、id 数 <= max_ids；自己就超过 capacity 的取值单独一块
    （留给下一层换个维度再切）。先放大的，块数接近最少；同计数按原顺序，结果是确定的。"""
    capacity = _SPLIT_BLOCK_ROWS if capacity is None else capacity
    bins: List[list] = []   # [[id...], 计数和]
    for id_, n in sorted(pairs, key=lambda pair: -(pair[1] or 0)):
        n = n or 0
        for b in bins:
            if b[1] + n <= capacity and len(b[0]) < max_ids:
                b[0].append(id_)
                b[1] += n
                break
        else:
            bins.append([[id_], n])
    return [b[0] for b in bins]


def _split_plan(applied: dict, counts: dict, declared: Optional[int]):
    """把一个装不下（超过 _QUERY_ROW_CAP）的查询切成几块。返回 (块列表, 并集盖不盖得住原查询)；切不动返回 None。

    ① 查询本身是好几个取值的并集（城市级叶子一次提交 150 个）：按计数把这些取值重新分组，并集不变。
    ② 只剩一个取值（国家）：换一个维度切，在原条件上再叠一层。这个维度必须盖得住这个查询的全部岗——
       判据是它的计数和 >= 对方自报的岗数。⚠️ 不能见维度就切：Target 带国家过滤时 `locations` 只露出
       55 个叶子、766 个岗（全部 14,072），拿它切会静默丢掉九成五。盖得住的里面选「自己就超过上限的
       取值占得最少」的那个（Target：州，只有加州 2,155 要再切一层；职类里 Stores 一个就 13,646）。
    """
    multi = [p for p, ids in applied.items() if len(ids) > 1]
    if multi:
        param = max(multi, key=lambda p: len(applied[p]))
        ids = applied[param]
        known = counts.get(param) or {}
        bins = _pack_facet_ids([(i, known.get(i, 0)) for i in ids])
        if len(bins) < 2:   # 计数说一个查询装得下、实际却撞了上限：计数不可信，对半切
            bins = [ids[:len(ids) // 2], ids[len(ids) // 2:]]
        return [{**applied, param: b} for b in bins], True
    best = None
    for param, vals in counts.items():
        if param in applied:
            continue
        live = [(i, n) for i, n in vals.items() if n > 0]
        if len(live) < 2:
            continue
        total = sum(n for _i, n in live)
        covering = declared is not None and total >= declared
        oversize = sum(n for _i, n in live if n >= _SPLIT_BLOCK_ROWS)
        key = (0, oversize, total) if covering else (1, -total, oversize)
        if best is None or key < best[0]:
            best = (key, param, live, covering)
    if best is None:
        return None
    _key, param, live, covering = best
    return [{**applied, param: b} for b in _pack_facet_ids(live)], covering


class WorkdayAdapter(BaseAdapter):
    name = "workday"
    max_pages = 100  # 每页 20 × 100 页 = Workday 单个查询的硬上限 2000（见 _QUERY_ROW_CAP）；收尾见 _page_through

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
        self.coverage_stop_reason = None   # 同一实例被复用时（probe / 单测），上一条源的停因不许带到这一条
        # 下面四个只在「一个查询超过 2000 条、要切块」时用得上（见 _collect_capped），其余源碰不到它们。
        self._list_cap = resolve_list_cap(DEFAULT_LIST_CAP)
        self._split_brake = RepetitionBrake()
        self._split_halt = None      # 切块中途停下的原因：repetition_brake / list_cap
        self._declared_floor = 0     # 装不下的查询里，对方自报岗数最大的那个（抓全率的分母）
        self._split_keys = set()     # 正在切的那个查询，切出来的各块一共翻到了哪些岗（对自报数用）
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
        # （📌 2026-10-12 复核：293 个翻页查询里，total < 2000 的 280 个正常收尾的查询，total 与翻到的条数
        #   0 个对不上；「报 180 却能翻 600+」与「翻过末尾回第一页」的表现一致——这一句是推测，当时的数据没法回放。
        #   并集的做法不受影响；现在 total 只用来认「封顶在 2000 = 这个查询装不下」，见 _collect_query。）
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
                # 文本召回超过 2000 条时不切块：它带进来的是「正文提到 China / United States」的全球岗，
                # 逐岗还要再过 regions；2026-10-12 全部 101 个源没有一个文本查询真撞上限。
                if not self._collect_query(source_url, headers, {}, q, seen, text_posts,
                                           label=f"workday:{self._host}:search:{q}", splittable=False):
                    any_capped = True

        # 4) 逐岗 detail 抓 jobDescription —— list 接口不含描述，外企卡片 JD 因此全空。
        #    GET {host}{externalPath} → jobPostingInfo.jobDescription（HTML；run.py 的 clean_summary 去标签解实体，
        #    且 summary 有正文后 extract_job_type/experience/education 能从中推断）。只抓将保留的在华岗
        #    （trusted 全保留；text_posts 取在华的），单源封顶防夜间全量被拖垮；失败该岗无摘要、不影响入库。
        self._enrich_descriptions(trusted, headers, filter_by_regions=False, regions=regions)
        self._enrich_descriptions(text_posts, headers, filter_by_regions=True, regions=regions)

        # 5) 地点说不清国家的岗，问对方 detail 自报的国家（见 _resolve_declared_countries）。
        #    ⚠️ 不受 CRAWL_DETAIL_CAP 管：快档（cap=0）和重档必须对同一个岗给出同一个答案，
        #    否则一天四次快档判 domestic、夜里重档判 overseas，这个岗就在两个池子之间来回跳。
        self.country_lookup = {"needed": 0, "looked_up": 0, "declared": 0, "unresolved": 0}
        self._resolve_declared_countries(trusted, headers, filter_by_regions=False, regions=regions)
        self._resolve_declared_countries(text_posts, headers, filter_by_regions=True, regions=regions)
        unresolved = self.country_lookup["unresolved"]
        if unresolved:
            logger.warning("workday %s: %d/%d posts' country unresolved (detail unreachable), "
                           "not written this run", self._host, unresolved, self.country_lookup["needed"])
        self.fetch_complete = not any_capped and not unresolved
        # 分母：一般就是看见的全部；有查询装不下又没切全时，记对方 facet 自报的岗数——
        # 否则「自报 14,072、只拿到 2,008」在台账上是 2,008 / 2,008，谁也看不出少了。
        self.reported_total = len(trusted) + len(text_posts)
        if not self.fetch_complete:
            self.reported_total = max(self.reported_total, self._declared_floor)

        return json.dumps({
            "_host": self._host, "_site": self._site,
            "trusted_posts": trusted, "text_posts": text_posts,
        }, ensure_ascii=False)

    def _collect_facet_posts(self, source_url, headers, candidates: dict, seen: set, out: List[dict]) -> bool:
        """按 {param: [id...]} 逐组分块翻页，新岗并入 out（按 externalPath 去重）。返回是否有查询没抓全。"""
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
                if not self._collect_query(source_url, headers, {param: chunk}, "", seen, out,
                                           label=f"workday:{self._host}:{param}:{chunk_start}"):
                    any_capped = True
        return any_capped

    def _post_page(self, source_url, headers, applied: dict, search_text: str, page: int) -> dict:
        body = {"appliedFacets": applied, "limit": _PAGE_SIZE, "offset": page * _PAGE_SIZE,
                "searchText": search_text}
        data = _post_list(source_url, body, headers, self.timeout).json()
        return data if isinstance(data, dict) else {}

    def _collect_query(self, source_url, headers, applied: dict, search_text: str, seen: set, out: List[dict],
                       label: str, depth: int = 0, splittable: bool = True) -> bool:
        """翻完一个查询（appliedFacets + searchText），新岗并入 out。返回这个查询是否抓全。

        首页自报的 total 封顶（>= _QUERY_ROW_CAP）= 这个查询装不下，交给 _collect_capped 切块；
        其余照常翻到底（_page_through）。depth > 0 = 这是切出来的一块。
        """
        try:
            first = self._post_page(source_url, headers, applied, search_text, 0)
        except Exception as exc:
            if depth == 0:
                raise   # 与原来一致：一个查询的第一页就拿不到，交上层记 failed
            # 切出来的某一块第一页失败：保住别的块已经抓到的，如实记没抓全（同顺丰那块碑）
            logger.warning("%s: 第 1 页抓取失败，这一块本轮没抓：%s", label, exc_brief(exc))
            return False
        total = first.get("total")
        if splittable and isinstance(total, int) and total >= _QUERY_ROW_CAP:
            return self._collect_capped(source_url, headers, applied, first, seen, out, label, depth)
        end = self._page_through(source_url, headers, applied, search_text, first, seen, out, label,
                                 in_split=depth > 0)
        if (end == _FULL and splittable and not self._split_halt
                and self.max_pages * _PAGE_SIZE >= _QUERY_ROW_CAP):
            # 首页没报封顶、却真翻满了对方的单查询上限：同样是装不下，照样切（已经翻到的不重翻）。
            # 条件里带 max_pages：哪天有人把页数上限调小，「翻满」就不再等于「对方装不下」，不能据此切。
            return self._collect_capped(source_url, headers, applied, first, seen, out, label, depth,
                                        window_done=True)
        return end == _ENDED

    def _page_through(self, source_url, headers, applied: dict, search_text: str, first: dict, seen: set,
                      out: List[dict], label: str, in_split: bool) -> str:
        """从已经拿到的第一页起把一个查询翻到底。返回 _ENDED（自然收尾）/ _FULL（翻满上限）/
        _CUT（中途失败或被叫停）。
        in_split = 这是从一个装不下的查询里切出来的一块：每页过一遍两道闸（_split_should_halt），翻到的岗记进 _split_keys。

        收尾判据是「这一页没有带来这个查询里的新岗」，不是「空页」：翻过末尾时 Workday 回的是第一页
        （见 _QUERY_ROW_CAP）。条数恰好是 20 的整数倍的查询因此等不到短页也等不到空页——旧实现一路翻满
        100 页、记「可能未抓全」，2026-10-12 同一轮 101 个源里 11 个源 12 个查询中招、白翻 964 页
        （全部列表请求的两成），而这 12 个查询一个岗都没少。
        ⚠️ 判重用这个查询自己的集合，不用跨查询的 seen：后一组的头几页常常全是前一组抓过的岗。
        """
        query_seen = set()
        total = first.get("total")
        declared = total if isinstance(total, int) and 0 < total < _QUERY_ROW_CAP else None
        data = first
        ended = False
        for page in range(self.max_pages):
            if page:
                try:
                    data = self._post_page(source_url, headers, applied, search_text, page)
                except Exception as exc:
                    logger.warning("%s: 第 %d 页抓取失败，保留已抓 %d 条（尽力而为）：%s",
                                   label, page + 1, len(query_seen), exc_brief(exc))
                    return _CUT
            raw = data.get("jobPostings") or []
            posts = [p for p in raw if isinstance(p, dict)]
            fresh = {k for k in map(_post_key, posts) if k and k not in query_seen}
            if not fresh:
                ended = True   # 空页，或翻过末尾被绕回了第一页
                break
            query_seen |= fresh
            if in_split:
                self._split_keys |= fresh
            added = []
            for p in posts:
                key = _post_key(p)
                if key and key not in seen:
                    seen.add(key)
                    out.append(p)
                    added.append(p)
            if in_split and self._split_should_halt(added, seen):
                return _CUT
            if len(raw) < _PAGE_SIZE:
                ended = True
                break
        if not ended:
            logger.warning("%s: 命中安全翻页上限 %d，可能未抓全（got=%d）", label, self.max_pages, len(query_seen))
            return _FULL
        # 「没有新岗」也可能是对方中途把同一页回了两次。total 小于上限时是准的，拿它兜一道：
        # 少了一整页以上就不算翻完（少几条是翻页期间的正常下架）。
        if declared is not None and declared - len(query_seen) >= _PAGE_SIZE:
            logger.warning("%s: 翻到 %d 条就没有新岗了，对方自报 %d 条——按没抓全记", label, len(query_seen), declared)
            return _CUT
        return _ENDED

    def _split_should_halt(self, posts: List[dict], seen: set) -> bool:
        """切块翻页时每页问一次：还该不该往下翻。两道闸都是全站既有口径，不是 workday 另立的：
          · 重复度刹车（base.RepetitionBrake）：连续 400 条没带来一个新的归一标题 = 同一个岗 × N 家门店；
          · 单源条数上限（base.DEFAULT_LIST_CAP，env CRAWL_MAX_JOBS）。
        只管切出来的块；没撞 2000 上限的源不走这里，行为与原来逐条相同。
        posts 只传这一页**新收进来**的岗：别的块 / 这一块自己的窗口已经收过的岗再出现一次，说明不了
        「再往下翻还有没有新角色」（首页不报 total 的租户会先翻满一窗再切，切出来的头几页全是刚收过的）。
        叫停按源算、不按查询算：一个源被判成门店批量发布，它后面再有装不下的查询也不再整包切。"""
        if not self._split_halt:
            if self._split_brake.observe([p.get("title") for p in posts]):
                self._split_halt = "repetition_brake"
            elif len(seen) >= self._list_cap:
                self._split_halt = "list_cap"
            if self._split_halt:
                self.coverage_stop_reason = self._split_halt
                logger.warning("workday %s: 切块翻页停在 %s（已收 %d 条）", self._host, self._split_halt, len(seen))
        return bool(self._split_halt)

    def _collect_capped(self, source_url, headers, applied: dict, first: dict, seen: set, out: List[dict],
                        label: str, depth: int, window_done: bool = False) -> bool:
        """一个查询超过 2000 条（Workday 只给前 2000）：按 facet 计数切成装得下的几块，分别翻、取并集。

        2026-10-12 实测唯一真撞上限的是 Target：美国岗自报 14,072，旧实现每轮只见 2,008，库里另有 2,107 个
        仍在招的岗（其中 208 个是总部 / 技术 / 实习岗）再也刷不到 last_seen_at，列表字段改了规则也不自愈。
        按州切 + 加州再按用工类型切，逐块翻完 = 14,071 条，与自报只差 1。

        没切全时（切不动 / 没有盖得住的维度 / 刹车 / 撞单源上限）一律把原查询自己的前 2000 条照拿一遍：
        那是改之前就拿得到的，保证任何情况下都不比改前少。
        """
        counts = _facet_counts(first.get("facets"))
        declared = _declared_rows(applied, counts)
        if depth == 0 and declared:
            self._declared_floor = max(self._declared_floor, declared)
        plan = None
        if depth < _SPLIT_MAX_DEPTH and not self._split_halt:
            plan = _split_plan(applied, counts, declared)
        complete = False
        mark = len(out)
        outer_keys, self._split_keys = self._split_keys, set()   # 这一层切出来的各块一共翻到了哪些岗
        if plan is not None:
            blocks, complete = plan
            logger.info("%s: 自报 %s 条超过单查询上限 %d，切成 %d 块", label, declared, _QUERY_ROW_CAP, len(blocks))
            for i, block in enumerate(blocks):
                if self._split_halt:
                    complete = False
                    break
                if not self._collect_query(source_url, headers, block, "", seen, out, f"{label}/{i}", depth + 1):
                    complete = False
            # 每一块都翻完了，并集却明显少于对方自报的岗数 = 这个维度其实没盖住（或计数不准）：不算抓全。
            # 只在自报数是准数（每个已选维度只有一个取值）时比，哪一层都比；容差 1% 或一页，
            # 给切分与翻页之间的上下架——依据只有 Target 一家（14,072 对 14,071），别的租户没验过。
            exact = all(len(ids) == 1 for ids in applied.values())
            if (complete and exact and declared
                    and len(self._split_keys) < declared - max(_PAGE_SIZE, declared // 100)):
                logger.warning("%s: 切了 %d 块都翻完，只见 %d 条，对方自报 %d 条——按没抓全记",
                               label, len(blocks), len(self._split_keys), declared)
                complete = False
        outer_keys |= self._split_keys
        self._split_keys = outer_keys
        if complete:
            return True
        if depth > 0:
            # 里层切不动的一块：尽力拿它自己的前 2000 条，照样受两道闸管。切过但没切全的不再补——
            # 每层都补一遍就是每层白翻 100 页，「不比改前少」由最外层那一窗兜。
            if plan is None and not window_done and not self._split_halt:
                self._page_through(source_url, headers, applied, "", first, seen, out, label, in_split=True)
            return False
        if self._split_halt == "repetition_brake":
            # 刹车前翻到的那几百条是「哪一块排在前面就是哪一块」的门店岗（Target 实测：加州的前 780 条）。
            # 留着它们 = 又多一批下一轮未必还够得着的行，正是要治的病；批量源只收「原窗口 + 小众取值」。
            for p in out[mark:]:
                seen.discard(_post_key(p))
            del out[mark:]
        if not window_done:
            self._page_through(source_url, headers, applied, "", first, seen, out, label, in_split=False)
        if self._split_halt == "repetition_brake":
            self._collect_minor_values(source_url, headers, applied, counts, seen, out, label)
        return False

    def _collect_minor_values(self, source_url, headers, applied: dict, counts: dict, seen: set,
                              out: List[dict], label: str) -> None:
        """刹车判定为门店批量发布的源：那一大包不整包拉（全站口径，见 base.DEFAULT_LIST_CAP 的注释），
        但批量岗都压在各维度的某一个大取值上，其余取值合起来装得进一个查询——把它们各翻一遍。

        Target（2026-10-12）：14,071 个美国岗归一后只有 694 种标题、前 20 种占 91.8%；职类 Stores 一项
        13,646，其余 17 个职类（实习 / 供应链 / 技术 …）合计 426 个、386 种标题，正是用户要看的那部分，
        而它们有一半排在前 2000 条之外。只取「有压倒性大取值的维度里、剩下那些取值」：
        州这种没有压倒性取值的维度不取（它的小取值加起来就是那一大包）。
        已选维度自己也算：几个国家一起提交、批量的那个国家被叫停时，剩下的小国家（在华 / 新加坡）
        排在它后面还没轮到，要在这里单独翻全。
        """
        for param, vals in counts.items():
            if param in applied:
                if len(applied[param]) < 2:
                    continue
                vals = {i: vals.get(i, 0) for i in applied[param]}
            live = [(i, n) for i, n in vals.items() if n > 0]
            minor = [(i, n) for i, n in live if n < _SPLIT_BLOCK_ROWS]
            if (not minor or len(minor) == len(live) or len(minor) > _FACET_ID_CHUNK
                    or sum(n for _i, n in minor) > _SPLIT_BLOCK_ROWS):
                continue
            block = {**applied, param: [i for i, _n in minor]}
            sub_label = f"{label}/minor:{param}"
            try:
                first = self._post_page(source_url, headers, block, "", 0)
            except Exception as exc:
                logger.warning("%s: 第 1 页抓取失败，这一块本轮没抓：%s", sub_label, exc_brief(exc))
                continue
            self._page_through(source_url, headers, block, "", first, seen, out, sub_label, in_split=False)

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
            loc = self._post_location(p)
            if filter_by_regions and not normalizer.location_in_source_regions(loc, regions):
                continue
            try:
                d = httpx.get(f"{self._cxs_base}{ep}", headers=headers, timeout=self.timeout)
                if d.status_code < 300:
                    info = d.json().get("jobPostingInfo", {}) or {}
                    desc = info.get("jobDescription")
                    if desc:
                        p["_jd"] = desc
                    if normalizer.needs_declared_country(loc):
                        # 同一个响应里就有国家，顺手记下，第 5 步不必再为它请求一次。
                        p["_country"] = _declared_country(info)
                    n += 1
            except Exception:
                continue

    _COUNTRY_LOOKUP_CAP = 2000  # 单源「只为问国家」的 detail 请求上限（2026-09-23 实测单源最多 ~310 个）

    def _resolve_declared_countries(self, posts: List[dict], headers: dict, filter_by_regions: bool, regions=None):
        """地点文本说不清国家的岗（'Durham' / 'Remote' / 'One Island East'），问 detail 要对方自报的国家，
        记在 post['_country']，parse 交给 RawJob.country_code。

        为什么要问：这批岗的 job_scope 原本只能按 source.regions 猜，而外企源 regions 大多含 CN →
        一律判 domestic。2026-09-23 香港库实测这样判 domestic 的在招 workday 岗 1,715 个，
        detail 问得到国家的 1,053 个里 US 541 / HK 306 / GB 28 / CN 27 / CA 24 …

        防来回跳（同一个岗今天 overseas、明天 domestic）的三条：
          · 每个需要的岗每一轮都问，不看 CRAWL_DETAIL_CAP（见 fetch 第 5 步）；
          · detail 明确说「这个岗不对外」（4xx）是确定答复 → 按原样走 regions 兜底，每轮结果一样；
          · 超时 / 5xx / 限流重试后仍拿不到 = 这一轮不知道 → **这个岗本轮不写库**（parse 跳过），
            库里保留上一轮的判定，fetch_complete 如实记 False。宁可一轮没刷新，不拿猜的值覆盖。
        """
        cap = _env_int("CRAWL_COUNTRY_LOOKUP_CAP", self._COUNTRY_LOOKUP_CAP)
        stats = self.country_lookup
        for p in posts:
            if not isinstance(p, dict) or "_country" in p:
                continue
            ep = (p.get("externalPath") or "").strip()
            if not ep or not (p.get("title") or "").strip():
                continue  # parse 不会产出它，不用问
            loc = self._post_location(p)
            if filter_by_regions and not normalizer.location_in_source_regions(loc, regions):
                continue
            if not normalizer.needs_declared_country(loc):
                continue
            stats["needed"] += 1
            if stats["looked_up"] >= cap:
                p["_country_unresolved"] = True
                stats["unresolved"] += 1
                continue
            stats["looked_up"] += 1
            status, info = self._get_detail(ep, headers)
            if status is None:
                p["_country_unresolved"] = True
                stats["unresolved"] += 1
                continue
            p["_country"] = _declared_country(info) if info is not None else None
            if p["_country"]:
                stats["declared"] += 1
            if info is not None and info.get("jobDescription") and not p.get("_jd"):
                p["_jd"] = info["jobDescription"]  # 已经拿到了，不多花请求

    def _get_detail(self, ep: str, headers: dict):
        """GET detail。返回 (status, jobPostingInfo)：
        2xx → (status, info)；4xx（429 除外）→ (status, None)，确定答复（岗位不对外 / 已下架）；
        连接异常 / 5xx / 429 重试一次仍失败 → (None, None)，本轮不知道。"""
        url = f"{self._cxs_base}{ep}"
        for attempt in range(2):
            last = attempt == 1
            try:
                d = httpx.get(url, headers=headers, timeout=self.timeout)
            except Exception as e:
                if last:
                    logger.info("workday detail %s failed twice: %r", url, e)
                    return None, None
                time.sleep(1)
                continue
            if d.status_code == 429 or d.status_code >= 500:
                if last:
                    return None, None
                try:
                    wait = float(d.headers.get("Retry-After", 1))
                except (TypeError, ValueError):
                    wait = 1
                time.sleep(min(30, max(0, wait)))
                continue
            if d.status_code >= 300:
                return d.status_code, None
            try:
                return d.status_code, d.json().get("jobPostingInfo") or {}
            except ValueError:
                if last:
                    return None, None
                time.sleep(1)
        return None, None

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
            if p.get("_country_unresolved"):
                return  # 本轮没问到国家：不写这一行，库里保留上一轮的判定（见 _resolve_declared_countries）
            location = self._post_location(p)
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
                country_code=p.get("_country"),  # 对方 detail 自报的国家；只在地点说不清时生效
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
    def _post_location(p: dict) -> Optional[str]:
        """parse 写进 RawJob.location 的那个地点。问不问国家、按不按 regions 过滤都必须看同一个值。"""
        ep = (p.get("externalPath") or "").strip()
        return WorkdayAdapter._loc_from_path(ep) or (p.get("locationsText") or None)

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

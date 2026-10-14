"""好未来校招官网 job.tal.com（集团 / 学而思 / 学而思网校 三个站点），纯 httpx、零鉴权。

## 为什么有这个 adapter（2026-10-12）
好未来的校招原来接的是 Moka 门户 `app.mokahr.com/campus-recruitment/tal/146099`。2026-09-10~13 之间对方把这个
路径 302 到了自己写的前端 job.tal.com：旧源从此每轮失败，库里 987 个在招行的链接全部落到新站首页（真浏览器
逐个打开：打得开 0 / 打不开 987）。新站用的岗位号与 Moka 是同一套 uuid，只是换了前端和接口。

## 三个站点（各是一条源，源地址 = 该站的「在招职位」页）
    https://job.tal.com/campus/positions            好未来招聘官网（集团）      渠道号 kg8Meh
    https://job.tal.com/campus/xes/positions        学而思校园招聘              渠道号 fXinVq
    https://job.tal.com/campus/xesonline/positions  学而思网校校园招聘          渠道号 iyZkOo
渠道号写在各站入口脚本的 `VITE_JOB_DEFAULT_CHANNEL` 里。接口回「渠道不存在」时去入口脚本重读一次，读不到就抛错。
⚠️ 渠道号绝不能传空串：接口会回整个租户的 2,500 多个岗（含没有对外发布的）。

集团站的列表**包含**另外两个品牌站的岗（2026-10-12：139 = 学而思 30 + 网校 14 + 集团自己的 95）。
集团那条源会把品牌站列出的岗剔掉，否则同一个岗两条源各写一行、链接只差一段路径。品牌站的列表取不全时
集团源整轮抛错——宁可这一轮不写，也不写一批重复行。

## 接口（都是从页面自己发的请求里读出来的；项目 UA、不带 Origin / Referer 也通）
- 列表：`POST https://job-api.100tal.com/sapi/activities/c/jobs/list`
  体 `{"orgId":"tal","route_code":<渠道号>,"limit":100,"offset":<页码>,"site":"campus","keyword":"",
       "locations":[],"commitments":[],"zhinengIds":[],"tag_ids":[]}`
  🚫 `offset` 是**页码**（从 0 起），不是偏移量：按偏移量翻（offset=20）第二页直接回 0 条，会被当成取完了。
  🚫 `limit` 最大只给 100（传更大也只回 100）。所以收尾看「这一页有没有带来新岗位」，不看条数。
  正文 `description`（HTML）就在列表行里，不用再逐岗取详情。
- 详情页：`https://job.tal.com/campus[/xes|/xesonline]/positions/<job_id>`，匿名可开，有「申请职位」按钮；
  已停的岗页面写「职位已停止招聘」（audit_dead_links 现有强信号认得）。

## robots / 预检（2026-10-12 核过）
job.tal.com、job-api.100tal.com 的 /robots.txt 都是 404（无限制）。BaseAdapter.should_skip 对三个源地址
HEAD 都是 200，不覆写。

## 官网只列「合并岗」
学而思站列的是一个角色配多个城市的合并岗（「科学思维教师-27校招」43 个城市）。Moka 后台里另有按分校拆开的
岗（「…-昆明分校-27校招」），官网列表不列——本 adapter 只跟官网列表走，不去枚举它们。

## 下架
列表就是该站对外的全集（三个站点自报总数与翻到的条数逐个相等），所以开 list-absence：抓全了的那一轮，
列表里没有的在招行判撤岗。集团源的「全集」是剔掉品牌站之后的那部分，两边口径一致。
"""
import json
import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import httpx

import normalizer
from .base import BaseAdapter, RawJob, exc_brief, resolve_list_cap, resolve_page_cap

_log = logging.getLogger(__name__)

_SITE = "https://job.tal.com"
_LIST_API = "https://job-api.100tal.com/sapi/activities/c/jobs/list"
# 站点路径前缀 → 渠道号（2026-10-12 读自各站入口脚本）
_CHANNELS = {
    "/campus": "kg8Meh",
    "/campus/xes": "fXinVq",
    "/campus/xesonline": "iyZkOo",
}
_GROUP_BASE = "/campus"
_BRAND_BASES = ("/campus/xes", "/campus/xesonline")
# 源地址只认站点根和它的这两个页面；/campus/ 下别的路径（将来的第四个站点）不许落到集团站头上
_SITE_PAGES = ("", "/positions", "/home")
# 列表里混着的占位岗（「没有合适职位也可以投」那个入口），不是岗位
_PLACEHOLDER_TITLES = frozenset({"无职位投递"})
_NO_CHANNEL_MSG = "渠道不存在"
_ENTRY_SCRIPT_RE = re.compile(r'src="(https://[^"]+/js/index-[^"]+\.js)"')
_CHANNEL_IN_SCRIPT_RE = re.compile(r'VITE_JOB_DEFAULT_CHANNEL:"([A-Za-z0-9]+)"')
# 对方自己打的招聘项目标签里，这两个是实习；「校园招聘-实习转正」是给应届生的转正岗，不算实习
_INTERN_TAGS = frozenset({"实习生", "日常实习"})
_CONVERSION_MARK = "实习转正"


class _ChannelGone(RuntimeError):
    """列表接口说这个渠道号不存在（渠道号换了）。"""


def site_base(source_url: str) -> str:
    """源地址 → 站点路径前缀（/campus、/campus/xes、/campus/xesonline）。认不出就抛错，不猜。"""
    parsed = urlparse(source_url or "")
    if (parsed.hostname or "").lower() != "job.tal.com":
        raise ValueError(f"tal: 源地址不在 job.tal.com 上：{source_url}")
    path = parsed.path.rstrip("/")
    for base in _CHANNELS:
        if any(path == base + page for page in _SITE_PAGES):
            return base
    raise ValueError(f"tal: 源地址不是已知的三个站点之一：{source_url}")


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def job_type_of(row: dict) -> str:
    """喂给分类器的招聘类型标签：只转述对方自己的标注，不替分类器下结论。

    对方把这些岗全标成校招（hire_mode）；实习靠招聘项目标签（实习生 / 日常实习）和工作性质（实习）认。
    「27实习转正-…」是给应届生的转正岗：工作性质写实习或兼职，项目标签是「校园招聘-实习转正」，按校招报。"""
    tags = {str(t).strip() for t in (row.get("tag_names") or [])}
    if tags & _INTERN_TAGS:
        return "实习"
    title = str(row.get("title") or "")
    if any(_CONVERSION_MARK in t for t in tags) or _CONVERSION_MARK in title:
        return "校园招聘"
    if str(row.get("commitment") or "").strip() == "实习":
        return "实习"
    return "校园招聘"


class TalAdapter(BaseAdapter):
    name = "tal"
    company_name = ""   # 三个站点三家牌子，由 sources.company 兜底
    official_hosts = ("job.tal.com", "job-api.100tal.com")
    supports_absence_liveness = True

    PAGE_SIZE = 100     # 接口给的上限
    LIST_CAP = 2000     # 现状三个站点合计不到 200；页数上限由它换算（resolve_page_cap）

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": _SITE + "/",
        }

    # ── 渠道号 ────────────────────────────────────────────────────────────────
    def _discover_route(self, client: httpx.Client, base: str) -> Optional[str]:
        """从该站入口脚本里重读渠道号。读不到返回 None（调用方抛错），绝不返回空串。"""
        try:
            page = client.get(f"{_SITE}{base}/home")
            page.raise_for_status()
            script = _ENTRY_SCRIPT_RE.search(page.text)
            if not script:
                return None
            js = client.get(script.group(1))
            js.raise_for_status()
            found = _CHANNEL_IN_SCRIPT_RE.search(js.text)
        except httpx.HTTPError as exc:
            _log.warning("tal: 重读 %s 的渠道号失败 %s", base, exc_brief(exc))
            return None
        if not found:
            return None
        code = found.group(1)
        if any(code == other for site, other in _CHANNELS.items() if site != base):
            # 三个站点各有各的入口脚本；读回来的是别站的渠道号 = 拿错了页面，用它会把别站的岗写到本站名下
            _log.warning("tal: %s 的入口脚本里读到的是别的站点的渠道号，不采用", base)
            return None
        return code

    # ── 列表 ──────────────────────────────────────────────────────────────────
    def _list_page(self, client: httpx.Client, route: str, page: int) -> dict:
        """取一页，返回 data（含 total / list）。任何「不是一页正常数据」的情况都抛错。"""
        if not route:
            raise RuntimeError("tal: 渠道号为空（空渠道号会取回未对外发布的岗），拒绝请求")
        resp = client.post(_LIST_API, json={
            "orgId": "tal", "route_code": route, "limit": self.PAGE_SIZE, "offset": page,
            "site": "campus", "keyword": "", "locations": [], "commitments": [],
            "zhinengIds": [], "tag_ids": [],
        })
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict) or payload.get("code") != 200:
            code = payload.get("code") if isinstance(payload, dict) else None
            msg = payload.get("msg") if isinstance(payload, dict) else None
            err = _ChannelGone if _NO_CHANNEL_MSG in str(msg or "") else RuntimeError
            raise err(f"tal: 列表接口回 code={code} msg={msg}")
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            # HTTP 200 + 没有 list：不能读成「0 个岗」
            raise RuntimeError("tal: 列表接口回 200 但没有 data.list（多半是接口改版）")
        return data

    def _fetch_channel(self, client: httpx.Client, base: str) -> Tuple[List[dict], Optional[int], Optional[str]]:
        """翻完一个站点的列表，返回 (去重后的行, 接口自报总数, 没抓全的原因)。原因为 None = 抓全了。

        没用 base.paginate_all：它按原始行数判「收满」、不去重，翻页参数一旦失效（每页回同一批）重复行会凑够总数；
        接口没给总数时它按空页收尾也算抓全。这里要的是按岗位号去重后的条数 >= 自报总数才算。
        第一页失败原样上抛（记 failed）；后面的页失败保留已取到的行、按没抓全收尾。"""
        route = _CHANNELS[base]
        seen: set = set()
        rows: List[dict] = []
        total: Optional[int] = None
        cap = resolve_list_cap(self.LIST_CAP)
        stop: Optional[str] = "page_cap"
        for page in range(resolve_page_cap(self.PAGE_SIZE, self.LIST_CAP)):
            try:
                try:
                    data = self._list_page(client, route, page)
                except _ChannelGone:
                    if page != 0:
                        raise
                    fresh_route = self._discover_route(client, base)
                    if not fresh_route or fresh_route == route:
                        raise
                    _log.warning("tal: %s 的渠道号变了，按入口脚本里的新值重试", base)
                    route = fresh_route
                    data = self._list_page(client, route, page)
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                if page == 0:
                    raise RuntimeError(f"tal: {base} 列表请求失败 —— {exc_brief(exc)}") from exc
                _log.warning("tal: %s 第 %d 页失败，按没抓全收尾 %s", base, page, exc_brief(exc))
                stop = "page_failed"
                break
            if total is None:
                # 只认第一次报的总数：后面的页把总数报小了，不能让「抓全」的门槛跟着降
                total = _int_or_none(data.get("total"))
            fresh = [r for r in data["list"]
                     if isinstance(r, dict) and r.get("job_id") and r["job_id"] not in seen]
            for r in fresh:
                seen.add(r["job_id"])
                rows.append(r)
            # 收尾看「这一页有没有带来新岗位」：offset 是页码、limit 有上限，条数说明不了问题
            if total is not None and len(rows) >= total:
                stop = None
                break
            if not fresh:
                stop = "page_no_new_rows" if rows else "empty"
                break
            if len(rows) >= cap:
                stop = "list_cap"
                break
        return rows, total, stop

    def _brand_ids(self, client: httpx.Client) -> set:
        """两个品牌站当前列出的全部岗位号。任一个没取全就抛错：没法确定集团站里哪些岗该剔。"""
        ids: set = set()
        for brand in _BRAND_BASES:
            b_rows, _total, b_stop = self._fetch_channel(client, brand)
            if b_stop is not None:
                raise RuntimeError(
                    f"tal: 品牌站 {brand} 的列表没取全（{b_stop}），没法从集团站里剔掉它的岗 —— 本轮不写，避免重复行")
            ids |= {r["job_id"] for r in b_rows}
        return ids

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        self.coverage_stop_reason = None
        base = site_base(source_url)
        brand_ids: set = set()
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=self._headers()) as client:
            rows, total, stop = self._fetch_channel(client, base)
            if base == _GROUP_BASE:
                if not rows:
                    # 集团站一个岗都没有：不据此判定好未来没在招，先当接口出了问题
                    raise RuntimeError("tal: 集团站列表为空（接口回 200、0 个岗）—— 不按「没在招」处理，需人工核查")
                brand_ids = self._brand_ids(client)

        kept, dropped, not_open, unmappable = [], 0, 0, 0
        for row in rows:
            title = str(row.get("title") or "").strip()
            if not title:
                unmappable += 1
            elif row["job_id"] in brand_ids or title in _PLACEHOLDER_TITLES:
                dropped += 1
            elif str(row.get("status") or "open").strip() != "open":
                not_open += 1
            else:
                kept.append(row)
        if rows and not kept and (unmappable or not_open):
            # 列表有行、该这条源写的却一条都留不下：多半是字段改名 / status 换了取值，不许记成「0 个岗、成功」
            raise RuntimeError(
                f"tal: 列表 {len(rows)} 行里没有一条可写（无标题 {unmappable}、status 不是 open {not_open}）"
                " —— 多半是接口字段变了")

        if total is not None:
            # 分母 = 接口自报总数里应该由这条源写的那部分（剔掉品牌站的岗、占位岗、已停的）
            self.reported_total = max(total - dropped - not_open, 0)
        # 接口自报 0 个岗（品牌站一批招完、下一批没开）也是抓全：这一轮 0 岗，run.py 在写库前就返回，不会走到缺席下架。
        self.fetch_complete = stop is None and unmappable == 0
        if stop in ("list_cap", "page_no_new_rows"):
            self.coverage_stop_reason = stop
        return json.dumps({"base": base, "rows": kept}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            payload = json.loads(html) or {}
        except (json.JSONDecodeError, TypeError):
            return []
        base = payload.get("base")
        if base not in _CHANNELS:
            return []
        jobs: List[RawJob] = []
        for row in payload.get("rows") or []:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("job_id") or "").strip()
            title = str(row.get("title") or "").strip()
            if not job_id or not title:
                continue
            bits = []
            zhineng = row.get("zhineng")
            function = str(zhineng.get("name") or "").strip() if isinstance(zhineng, dict) else ""
            if function:
                bits.append(f"职能类型：{function}")
            # description 是 HTML 片段，交给 normalizer.clean_summary 统一去标签 / 截断
            description = str(row.get("description") or "").strip()
            if description:
                bits.append(description)
            jd_url = f"{_SITE}{base}/positions/{job_id}"
            jobs.append(RawJob(
                company=self.company_name or "",
                title=title,
                location=normalizer.join_places(row.get("Locations") or []),
                job_type=job_type_of(row),
                summary="\n".join(bits).strip() or None,
                jd_url=jd_url,
                apply_url=jd_url,
                # 发布日不填：接口只有 created_at（建岗时间）和 updated_at，页面上写的是「更新于」
            ))
        return jobs

"""
飞书/Lark 招聘平台通用层（{company}.jobs.feishu.cn）。

与字节同平台：拦截 /api/v1/search/job/posts，岗位在 data.job_post_list，
详情页 https://{host}/index/position/{id}/detail。一套适配覆盖蔚来/小鹏/地平线/小米。

分页（与北森同思路）：列表页只发**一次** offset=0&limit=10 的 POST，被动拦截 + 滚动翻页
最多 max_pages 页 → 恰好截断在 ~40 条（实测 ponyai 实有 93、ecoflow 实有 209）。
data.count 给出真实总数。修复：捕获该 POST，用站点自身 session（含 _signature，实测签名
**不绑定** offset/limit，可复用）服务端翻页重放 limit=50 直到收齐 count，合成同 shape 响应。
捕获不到 POST 则回退被动拦截（super().fetch）。复用站点请求、不破签名、低频。
"""
import json
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import httpx

import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter, _UA


class FeishuRecruitAdapter(PlaywrightAdapter):
    host = ""  # 子类设置，如 nio.jobs.feishu.cn
    intercept_match = "/api/v1/search/job/posts"
    posts_keys = ("data.job_post_list", "job_post_list")
    _PAGE_SIZE = 50    # 单页拉取数（接口实测 limit=50 稳定返回，远超站点默认 10）
    _MAX_JOBS = 600    # 单租户上限（防超大公司一次拉爆）
    _HTTPX_TIMEOUT = 20

    # list-absence 探活：feishu posts API 返**全量在招岗**（非夹带已关闭岗），且本类按 count 翻全；
    # 故抓全时「上次在、这次没了」可判下架。仅 fetch_complete=True 时生效（见 run.py 兜底）。
    supports_absence_liveness = True
    fetch_complete = False  # 每次 fetch 末尾置位：是否抓到完整列表（翻到 count、未撞 _MAX_JOBS 上限）

    def __init__(self):
        self.official_hosts = (self.host,)
        self.detail_template = "https://" + self.host + "/index/position/{id}/detail"
        self.list_urls = [
            "https://" + self.host + "/index/position",
            "https://" + self.host + "/",
        ]
        self.fetch_complete = False

    def _resolve_host(self, source_url: str) -> str:
        """httpx 直拉用的 host：子类有 self.host；通用类 fetch 前已 _bind_host → official_hosts[0]。"""
        if self.official_hosts and self.official_hosts[0]:
            return self.official_hosts[0]
        return urlparse(source_url).netloc

    def _httpx_fetch(self, host: str) -> Tuple[List[dict], Optional[int], bool]:
        """纯 httpx 直拉 posts API（feishu_probe 已实证冷启动可达：真实 Chrome UA、无签名、无 cookie）。
        翻页到 data.count，返回 (rows, total, reached)。reached=至少一次拿到合法 data dict（用于区分
        '真 0 岗' 与 'httpx 没打通'——前者照常返回空、后者回退浏览器）。daily-crawl 无 Playwright 也能跑。"""
        rows: List[dict] = []
        seen: set = set()
        total: Optional[int] = None
        reached = False
        offset = 0
        headers = {"User-Agent": _UA, "Accept-Language": "zh-CN,en;q=0.9",
                   "Content-Type": "application/json",
                   "Referer": f"https://{host}/index/position"}
        try:
            with httpx.Client(timeout=self._HTTPX_TIMEOUT, follow_redirects=True, headers=headers) as cli:
                while len(rows) < self._MAX_JOBS:
                    body = {"keyword": "", "limit": self._PAGE_SIZE, "offset": offset,
                            "job_category_id_list": [], "tag_id_list": [], "location_code_list": [],
                            "subject_id_list": [], "recruitment_id_list": [], "portal_type": 2,
                            "job_function_id_list": [], "storefront_id": ""}
                    try:
                        r = cli.post(f"https://{host}/api/v1/search/job/posts", json=body)
                        jj = r.json()
                    except Exception:
                        break
                    data = (jj or {}).get("data") if isinstance(jj, dict) else None
                    if not isinstance(data, dict):
                        break
                    reached = True
                    if total is None:
                        total = data.get("count") or 0
                    chunk = data.get("job_post_list") or []
                    if not isinstance(chunk, list) or not chunk:
                        break
                    for post in chunk:
                        pid = str((post or {}).get("id") or "")
                        if pid and pid not in seen:
                            seen.add(pid)
                            rows.append(post)
                    if total and len(rows) >= total:
                        break
                    if len(chunk) < self._PAGE_SIZE:  # 末页不足一页 → 收完
                        break
                    offset += self._PAGE_SIZE
        except Exception:
            return rows, total, reached
        return rows, total, reached

    def fetch(self, source_url: str) -> str:
        """httpx-first：冷启动直拉 posts API（无浏览器，daily-crawl 4×/天可跑）；httpx 未打通才回退
        浏览器抓包链（仅 Playwright 可用环境如 enrich-crawl）。"""
        self.fetch_complete = False
        host = self._resolve_host(source_url)
        if host:
            rows, total, reached = self._httpx_fetch(host)
            if reached:
                # httpx 打通（含真 0 岗）→ 直接用，不再开浏览器。complete=翻全（含 0 岗）。
                self.fetch_complete = (total is not None and len(rows) >= (total or 0))
                return json.dumps(
                    {"_intercepted": [{"data": {"job_post_list": rows, "count": total if total is not None else len(rows)}}]},
                    ensure_ascii=False)
        # httpx 没打通（reached=False）→ 回退浏览器抓包（无 Playwright 环境会抛 → 上层记 failed，不写空）
        return self._browser_fetch(source_url)

    def _browser_fetch(self, source_url: str) -> str:
        """捕获列表页自己发的 posts POST → 用站点 session 服务端翻页重放收齐 count；
        捕获不到（站点改版/反爬）则回退被动拦截链（与原行为一致，零回归）。"""
        from playwright.sync_api import sync_playwright

        captured: dict = {}
        passive: List[dict] = []
        urls = self.list_urls or [source_url]
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # 必须用真实浏览器 UA（与 PlaywrightAdapter.fetch 一致）：飞书 API 对默认 bot UA
            # 的 page.request 重放返回 405；真实 Chrome UA 才放行（站点 JS 生成的 _signature 同此 UA 上下文）。
            ctx = browser.new_context(
                user_agent=_UA,
                viewport={"width": 1366, "height": 900}, locale="zh-CN")
            page = ctx.new_page()

            def on_request(req):
                # 捕获列表页自己发的 posts POST（含 _signature query + offset/limit body），供重放。
                if self.intercept_match in req.url and req.method == "POST" and not captured:
                    try:
                        captured["url"] = req.url
                        captured["body"] = json.loads(req.post_data or "{}")
                    except Exception:
                        pass

            def on_response(resp):
                # 被动拦截兜底（与 PlaywrightAdapter.fetch 同口径）：捕获不到 POST 时仍有数据可用。
                try:
                    if self.intercept_match not in resp.url:
                        return
                    if "json" in (resp.headers or {}).get("content-type", "").lower():
                        passive.append(resp.json())
                except Exception:
                    pass

            page.on("request", on_request)
            page.on("response", on_response)
            for u in urls:
                try:
                    page.goto(u, wait_until="domcontentloaded", timeout=self.pw_timeout)
                    page.wait_for_timeout(self.wait_ms)
                except Exception:
                    continue
                if captured.get("url"):
                    break  # 首个列表页就抓到 POST，无需再开其它入口

            rows: List[dict] = []
            total = None
            if captured.get("url") and isinstance(captured.get("body"), dict):
                rows, total = self._replay_paginated(page, captured["url"], dict(captured["body"]))
            browser.close()

        if rows:
            # 浏览器抓全判定（与 httpx 同口径）：翻到 total 且未撞 _MAX_JOBS → complete，供 list-absence。
            self.fetch_complete = (total is not None and len(rows) >= (total or 0))
            # 合成下游同 shape 响应：parse() 走 posts_keys=data.job_post_list 抽取，逻辑不变。
            return json.dumps(
                {"_intercepted": [{"data": {"job_post_list": rows, "count": total or len(rows)}}]},
                ensure_ascii=False)
        if passive:  # 没捕获到 POST/重放为空 → 回退被动拦截链
            return json.dumps({"_intercepted": passive}, ensure_ascii=False)
        raise RuntimeError(
            f"{self.name}: anti_bot_blocked — 未捕获 posts POST 也无被动拦截 "
            f"(match={self.intercept_match})")

    def _replay_paginated(self, page, url: str, body: dict):
        """用站点 session 翻页重放 url（沿用其 _signature），limit=_PAGE_SIZE，收齐 data.count。
        返回 (rows, total)。任一步异常即停，已收的照常返回（不丢已拿到的岗位）。"""
        rows: List[dict] = []
        seen: set = set()
        total = None
        offset = 0
        hdrs = {"content-type": "application/json"}
        while len(rows) < self._MAX_JOBS:
            body["offset"] = offset
            body["limit"] = self._PAGE_SIZE
            try:
                r = page.request.post(url, data=json.dumps(body), headers=hdrs)
                jj = r.json()
            except Exception:
                break
            data = (jj or {}).get("data") if isinstance(jj, dict) else None
            if not isinstance(data, dict):
                break
            if total is None:
                total = data.get("count") or 0
            chunk = data.get("job_post_list") or []
            if not isinstance(chunk, list) or not chunk:
                break
            for post in chunk:
                pid = str((post or {}).get("id") or "")
                if pid and pid not in seen:
                    seen.add(pid)
                    rows.append(post)
            if total and len(rows) >= total:
                break
            if len(chunk) < self._PAGE_SIZE:  # 末页不足一页 → 收完
                break
            offset += self._PAGE_SIZE
        return rows, total

    def _map(self, post: dict) -> Optional[RawJob]:
        pid = str(post.get("id") or post.get("code") or "").strip()
        title = (post.get("title") or "").strip()
        if not pid or not title:
            return None

        city = ""
        ci = post.get("city_info")
        if isinstance(ci, dict):
            city = ci.get("name") or ""
        if not city:
            cl = post.get("city_list")
            if isinstance(cl, list) and cl and isinstance(cl[0], dict):
                city = cl[0].get("name") or ""

        job_type = ""
        jc = post.get("job_category")
        if isinstance(jc, dict):
            job_type = jc.get("name") or ""

        desc = (post.get("description") or "").strip()
        req = (post.get("requirement") or "").strip()
        summary = (desc + ("　【职位要求】" + req if req else "")).strip() or None
        jd_url = self.detail_template.format(id=pid)
        return RawJob(
            company=self.company_name, title=title, location=city or None,
            job_type=job_type or None, jd_url=jd_url, apply_url=jd_url,
            summary=summary, posted_at=normalizer.pick_publish_date(post),
        )


class FeishuGenericAdapter(FeishuRecruitAdapter):
    """飞书招聘**数据驱动**通用适配器（国内版 Workday）：host 从 source_url 动态解析，不再每家硬编码子类。
    一套覆盖所有用飞书招聘的公司（造车新势力 / 大量互联网与科技中企）。
    onboard = 加一行 sources，source_url 填该公司飞书招聘页（如 https://{tenant}.jobs.feishu.cn/index/position）。
    company 由 sources.company 兜底；岗位接口/字段/详情页格式复用 FeishuRecruitAdapter。"""
    name = "feishu"
    company_name = ""  # 由 sources.company 兜底

    def __init__(self):
        # 不在 init 固定 host —— 留到 fetch 时按 source_url 解析（见 _bind_host）。
        self.official_hosts = ()
        self.detail_template = ""
        self.list_urls = []

    def _bind_host(self, source_url: str):
        parsed = urlparse(source_url)
        host = parsed.netloc
        path = (parsed.path or "").strip("/")
        if path and path != "index/position":
            portal_base = "/" + path.split("/")[0]
        else:
            portal_base = "/index"
        self.official_hosts = (host,)
        self.detail_template = f"https://{host}{portal_base}/position/{{id}}/detail"
        standard_url = f"https://{host}/index/position"
        # 自定义 portal slug（如 /ponyai、/talent、/social）优先打开传入入口；标准入口保持原行为。
        if path and path != "index/position":
            self.list_urls = [f"https://{host}{portal_base}", standard_url]
        else:
            self.list_urls = [standard_url, source_url]
        return host

    def fetch(self, source_url: str) -> str:
        self._bind_host(source_url)
        return super().fetch(source_url)


class NioAdapter(FeishuRecruitAdapter):
    name = "nio_feishu"; company_name = "蔚来"; host = "nio.jobs.feishu.cn"


class XpengAdapter(FeishuRecruitAdapter):
    name = "xpeng_feishu"; company_name = "小鹏汽车"; host = "xiaopeng.jobs.feishu.cn"


class HorizonAdapter(FeishuRecruitAdapter):
    name = "horizon_feishu"; company_name = "地平线"; host = "horizon.jobs.feishu.cn"


class XiaomiAdapter(FeishuRecruitAdapter):
    name = "xiaomi_feishu"; company_name = "小米"; host = "xiaomi.jobs.f.mioffice.cn"

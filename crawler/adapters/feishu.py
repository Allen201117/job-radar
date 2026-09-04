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
import logging
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import httpx

import normalizer
from .base import DEFAULT_LIST_CAP, RawJob, RepetitionBrake, resolve_list_cap
from .playwright_base import PlaywrightAdapter, _UA

logger = logging.getLogger(__name__)


def _titles_of(rows):
    """喂给 RepetitionBrake 的标题序列；飞书 job_post 的标题恒在 `title`（见 _map）。"""
    return [str((r or {}).get("title") or "") for r in (rows or []) if isinstance(r, dict)]


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _should_continue(before, after, chunk, total, page_size):
    """还该不该翻下一页。

    ⚠️ 末页判据**不能**用「本页条数 < pageSize」：站点限流/抖动时会回短页，一个瞬时短页就把
    整源停在半路（同一条在 beisen 上实测把中国交建从 2565 掐到 800）。改用「这一页有没有带来
    新岗位」（before/after 是去重后的行数）；只有在没有分母可判时才退回短页当自然末页。"""
    if after <= before:
        return False
    if total:
        return True
    return len(chunk) >= page_size


class FeishuRecruitAdapter(PlaywrightAdapter):
    """飞书招聘门户通用层。

    ## 子门户（website_path）—— 校招/实习岗藏在这里，2026-09-04 才挖出来
    同一个租户可以挂多个门户，**用哪个门户由请求头 `website-path` 决定**，与 URL 路径同名：
      · 不带该头（主门户）= 社招全集      · `campus` = 校园招聘
      · `internship` = 实习              · `newretailing` 等 = 租户自定义专项
    小米实测：不带 1894 / campus 764 / internship 554 / newretailing 121，四个池子互不相同。

    ⚠️ 此前判「飞书私有部署没有校招板块」是**错的**，错在试错了维度：当时对比的是
    `storefront_id` 两个取值（返回完全相同的 1887 条），而真正的开关是这个请求头。
    ⚠️ `portal_type` 也不是开关：带 `website-path: campus` 时传 2 或 6 都返回同一批 764 条。
    ⚠️ **`website-path: index` 不等于「主门户」**，它是个更小的子集（蔚来 2055 → 1801），
       所以 `_bind_website_path` 把 index 当成「没有子门户」。

    新增一个租户的校招源**不需要写代码**：插一条 source_url 指向 `https://{host}/campus/position`
    的 sources 行即可，本类按路径自动切门户、切详情模板。
    """

    host = ""  # 子类设置，如 nio.jobs.feishu.cn
    website_path = ""  # 由 source_url 派生；""=主门户（社招）
    intercept_match = "/api/v1/search/job/posts"
    posts_keys = ("data.job_post_list", "job_post_list")
    _PAGE_SIZE = 50    # 单页拉取数（接口实测 limit=50 稳定返回，远超站点默认 10）
    # 单租户抓取条数上限（env CRAWL_MAX_JOBS 可整体调档）。旧的 600 硬顶让蔚来(2055)/小鹏(1552)/
    # 哪吒(1127)/智元(904)/安克(848)/物美(785)/理想(754) 每轮都只抓到前 600 条
    # （2026-09-04 crawl_runs 实测），且这七家全部 ≤8000，抬档一次就能抓全。
    _MAX_JOBS = DEFAULT_LIST_CAP
    _HTTPX_TIMEOUT = 20

    # list-absence 探活：feishu posts API 返**全量在招岗**（非夹带已关闭岗），且本类按 count 翻全；
    # 故抓全时「上次在、这次没了」可判下架。仅 fetch_complete=True 时生效（见 run.py 兜底）。
    supports_absence_liveness = True
    fetch_complete = False  # 每次 fetch 末尾置位：是否抓到完整列表（翻到 count、未撞 _MAX_JOBS 上限）

    def __init__(self):
        self.official_hosts = (self.host,)
        self.website_path = ""
        self._apply_website_path("")
        self.fetch_complete = False
        self.reported_total = None
        self._prefetched = None

    def _apply_website_path(self, path: str) -> None:
        """按子门户重算详情模板与入口页。path="" = 主门户（社招），走 /index/…（历史行为不变）。

        ⚠️ host 必须从 **official_hosts 优先** 取：`FeishuGenericAdapter` 的 host 是空串、
        真实 host 由 `_bind_host` 放进 official_hosts。早先这里直接用 self.host，结果把它
        `_bind_host` 刚算好的 detail_template 覆写成 `https:///index/position/{id}/detail`
        → jd_url 全废 → 68 个通用飞书源**解析出 0 岗却仍标 fetch_complete=True**
        （2026-09-04 实测拓竹 reported=165/parsed=0）。这正是 CLAUDE.md 立碑的
        「0 岗 + 自称抓全」组合，回归测试见 test_feishu_httpx.WebsitePathTest。
        """
        self.website_path = path or ""
        host = (self.official_hosts[0] if getattr(self, "official_hosts", None) else "") or self.host
        if not host:
            return   # host 还没绑定（通用类的 __init__ 阶段）→ 什么都别改，等 _bind_host 之后再来
        prefix = path or "index"
        self.detail_template = f"https://{host}/{prefix}/position/{{id}}/detail"
        self.list_urls = [
            f"https://{host}/{prefix}/position",
            f"https://{host}/",
        ]

    def _bind_website_path(self, source_url: str) -> None:
        """从 source_url 的首个路径段派生子门户（见 website_path 的类注释）。

        ⚠️ **`index` 必须当成「没有子门户」**：飞书的主门户带 `website-path: index` 反而是
        *子集* —— 2026-09-04 实测蔚来不带该头 2055 岗、带 index 只有 1801 岗（少 254 个）。
        库里 70 个存量飞书源全是 `/index/position`，一旦把 index 也派生出去就是**全体缩水**。
        """
        segments = [seg for seg in (urlparse(source_url).path or "").split("/") if seg]
        first = segments[0] if segments else ""
        self._apply_website_path("" if first in ("", "index", "position") else first)

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
        prefix = self.website_path or "index"
        headers = {"User-Agent": _UA, "Accept-Language": "zh-CN,en;q=0.9",
                   "Content-Type": "application/json",
                   "portal-channel": "saas-career", "portal-platform": "pc",
                   "Referer": f"https://{host}/{prefix}/position"}
        if self.website_path:
            # 只有子门户才带这个头。主门户带 `website-path: index` 会拿到更小的子集（见类注释）。
            headers["website-path"] = self.website_path
        try:
            with httpx.Client(timeout=self._HTTPX_TIMEOUT, follow_redirects=True, headers=headers) as cli:
                cap = resolve_list_cap(self._MAX_JOBS)
                brake = RepetitionBrake()
                while len(rows) < cap:
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
                    before = len(rows)
                    for post in chunk:
                        pid = str((post or {}).get("id") or "")
                        if pid and pid not in seen:
                            seen.add(pid)
                            rows.append(post)
                    if total and len(rows) >= total:
                        break
                    # 重复度刹车：批量发布源（同一个岗 × N 家门店）翻再多页也只是同质副本。
                    # 放在「抓全」判定之后 → 能抓全的源一律抓全。刹停 → fetch_complete 天然为 False。
                    if brake.observe(_titles_of(rows[before:])):
                        logger.info("%s: 重复度刹车 —— 连续 %d 条没有新角色，停在 %d/%s 条 host=%s",
                                    self.name, brake.stall_rows, len(rows), total, host)
                        break
                    if not _should_continue(before, len(rows), chunk, total, self._PAGE_SIZE):
                        break
                    offset += self._PAGE_SIZE
        except Exception:
            return rows, total, reached
        return rows, total, reached

    def _detail_portal_closed(self, host: str, post: dict) -> bool:
        """只抽一岗确认租户详情门户；请求异常一律放行，避免误杀。"""
        pid = str((post or {}).get("id") or (post or {}).get("code") or "").strip()
        if not pid:
            return False
        try:
            response = httpx.get(
                self.detail_template.format(id=pid),
                timeout=self._HTTPX_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _UA,
                         "Referer": f"https://{host}/{self.website_path or 'index'}/position"},
            )
            return response.status_code in (404, 410)
        except Exception:
            return False

    def should_skip(self, source_url: str) -> Optional[str]:
        """租户详情门户关闭时整源跳过；列表 API 仍吐岗不足以证明可投。"""
        if not getattr(self, "host", "") and hasattr(self, "_bind_host"):
            self._bind_host(source_url)
        self._bind_website_path(source_url)
        host = self._resolve_host(source_url)
        if not host:
            return None
        rows, total, reached = self._httpx_fetch(host)
        if not reached:
            return None
        self._prefetched = (rows, total, reached)
        if rows and self._detail_portal_closed(host, rows[0]):
            return "feishu tenant detail portal closed (404/Not Found); skip source to avoid unusable jd_url"
        return None

    def fetch(self, source_url: str) -> str:
        """httpx-first：冷启动直拉 posts API（无浏览器，daily-crawl 4×/天可跑）；httpx 未打通才回退
        浏览器抓包链（仅 Playwright 可用环境如 enrich-crawl）。"""
        self.fetch_complete = False
        self.reported_total = None
        prefetched = self._prefetched
        self._prefetched = None
        self._bind_website_path(source_url)
        host = self._resolve_host(source_url)
        if host:
            rows, total, reached = prefetched or self._httpx_fetch(host)
            if reached:
                # httpx 打通（含真 0 岗）→ 直接用，不再开浏览器。complete=翻全（含 0 岗）。
                self.reported_total = _int_or_none(total)
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
            self.reported_total = _int_or_none(total)
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
        cap = resolve_list_cap(self._MAX_JOBS)
        brake = RepetitionBrake()
        while len(rows) < cap:
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
            before = len(rows)
            for post in chunk:
                pid = str((post or {}).get("id") or "")
                if pid and pid not in seen:
                    seen.add(pid)
                    rows.append(post)
            if total and len(rows) >= total:
                break
            if brake.observe(_titles_of(rows[before:])):   # 与 httpx 路径同口径，见那边注释
                logger.info("%s: 重复度刹车 —— 连续 %d 条没有新角色，停在 %d/%s 条 url=%s",
                            self.name, brake.stall_rows, len(rows), total, url)
                break
            if not _should_continue(before, len(rows), chunk, total, self._PAGE_SIZE):
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
        self._prefetched = None

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
    # 原来这里单独覆写 _MAX_JOBS=3000「抓全小米的 ~2030 岗」。那是给一家公司打的补丁，
    # 别的租户照样卡在 600 —— 直到 2026-09-04 才量出来还有 32 个源在漏 9 万个岗。
    # 现在基类基准档就是 3000、必投公司自动抬到 8000，这条补丁不再需要（留碑不留码）。

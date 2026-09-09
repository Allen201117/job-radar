"""京东校园招聘（campus.jd.com）浏览器拦截 adapter。"""
import json
from typing import List, Optional

import httpx

import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter, _UA


# ⚠️ 京东用的是 **totalNumber**，不是 total/totalCount/count —— 少了它 reported_total 恒为
# None，「抓全自检」就永远判不出是否收齐（第一版实测 total=None / complete=False）。
_TOTAL_KEYS = ("totalNumber", "total", "totalCount", "count")


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class JdCampusAdapter(PlaywrightAdapter):
    """只抓 campus.jd.com 的校招/实习/专项岗位，不和 zhaopin.jd.com 社招 adapter 混用。

    ## 三个渠道（2026-09-09 live 实测，同一 SPA 用 `#/jobs?type=` 区分）
    - `present`    应届生（原有渠道），live totalNumber=126。
    - `internship` 实习生，官网自报 totalNumber=101。⚠️ 不是页面上「实习生」筛选 tab
      （那个 tab 是 present 渠道内部按 planId 过滤的子集，与本渠道数据不同）；
      真正的渠道切换是导航到 `#/jobs?type=internship`——SPA 自己的路由会据此改发
      `POST /api/wx/position/page?type=internship`，纯页面自身行为，不是手动重放请求。
    - `talent`     TGT 专项（顶尖青年技术天才计划），live totalNumber=123。
      官网 `#/talentProject` 页原话：「价值观匹配…有机会优先向**应届生校招项目
      （JDS/TET/TGT）**转化」——TGT 与 JDS/TET 并列，官方明确把它归为应届生校招项目，
      不是社招，故予接入。该渠道内部混有两条子轨（岗位自带 `jobDirection` 字段区分）：
      `TGT`（应届全职，样本 55 条）与 `TGT实习生`（实习，样本 68 条，55+68=123 对得上）；
      `_map` 按这个字段逐条定 job_type，不按渠道整体一刀切。
    ⚠️ 三渠道 live 逐条比对 publishId 全集，**零重叠**（126/101/123 各自独立，并集 350）——
    与「实习生」筛选 tab 的巧合重名容易让人误以为渠道之间有重叠，实测没有，可放心加总判抓全。
    """

    name = "jd_campus"
    company_name = "京东"
    official_hosts = ("campus.jd.com",)
    list_urls = [
        "https://campus.jd.com/#/jobs?type=present",
        "https://campus.jd.com/#/jobs?type=internship",
        "https://campus.jd.com/#/jobs?type=talent",
    ]
    # 渠道定义：(type 参数, 列表 URL, 该渠道除个别岗位外的默认 job_type)。
    # talent 渠道的默认值会被 _map 按单条 jobDirection 覆写（见类注释）。
    _CHANNELS = (
        ("present", "https://campus.jd.com/#/jobs?type=present", "校园招聘"),
        ("internship", "https://campus.jd.com/#/jobs?type=internship", "实习"),
        ("talent", "https://campus.jd.com/#/jobs?type=talent", "校园招聘"),
    )
    intercept_match = "/api/wx/position/page?type=present"  # 向后兼容旧引用；实际拦截逐渠道生成
    # live 2026-09-03 实测：响应形如 {"success":true,"body":{"totalNumber":126,"items":[…],"pageCount":0}}
    # ⚠️ 是 body.items，不是 body.list / body.records（后两者是常见猜法，这站都不是）。
    posts_keys = ("body.items",) + PlaywrightAdapter.posts_keys
    wait_ms = 8000
    max_pages = 30  # live 2026-09-03 单渠道最多 13 页；留增长余量，防止站点分页异常无限点。

    _DICT_API = "https://campus.jd.com/api/wx/position/dict?type=present"
    _PROJECT_API = "https://campus.jd.com/api/wx/position/getProjectList"

    def should_skip(self, source_url: str) -> Optional[str]:
        """用免登录配套接口做轻量探活；网络异常不把可用校园源误判为停用。"""
        headers = {
            "User-Agent": _UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://campus.jd.com/#/jobs",
        }
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
                dictionary = client.post(self._DICT_API)
                projects = client.get(self._PROJECT_API)
                dictionary.raise_for_status()
                projects.raise_for_status()
                dict_body = dictionary.json()
                project_body = projects.json()
        except (httpx.HTTPError, ValueError):
            # 探活仅是提前发现整源不可用的优化；真正列表抓取仍交浏览器给出可观测的 failed。
            return None
        if not isinstance(dict_body, dict) or not isinstance(project_body, dict):
            return "jd_campus: campus probe returned non-JSON payload"
        if dict_body.get("success") is False or project_body.get("success") is False:
            return "jd_campus: campus probe reported unsuccessful response"
        return None

    def fetch(self, source_url: str) -> str:
        """逐渠道导航 `#/jobs?type=…`，拦截该渠道自己发出的列表 POST，点站内分页直到收齐
        该渠道官网自报总数；三个渠道各自判断「是否抓全」，全部为真才整体 fetch_complete=True
        （与 huawei_campus / xiaohongshu 同口径，不拿渠道总数之和当分母——三渠道 publishId
        live 实测互不重叠，加总是安全的，见类注释）。

        ⚠️ 该接口用 httpx/curl 会被风控替换为 JDOA Message Alert XHTML；不可在此自行重放
        POST。只能加载公开 SPA、导航到对应渠道的 `#/jobs?type=…`，让站点自己的路由与 JS
        发请求，再读取浏览器响应。
        ⚠️ 不能以「本页条数小于 pageSize」判末页：该站会忽略 pageSize，第一页就可能误停。
        只以「本页没有带来新 publishId」或「已收齐该渠道接口自报总数」停止翻页。
        ⚠️ 每条岗位在收集时打上 `_channel` 标记（渠道名），供 `_map` 决定 job_type——
        present/internship 渠道整体定死，talent 渠道再按单条 `jobDirection` 精修。
        ⚠️ 三个渠道的列表 URL 只有 `#` 后面的 query 不同（同一个 `#/jobs` 路径），浏览器对这种
        「同文档导航」的 `goto` **不会重新渲染**、SPA 也不会重新发起列表请求——第一版实测切到
        internship/talent 渠道时 `on_response` 一次都没触发，两个渠道各拿到 0 条（CLAUDE.md
        「hash 路由必须 reload()」那条碑说的正是这个坑）。修法＝换渠道时若与上一个 URL 同路径，
        `goto` 之后必须再 `reload()` 一次，让 SPA 重新跑一遍其路由初始化逻辑、重新发请求。
        """
        from playwright.sync_api import sync_playwright

        self.reported_total = None
        self.fetch_complete = False
        all_responses: List[dict] = []
        totals: List[int] = []
        drained: List[bool] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=_UA, viewport={"width": 1366, "height": 900}, locale="zh-CN"
            )
            page = ctx.new_page()
            previous_url: Optional[str] = None
            try:
                for ptype, url, _default_job_type in self._CHANNELS:
                    match = f"/api/wx/position/page?type={ptype}"
                    channel_responses: List[dict] = []
                    seen_ids = set()

                    def on_response(response, _match=match, _bucket=channel_responses):
                        try:
                            if _match not in response.url:
                                return
                            if "json" not in (response.headers or {}).get("content-type", "").lower():
                                return
                            _bucket.append(response.json())
                        except Exception:
                            # 单个响应解析失败不影响后续页；本渠道最终一条都没有会体现在
                            # drained=False，不会被静默吞掉。
                            return

                    page.on("response", on_response)
                    try:
                        same_document = (
                            previous_url is not None
                            and previous_url.split("#", 1)[0] == url.split("#", 1)[0]
                        )
                        page.goto(url, wait_until="domcontentloaded", timeout=self.pw_timeout)
                        if same_document:
                            # 只改 hash 的 goto 不重新渲染/不重新发请求，必须 reload 一次。
                            page.reload(wait_until="domcontentloaded", timeout=self.pw_timeout)
                        previous_url = url
                        self._await_list_capture(page, channel_responses, (match,))
                        channel_total = self._tag_and_collect(channel_responses, seen_ids, ptype)

                        for _ in range(max(0, self.max_pages - 1)):
                            if channel_total is not None and len(seen_ids) >= channel_total:
                                break
                            before = len(seen_ids)
                            if not self._click_next_page(page):
                                break
                            self._await_list_capture(page, channel_responses, (match,))
                            channel_total = self._tag_and_collect(channel_responses, seen_ids, ptype)
                            if len(seen_ids) == before:
                                break
                    finally:
                        page.remove_listener("response", on_response)

                    all_responses.extend(channel_responses)
                    if channel_total is not None:
                        totals.append(channel_total)
                        drained.append(len(seen_ids) >= channel_total)
                    else:
                        drained.append(False)  # 连总数都没拿到 → 本渠道不算抓全
            finally:
                browser.close()

        if not all_responses:
            raise RuntimeError(
                "jd_campus: anti_bot_blocked — 三个渠道均未从页面列表响应捕获任何岗位"
            )
        if len(totals) == len(self._CHANNELS):
            self.reported_total = sum(totals)
        self.fetch_complete = len(drained) == len(self._CHANNELS) and all(drained)
        return json.dumps({"_intercepted": all_responses}, ensure_ascii=False)

    def _tag_and_collect(self, responses: List[dict], seen_ids: set, ptype: str) -> Optional[int]:
        """给本渠道已捕获的响应里每条岗位打上 `_channel`，收集 publishId，返回该渠道自报总数。"""
        total: Optional[int] = None
        for response in responses:
            t = self._reported_total_from_response(response)
            if t is not None and total is None:
                total = t
            for position in self._extract_posts(response):
                if not isinstance(position, dict):
                    continue
                position["_channel"] = ptype
                publish_id = str(position.get("publishId") or "").strip()
                if publish_id:
                    seen_ids.add(publish_id)
        return total

    def _click_next_page(self, page) -> bool:
        """点页面原生的「下一页」，让 SPA 自己携带风控所需上下文发下一页 POST。"""
        for selector in (
            'li[title="下一页"]',
            ".ant-pagination-next:not(.ant-pagination-disabled)",
            '[class*="next"]:not([class*="disabled"])',
            "text=下一页",
        ):
            try:
                button = page.locator(selector).first
                if button.count() == 0 or not button.is_enabled():
                    continue
                classes = button.get_attribute("class") or ""
                if "disabled" in classes:
                    continue
                button.click(timeout=5000)
                return True
            except Exception:
                continue
        return False

    @staticmethod
    def _reported_total_from_response(response: dict) -> Optional[int]:
        """从列表响应的外层逐层找官网自报总数，避免把某个岗位字段当分母。"""
        current = response
        for key in ("body", "data", "result"):
            if not isinstance(current, dict):
                break
            for total_key in _TOTAL_KEYS:
                total = _int_or_none(current.get(total_key))
                if total is not None:
                    return total
            current = current.get(key)
        if isinstance(current, dict):
            for total_key in _TOTAL_KEYS:
                total = _int_or_none(current.get(total_key))
                if total is not None:
                    return total
        return None

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        publish_id = str(post.get("publishId") or "").strip()
        title = str(post.get("positionName") or "").strip()
        # ⚠️ publishId 是官网详情页唯一主键；缺它绝不拼半截 jd_url 入库。
        if not (publish_id and title):
            return None
        # ⚠️ 顶层 workCity 恒为 None；真正的工作地点在 requirementVoList[].workCity
        # （一个岗位常对应几十条需求、分布在多城市 + 多事业群）。live 实测「市场营销」一岗
        # 有 31 条需求。只取顶层字段会让所有岗位的城市都是空的（第一版就是这样）。
        cities, bgs = [], []
        for req in (post.get("requirementVoList") or []):
            if not isinstance(req, dict):
                continue
            city = str(req.get("workCity") or "").strip()
            if city and city not in cities:
                cities.append(city)
            bg = str(req.get("positionBg") or "").strip()
            if bg and bg not in bgs:
                bgs.append(bg)
        location = cities[0] if cities else None

        bits = []
        if len(cities) > 1:
            bits.append("工作地点：" + "、".join(cities))
        if bgs:
            bits.append("所属业务：" + "、".join(bgs))
        direction = str(post.get("jobDirection") or "").strip()
        category = str(post.get("jobCategory") or "").strip()
        if direction or category:
            bits.append("职位方向：" + " / ".join(x for x in (direction, category) if x))
        # workContent=工作内容、qualification=任职资格，都是列表接口直接给的全文，无需逐岗富化。
        for key, label in (("workContent", "工作内容"), ("qualification", "任职资格")):
            val = str(post.get(key) or "").strip()
            if val:
                bits.append(f"【{label}】\n{val}")
        jd_url = f"https://campus.jd.com/#/details?id={publish_id}"
        # job_type：internship 渠道整体是实习；talent 渠道内部按单条 jobDirection 精修
        # （TGT实习生=实习，TGT=校园招聘）；present 及其余情况默认校园招聘。
        # 见类注释：三渠道 live 实测互不重叠，_channel 缺失只会发生在单测直接构造 post 时。
        channel = post.get("_channel")
        job_type = "实习" if (channel == "internship" or direction == "TGT实习生") else "校园招聘"
        return RawJob(
            company=self.company_name,
            title=title,
            location=location,
            job_type=job_type,
            summary="\n\n".join(bits).strip() or None,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )

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
    """只抓 campus.jd.com 的校招/实习岗位，不和 zhaopin.jd.com 社招 adapter 混用。"""

    name = "jd_campus"
    company_name = "京东"
    official_hosts = ("campus.jd.com",)
    list_urls = ["https://campus.jd.com/#/jobs"]
    intercept_match = "/api/wx/position/page?type=present"
    # live 2026-09-03 实测：响应形如 {"success":true,"body":{"totalNumber":126,"items":[…],"pageCount":0}}
    # ⚠️ 是 body.items，不是 body.list / body.records（后两者是常见猜法，这站都不是）。
    posts_keys = ("body.items",) + PlaywrightAdapter.posts_keys
    wait_ms = 8000
    max_pages = 30  # live 2026-09-03 为 13 页；留增长余量，防止站点分页异常无限点。

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
        """拦截页面自己发出的列表 POST，并逐页点击站内分页直到收齐官网总数。

        ⚠️ 该接口用 httpx/curl 会被风控替换为 JDOA Message Alert XHTML；不可在此自行重放
        POST。只能加载公开 SPA，让站点自己的 JS 发请求，再读取浏览器响应。
        ⚠️ 不能以「本页条数小于 pageSize」判末页：该站会忽略 pageSize，第一页就可能误停。
        只以「本页没有带来新 publishId」或「已收齐接口自报总数」停止翻页。
        """
        from playwright.sync_api import sync_playwright

        self.reported_total = None
        self.fetch_complete = False
        captured: List[dict] = []
        seen_ids = set()

        def collect_positions() -> None:
            nonlocal seen_ids
            for response in captured:
                total = self._reported_total_from_response(response)
                if total is not None and self.reported_total is None:
                    self.reported_total = total
                for position in self._extract_posts(response):
                    publish_id = str((position or {}).get("publishId") or "").strip()
                    if publish_id:
                        seen_ids.add(publish_id)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=_UA, viewport={"width": 1366, "height": 900}, locale="zh-CN"
            )
            page = ctx.new_page()

            def on_response(response):
                try:
                    if self.intercept_match not in response.url:
                        return
                    if "json" not in (response.headers or {}).get("content-type", "").lower():
                        return
                    captured.append(response.json())
                except Exception:
                    # 单个响应解析失败不影响后续页；最终没有任何岗位仍会明确抛错。
                    return

            page.on("response", on_response)
            try:
                page.goto(self.list_urls[0], wait_until="domcontentloaded", timeout=self.pw_timeout)
                self._await_list_capture(page, captured, (self.intercept_match,))
                collect_positions()

                for _ in range(max(0, self.max_pages - 1)):
                    if self.reported_total is not None and len(seen_ids) >= self.reported_total:
                        self.fetch_complete = True
                        break
                    before = len(seen_ids)
                    if not self._click_next_page(page):
                        break
                    self._await_list_capture(page, captured, (self.intercept_match,))
                    collect_positions()
                    if len(seen_ids) == before:
                        break
                else:
                    # 撞安全上限时不自称抓全，保留已抓响应让上层记录 partial。
                    self.fetch_complete = False
            finally:
                browser.close()

        if not seen_ids:
            raise RuntimeError(
                "jd_campus: anti_bot_blocked — 未从页面列表响应捕获任何带 publishId 的岗位"
            )
        self.fetch_complete = self.fetch_complete or (
            self.reported_total is not None and len(seen_ids) >= self.reported_total
        )
        return json.dumps({"_intercepted": captured}, ensure_ascii=False)

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
        return RawJob(
            company=self.company_name,
            title=title,
            location=location,
            job_type="校园招聘",
            summary="\n\n".join(bits).strip() or None,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )

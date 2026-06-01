"""
SPA 招聘站通用浏览器抓取层（Tier-2）。

思路（合规）：用真实无头浏览器加载官方招聘**公开页** → 站点自有 JS 自己签名调用其官方岗位接口
→ 我们**拦截该接口响应**拿到真实 title/id/城市 → 用详情 URL 模板拼 jd_url → RawJob。
不破解签名、不调私有接口、低频。

子类只需配置：list_urls / intercept_match / posts_keys / detail_template / official_hosts，并实现 _map()。
playwright 仅在 fetch() 内惰性导入——未跑 fetch 的单元测试无需安装 playwright。
"""
import json
from typing import List, Optional

from .base import BaseAdapter, RawJob

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class PlaywrightAdapter(BaseAdapter):
    name = "playwright_base"

    # ---- 子类配置 ----
    company_name: str = ""
    list_urls: List[str] = []
    intercept_match: str = ""           # 要拦截的接口 URL 子串
    posts_keys = ("data.job_post_list", "data.posts", "data.list", "job_post_list", "posts", "list")
    detail_template: str = ""           # 含 {id}
    official_hosts: tuple = ()
    wait_ms: int = 6000
    pw_timeout: int = 45000

    def should_skip(self, source_url: str) -> Optional[str]:
        # SPA 站 HEAD 检查无意义（首页永远 200），交给浏览器渲染判定，跳过 httpx HEAD。
        return None

    def fetch(self, source_url: str) -> str:
        """启动无头浏览器，遍历 list_urls，拦截官方岗位接口响应，返回汇总 JSON 文本。"""
        from playwright.sync_api import sync_playwright

        collected: List[dict] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=_UA, viewport={"width": 1366, "height": 900}, locale="zh-CN"
            )
            page = ctx.new_page()

            def on_response(resp):
                try:
                    if self.intercept_match and self.intercept_match in resp.url:
                        ct = (resp.headers or {}).get("content-type", "").lower()
                        if "json" in ct:
                            collected.append(resp.json())
                except Exception:
                    pass

            page.on("response", on_response)

            urls = self.list_urls or [source_url]
            for u in urls:
                try:
                    page.goto(u, wait_until="domcontentloaded", timeout=self.pw_timeout)
                    page.wait_for_timeout(self.wait_ms)
                except Exception:
                    continue
            browser.close()

        if not collected:
            # 一条接口都没拦到 → 多半被反爬识别或站点改版；交给 run.py 记为 partial（不伪装成功）
            raise RuntimeError(
                f"{self.name}: anti_bot_blocked — 未拦截到任何 '{self.intercept_match}' 接口响应"
            )
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        responses = (data or {}).get("_intercepted") or []
        jobs: List[RawJob] = []
        seen = set()
        for resp in responses:
            for post in self._extract_posts(resp):
                job = self._map(post)
                if job and job.title and job.jd_url and self._host_ok(job.jd_url) and job.jd_url not in seen:
                    seen.add(job.jd_url)
                    jobs.append(job)
        return jobs

    # ---- helpers ----
    def _extract_posts(self, resp) -> list:
        for key in self.posts_keys:
            cur = resp
            ok = True
            for part in key.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, list):
                return cur
        return []

    def _host_ok(self, jd_url: str) -> bool:
        if not self.official_hosts:
            return True
        return any(h in jd_url for h in self.official_hosts)

    def _map(self, post: dict) -> Optional[RawJob]:
        raise NotImplementedError

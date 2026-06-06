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

# 岗位行常见的「标题」字段名，用于在未知 JSON 结构里识别岗位列表。
_TITLE_KEYS = ("title", "name", "jobTitle", "positionName", "job_title",
               "position_name", "jobName", "postName", "JobAdName")


def _deep_find_job_list(obj, depth: int = 0) -> list:
    """深搜响应，返回最大的「元素是 dict 且多数含标题字段」的列表（通用站点兜底）。"""
    if depth > 6:
        return []
    best: list = []
    if isinstance(obj, list):
        dicts = [x for x in obj if isinstance(x, dict)]
        if dicts and sum(any(k in d for k in _TITLE_KEYS) for d in dicts) >= max(1, len(dicts) // 2):
            best = obj
        for x in obj:
            cand = _deep_find_job_list(x, depth + 1)
            if len(cand) > len(best):
                best = cand
    elif isinstance(obj, dict):
        for v in obj.values():
            cand = _deep_find_job_list(v, depth + 1)
            if len(cand) > len(best):
                best = cand
    return best


class PlaywrightAdapter(BaseAdapter):
    name = "playwright_base"

    # ---- 子类配置 ----
    company_name: str = ""
    list_urls: List[str] = []
    intercept_match: str = ""           # 要拦截的接口 URL 单个子串（向后兼容）
    intercept_matches: tuple = ()       # 多个候选子串（任一命中即拦截）；两者皆空 = 拦截所有 JSON
    posts_keys = ("data.job_post_list", "data.posts", "data.list", "data.data.list",
                  "data.items", "data.records", "data.rows", "data.content",
                  "job_post_list", "posts", "list", "items", "records", "rows", "data",
                  "Data", "Data.Posts", "Data.List", "Data.Rows")  # 北森 GetJobAdPageList: 顶层 Data 列表
    detail_template: str = ""           # 含 {id}
    official_hosts: tuple = ()
    wait_ms: int = 6000
    pw_timeout: int = 45000
    max_pages: int = 4

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

            matchers = self.intercept_matches or (
                (self.intercept_match,) if self.intercept_match else ()
            )

            def on_response(resp):
                try:
                    # 两者皆空 = 拦截所有 JSON 响应（通用站点）；否则任一子串命中即拦截。
                    if matchers and not any(m in resp.url for m in matchers):
                        return
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
                    self._paginate(page)
                except Exception:
                    continue
            browser.close()

        if not collected:
            # 一条接口都没拦到 → 多半被反爬识别或站点改版；交给 run.py 记为 partial（不伪装成功）
            raise RuntimeError(
                f"{self.name}: anti_bot_blocked — 未拦截到任何岗位接口 JSON 响应 "
                f"(matchers={matchers or 'ALL_JSON'})"
            )
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    def _paginate(self, page):
        """翻页/滚动以触发更多接口分页响应（被 on_response 持续拦截）。低频、有上限。"""
        for _ in range(max(0, self.max_pages - 1)):
            clicked = False
            for sel in ('li[title="下一页"]', "text=下一页",
                        ".ant-pagination-next:not(.ant-pagination-disabled)",
                        '[class*="next"]:not([class*="disabled"])'):
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_enabled():
                        btn.click(timeout=2500)
                        page.wait_for_timeout(2500)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                try:
                    page.mouse.wheel(0, 5000)
                    page.wait_for_timeout(2000)
                except Exception:
                    break

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
        # 兜底（通用站点未知结构）：深搜响应里「最像岗位列表」的 dict 数组。
        return _deep_find_job_list(resp)

    def _host_ok(self, jd_url: str) -> bool:
        if not self.official_hosts:
            return True
        return any(h in jd_url for h in self.official_hosts)

    def _map(self, post: dict) -> Optional[RawJob]:
        raise NotImplementedError

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

import platform_fingerprint

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


def _nav_evidence(records):
    """导航证据只留判因需要的字段——**整页 HTML 绝不进台账**（体积 + 噪音）。"""
    return [
        {
            key: record.get(key)
            for key in ("url", "final_url", "status", "error")
            if record.get(key) is not None
        }
        for record in (records or [])[:4]
    ]


class InterceptFailure(RuntimeError):
    """浏览器道一个岗位接口都没拦到 —— 把**为什么**带出去，别让调用方对着字符串猜。

    block_kind：
      · ``anti_bot``              对方真的拒了我们（403/412/503，或 WAF/验证码厂商的挑战页）
      · ``no_job_data_on_entry``  页面正常打开，但这一页就是没有岗位数据（多半站错了页）
      · ``entry_unreachable``     页面压根没打开（导航全部失败）

    ``hops`` 只在 no_job_data_on_entry 时有值：从**渲染后**的页面里抽出的自家招聘子域候选，
    供 gap_funnel_browser 跟下一跳（httpx 道靠原始 HTML 抽不到 SPA 壳里的链接，这半只能在这里做）。
    """

    def __init__(self, message, *, block_kind, hops=(), evidence=None):
        super().__init__(message)
        self.block_kind = block_kind
        self.hops = list(hops or ())
        self.evidence = dict(evidence or {})


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
    wait_ms: int = 6000              # 等待列表接口响应的上限（智能等待命中后提前返回，绝不超此值）
    quiet_after_capture_ms: int = 1800  # 命中拦截后需连续静默这么久才算「列表加载停当」（兜住紧随的二次 XHR）
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
            navigations = []
            for u in urls:
                record = {"url": u}
                try:
                    response = page.goto(
                        u, wait_until="domcontentloaded", timeout=self.pw_timeout
                    )
                    record["status"] = (
                        int(getattr(response, "status", 0) or 0) if response else None
                    )
                    self._await_list_capture(page, collected, matchers)
                    self._paginate(page)
                except Exception as exc:
                    record["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
                # 只有「一个岗位接口都没拦到」时才多花一次 content()/url 去取判因证据，
                # 正常路径零额外开销。
                if not collected:
                    try:
                        record["final_url"] = page.url
                        record["html"] = page.content()
                    except Exception:
                        pass
                navigations.append(record)
            browser.close()

        if not collected:
            raise self.classify_empty_capture(navigations, matchers)
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    @classmethod
    def classify_empty_capture(cls, navigations, matchers=()):
        """一个岗位接口都没拦到 —— 判因并返回待抛的 InterceptFailure（纯函数，可单测）。

        ⚠️ 这里以前**一律**记 `anti_bot_blocked`。那是把我们自己的判断失误说成对方的行为：
        2026-09-04 台账里 21 家必投公司因此被标「被反爬」，逐个核查后无一被拒——
        漏斗只是停在「公司官网的招聘介绍页」上，而那种页面本来就没有岗位数据
        （巴斯夫、壳牌各空撞 30 次，排查方向被带去研究怎么绕反爬）。
        2026-09-05 复测其中 8 家入口：全部 HTTP 200、零拦截信号。
        判「是否真被拒」的唯一判据在 platform_fingerprint.detect_block_signal，两道共用。
        """
        records = list(navigations or [])
        opened = [
            record for record in records
            if record.get("status") is not None or record.get("html")
        ]
        matcher_text = "matchers=%s" % (tuple(matchers) if matchers else "ALL_JSON")
        if not opened:
            errors = "; ".join(
                str(record.get("error") or "no_response") for record in records[:3]
            ) or "no_navigation"
            return InterceptFailure(
                f"{cls.name}: entry_unreachable — 入口页没能打开（{errors}）",
                block_kind="entry_unreachable",
                evidence={"navigations": _nav_evidence(records)},
            )
        for record in opened:
            if platform_fingerprint.detect_block_signal(
                record.get("status"), record.get("html") or ""
            ):
                return InterceptFailure(
                    f"{cls.name}: anti_bot_blocked — 对方拒绝访问"
                    f"（HTTP {record.get('status')}），未拦截到任何岗位接口 JSON "
                    f"({matcher_text})",
                    block_kind="anti_bot",
                    evidence={"navigations": _nav_evidence(records)},
                )
        hops = []
        for record in opened:
            for hop in platform_fingerprint.find_careers_subdomain_hops(
                record.get("html") or "", record.get("final_url") or record.get("url")
            ):
                if hop not in hops:
                    hops.append(hop)
        return InterceptFailure(
            f"{cls.name}: no_job_data_on_entry — 入口页正常打开"
            f"（HTTP {opened[0].get('status')}）但这一页没有岗位数据，很可能站错了页；"
            f"自家招聘子域候选 {len(hops)} 个 ({matcher_text})",
            block_kind="no_job_data_on_entry",
            hops=hops,
            evidence={"navigations": _nav_evidence(records)},
        )

    def _await_list_capture(self, page, collected, matchers) -> None:
        """智能等待岗位接口响应：命中拦截（collected 增长）后再静默 quiet_after_capture_ms（兜住紧随的
        二次 XHR）即返回，**上限仍是 wait_ms**。比固定 wait_ms 死等快，且绝不少等/丢数据——命中前一直等、
        命中后留静默窗口、未命中则等满 wait_ms（与旧行为完全一致）。

        仅在配了**具体 matchers**（命中即可靠判定「岗位接口已回」）时启用；matchers 为空=拦截所有 JSON
        时无法区分岗位接口与统计/配置请求 → 退回固定 wait_ms（不冒提前返回丢岗位的风险）。"""
        if not matchers:
            page.wait_for_timeout(self.wait_ms)
            return
        step = 300
        waited = 0
        last = len(collected)
        quiet = 0
        while waited < self.wait_ms:
            page.wait_for_timeout(step)  # sync API 在等待期间仍会派发 on_response（拦截照常累积）
            waited += step
            cur = len(collected)
            if cur > last:        # 有新拦截响应 → 重置静默计时（仍在加载，继续等）
                last = cur
                quiet = 0
            elif last > 0:        # 已命中过且本轮无新响应 → 累计静默；够久即判定加载停当，提前返回
                quiet += step
                if quiet >= self.quiet_after_capture_ms:
                    return
        # 未命中 / 一直有新响应 → 等满 wait_ms（绝不少等）

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

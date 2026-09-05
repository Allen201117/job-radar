"""
SPA 招聘站通用浏览器抓取层（Tier-2）。

思路（合规）：用真实无头浏览器加载官方招聘**公开页** → 站点自有 JS 自己签名调用其官方岗位接口
→ 我们**拦截该接口响应**拿到真实 title/id/城市 → 用详情 URL 模板拼 jd_url → RawJob。
不破解签名、不调私有接口、低频。

子类只需配置：list_urls / intercept_match / posts_keys / detail_template / official_hosts，并实现 _map()。
playwright 仅在 fetch() 内惰性导入——未跑 fetch 的单元测试无需安装 playwright。
"""
import json
import re
from typing import List, Optional
from urllib.parse import urlparse

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


# 静态资源不是招聘列表页。台账里真出现过入口 URL 就是一张图的情况（京东方的
# official_entry_url = portal-oss.zhiye.com/…/xxx.jpg，早先某轮搜来的垃圾）：
# chromium goto 一张图也返 200、content() 给个 <img> 包壳，而 host 带 zhiye.com
# 就足以让 detect_platform 一口咬定 beisen —— **回验 host 挡不住它，host 本来就是对的**。
# ⚠️ 只匹配 path，不匹配整串：query 里带 .jpg 的正常接口会被误伤。
# （`.json` 不会命中：`js` 后面跟着 `o`，cnstaff 的 joblist.json 安全。）
_STATIC_ASSET_RE = re.compile(
    r"\.(?:jpe?g|png|gif|webp|svg|ico|bmp|css|js|mjs|woff2?|ttf|otf|eot"
    r"|mp4|webm|mp3|pdf|zip|rar|gz)$",
    re.I,
)


def _is_static_asset(url):
    return bool(_STATIC_ASSET_RE.search(urlparse(str(url or "")).path or ""))


def _ats_hint(final_url, html):
    """渲染后的页面里认出的第三方 ATS。认不出、或解析不出真正属于该平台的地址 → None。

    ⚠️ 必须回验 `detect_platform(resolved, "") == platform`：resolve_source_url 兜底会原样返回
    final_url（= 公司自己的招聘介绍页），不回验就等于把「没找到」当成「找到了」。

    附带 `identity_text`（标题 + 可见文本前 3000 字）：**身份结论只有这里做得出来**——
    httpx 对 moka/beisen 租户页只拿得到壳，核不出公司名（宝洁 app.mokahr.com/…/pg/91934
    实测 page_company_not_found），而 P1 的候选门是 identity_ok 不为 True 就拒。
    把这段素材带给持有 row["company"] 的那一层去核，别让 P1 拿壳重判。
    ⚠️ 它**只在内存里传，绝不进台账**（gap_funnel_browser 收到后立刻 pop 掉）。
    ⚠️ 也不能改走 adapter.company_name：probe_one 与 run.py 都不设它，
    verify_page_identity("") 直接返回 (True, "company_not_provided") —— 门形同虚设。
    """
    if _is_static_asset(final_url):
        return None
    platform, adapter = platform_fingerprint.detect_platform(final_url, html)
    if not adapter:
        return None
    resolved = platform_fingerprint.resolve_source_url(platform, final_url, html)
    if (
        not resolved
        or _is_static_asset(resolved)
        or platform_fingerprint.detect_platform(resolved, "")[0] != platform
    ):
        return None
    title = platform_fingerprint._TITLE_RE.search(str(html or ""))
    title_text = platform_fingerprint._visible_text(title.group(1), 200) if title else ""
    return {
        "platform": platform,
        "adapter": adapter,
        "source_url": resolved,
        # 标题排在前面：verify_page_identity 只读可见文本前 3000 字。
        "identity_text": (title_text + " " + platform_fingerprint._visible_text(html, 3000))[:3200],
    }


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

    no_job_data_on_entry 时额外带两样「下一跳」线索，都是**只有渲染后才拿得到**的
    （httpx 道看到的原始 HTML 里，SPA 壳往往一个链接都没有）：
      · ``ats_hint``  渲染后的页面里认出的第三方 ATS（跨主域那半，如 basf.jobs→hotjob、
                      shell→myworkdayjobs）。2026-09-05 实测：find_careers_subdomain_hops
                      **只收同主域**，巴斯夫/壳牌这类的目标全被它丢掉，所以这条不能省。
      · ``hops``      自家招聘子域候选（同主域那半，如 job.10jqka→campus.10jqka）。
    """

    def __init__(self, message, *, block_kind, hops=(), ats_hint=None, evidence=None):
        super().__init__(message)
        self.block_kind = block_kind
        self.hops = list(hops or ())
        self.ats_hint = dict(ats_hint) if ats_hint else None
        self.evidence = dict(evidence or {})


class PlaywrightAdapter(BaseAdapter):
    name = "playwright_base"

    # ---- 子类配置 ----
    company_name: str = ""
    entry_hint = None                # 见 capture_entry_hint；每次 fetch 重置
    list_urls: List[str] = []
    intercept_match: str = ""           # 要拦截的接口 URL 单个子串（向后兼容）
    intercept_matches: tuple = ()       # 多个候选子串（任一命中即拦截）；两者皆空 = 拦截所有 JSON
    posts_keys = ("data.job_post_list", "data.posts", "data.list", "data.data.list",
                  "data.items", "data.records", "data.rows", "data.content",
                  "job_post_list", "posts", "list", "items", "records", "rows", "data",
                  "Data", "Data.Posts", "Data.List", "Data.Rows")  # 北森 GetJobAdPageList: 顶层 Data 列表
    detail_template: str = ""           # 含 {id}
    official_hosts: tuple = ()
    # 每次 fetch 都从渲染后的入口页认一次第三方 ATS（结果放 self.entry_hint）。
    # 只给「不知道对方是什么平台」的通用盲抓开（company_spa）——它多花一次 page.content()，
    # 对已知平台的子类没有收益。⚠️ 光靠「一个 JSON 都没拦到」那条路**认不出最常见的那一类**：
    # 2026-09-05 实测广汽/埃斯顿/华虹三家，company_spa 的 fetch 全部成功（JSON 拦到了），
    # 但 parse 出 0 个岗（拼不出逐岗 URL）—— 不抛异常，于是判因逻辑一次都没跑到。
    capture_entry_hint: bool = False
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

        # ⚠️ 必须每次 fetch 重置：probe.py 用的是 ADAPTERS 里的**共享单例**，
        # 不重置会把上一个源认出的平台安到下一家头上（张冠李戴，同 list_urls 那个坑）。
        self.entry_hint = None
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
                # 取判因证据要多花一次 content()/url：一个岗位接口都没拦到时必取；
                # 通用盲抓（capture_entry_hint）即使拦到了也取，用来认真实平台。
                if not collected or self.capture_entry_hint:
                    try:
                        record["final_url"] = page.url
                        record["html"] = page.content()
                    except Exception:
                        pass
                navigations.append(record)
            browser.close()

        if self.capture_entry_hint:
            self.entry_hint = next(
                (
                    hint
                    for hint in (
                        _ats_hint(
                            record.get("final_url") or record.get("url"),
                            record.get("html") or "",
                        )
                        for record in navigations
                    )
                    if hint
                ),
                None,
            )
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
        hops, ats_hint = [], None
        for record in opened:
            html = record.get("html") or ""
            final_url = record.get("final_url") or record.get("url")
            if ats_hint is None:
                ats_hint = _ats_hint(final_url, html)
            for hop in platform_fingerprint.find_careers_subdomain_hops(html, final_url):
                if hop not in hops:
                    hops.append(hop)
        return InterceptFailure(
            f"{cls.name}: no_job_data_on_entry — 入口页正常打开"
            f"（HTTP {opened[0].get('status')}）但这一页没有岗位数据，很可能站错了页；"
            f"渲染后认出 ATS={(ats_hint or {}).get('platform') or '无'}、"
            f"自家招聘子域候选 {len(hops)} 个 ({matcher_text})",
            block_kind="no_job_data_on_entry",
            hops=hops,
            ats_hint=ats_hint,
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

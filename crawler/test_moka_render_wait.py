"""Moka 列表「渲染完」的判据与失败分流（2026-09-13）。

治的病：2026-09-10 起 Moka 新版前端每页都 POST sentry-fe.mokahr.com，该主机从 GitHub runner
连不上也不断开 → `wait_until="networkidle"` 永远等不到 → 4 个路由 ×35s 全超时被 `except: continue`
吞掉 → 返回 0 岗、crawl_run 记 success。410 个 moka 源日产从 3.6 万跌到 535，312 个源天天「0 岗成功」。

钉死三件事：
① 不再等 networkidle（永远等不到的请求不该决定抓不抓得到）；
② 所有路由都「既没岗位卡也没空态」= 页面没渲染出来 → 必须抛错，让 crawl_run 记 failed；
③ 页面正常渲染出 Moka 自己的空态 = 真没岗 → 正常返回 0 岗，不许误报 failed；
④ 门户被关停（整页「当前网页已关停」）单独报 portal closed，不混进「没渲染出来」。
"""
import json
import sys
import types
import unittest
from unittest import mock

from adapters.china_ats import MokaAdapter

BASE = "https://app.mokahr.com/campus-recruitment/demo/1"


class _Timeout(Exception):
    """模拟 playwright TimeoutError（fetch 只按 Exception 处理，不依赖具体类型）。"""


class _Handle:
    def __init__(self, value):
        self._v = value

    def json_value(self):
        return self._v


class _FakePage:
    """按路由编排行为：("cards", n) / ("empty",) / ("closed",) / ("timeout",) / ("goto_error",)。"""

    def __init__(self, behaviors, reopen_behaviors=None):
        self.behaviors = behaviors
        self.reopen_behaviors = reopen_behaviors or {}
        self.route = None
        self.gotos = []  # (route, wait_until)

    def _behavior(self):
        opened = sum(1 for r, _ in self.gotos if r == self.route)
        if opened > 1 and self.route in self.reopen_behaviors:
            return self.reopen_behaviors[self.route]
        return self.behaviors.get(self.route, ("timeout",))

    def goto(self, url, wait_until=None, timeout=None):
        assert url.startswith(BASE)
        self.route = url[len(BASE):]
        self.gotos.append((self.route, wait_until))
        if self._behavior()[0] == "goto_error":
            raise _Timeout(f"goto {url} timed out")

    def wait_for_function(self, js, arg=None, timeout=None, polling=None):
        b = self._behavior()
        if b[0] in ("timeout", "goto_error"):
            raise _Timeout("wait_for_function timed out")
        # 真实浏览器里由 _READY_JS 判断；替身按编排直接给结论，但要求判据文案确实被传进去了
        markers, closed = arg
        assert "暂无匹配职位" in markers and "尚无任何相关职位" in markers
        assert closed == "当前网页已关停"
        return _Handle(b[0])

    def wait_for_timeout(self, _ms):
        pass

    def eval_on_selector_all(self, sel, js):
        b = self._behavior()
        n = b[1] if b[0] == "cards" else 0
        slug = "".join(ch for ch in self.route if ch.isalnum()) or "root"
        return [{"href": f"#/job/{slug}-{i}", "text": f"算法工程师{i}\n北京市"} for i in range(n)]

    def query_selector(self, sel):
        return None  # 单页租户：不渲染分页器

    def query_selector_all(self, sel):
        return []


def _fake_playwright_modules(page):
    class _Ctx:
        def new_page(self):
            return page

    class _Browser:
        def new_context(self, **_kw):
            return _Ctx()

        def close(self):
            pass

    class _Chromium:
        def launch(self, headless=True):
            return _Browser()

    class _PW:
        chromium = _Chromium()

    class _CM:
        def __enter__(self):
            return _PW()

        def __exit__(self, *a):
            return False

    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: _CM()
    pkg = types.ModuleType("playwright")
    pkg.sync_api = sync_api
    return {"playwright": pkg, "playwright.sync_api": sync_api}


def _run(behaviors, reopen_behaviors=None):
    page = _FakePage(behaviors, reopen_behaviors)
    adapter = MokaAdapter()
    # BASE 是带 id 的校招门户：0 岗时 fetch 会去问平台「当前生效的校招门户」——单测不打真网络，
    # 这里固定答「就是它自己」（= 真休眠）。换期那条路径钉在 test_fake_green_sources.py。
    adapter._current_campus_portal_id = lambda host, tenant: BASE.rsplit("/", 1)[-1]
    with mock.patch.dict(sys.modules, _fake_playwright_modules(page)):
        raw = adapter.fetch(BASE)
    return adapter, page, json.loads(raw)


class MokaRenderWaitTest(unittest.TestCase):
    def test_never_waits_for_networkidle(self):
        _, page, _ = _run({"#/jobs": ("cards", 12)})
        self.assertTrue(page.gotos)
        for route, wait_until in page.gotos:
            self.assertNotEqual(wait_until, "networkidle",
                                "sentry 请求挂着时 networkidle 永远等不到 → 全部路由超时 → 0 岗")

    def test_all_routes_not_rendered_raises(self):
        page = _FakePage({})  # 每个路由都等不到岗位卡 / 空态
        adapter = MokaAdapter()
        with mock.patch.dict(sys.modules, _fake_playwright_modules(page)):
            with self.assertRaises(RuntimeError) as ctx:
                adapter.fetch(BASE)
        self.assertIn("not found on any route", str(ctx.exception))
        self.assertEqual(len(page.gotos), len(MokaAdapter._routes), "要把每个路由都试过才能下「没有列表」的结论")
        self.assertIsNone(adapter.reported_total)
        self.assertFalse(adapter.fetch_complete)

    def test_goto_errors_everywhere_also_raise(self):
        page = _FakePage({r: ("goto_error",) for r in MokaAdapter._routes})
        adapter = MokaAdapter()
        with mock.patch.dict(sys.modules, _fake_playwright_modules(page)):
            with self.assertRaises(RuntimeError):
                adapter.fetch(BASE)

    def test_rendered_empty_state_returns_zero_without_raising(self):
        adapter, _, data = _run({"#/jobs": ("empty",)})   # 其余路由都不是列表页（等不到判据）
        self.assertEqual(data["cards"], [])
        self.assertEqual(adapter.parse(json.dumps(data)), [])
        self.assertIsNone(adapter.reported_total, "一条都没拿到时别拿 0 当分母（既有契约）")
        self.assertFalse(adapter.fetch_complete)

    def test_closed_portal_raises_immediately_with_its_own_reason(self):
        # 2026-09-13 CI 实测：人福医药 / 仙工智能 / 极米校招 / 观远数据 / 真格基金 / 流利说 整页只剩「当前网页已关停」
        page = _FakePage({r: ("closed",) for r in MokaAdapter._routes})
        adapter = MokaAdapter()
        with mock.patch.dict(sys.modules, _fake_playwright_modules(page)):
            with self.assertRaises(RuntimeError) as ctx:
                adapter.fetch(BASE)
        self.assertIn("portal closed", str(ctx.exception), "关停 ≠ 没渲染出来，报错原因要能让人直接去停用源")
        self.assertEqual(len(page.gotos), 1, "整个门户关停，换 hash 路由是同一页，不必再白等 3 个路由")
        self.assertIsNone(adapter.reported_total)

    def test_cards_on_later_route_after_earlier_timeouts(self):
        adapter, page, data = _run({"#/campus/jobs": ("cards", 7)})
        self.assertEqual(len(data["cards"]), 7)
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(adapter.reported_total, 7)
        self.assertEqual(len(adapter.parse(json.dumps(data))), 7)

    def test_best_route_reopened_only_when_page_moved_away(self):
        # 命中 ≥3 张卡就停：页面还停在该路由，不必再开一遍
        _, page, _ = _run({"#/jobs": ("cards", 5)})
        self.assertEqual([r for r, _ in page.gotos], ["#/jobs"])
        # 岗位最多的路由不是最后打开的那个 → 要回到它再翻页
        _, page, data = _run({"#/jobs": ("cards", 2), "#/positions": ("empty",)})
        self.assertEqual([r for r, _ in page.gotos], ["#/jobs", "", "#/campus/jobs", "#/positions", "#/jobs"])
        self.assertEqual(len(data["cards"]), 2)

    def test_failure_when_reopening_best_route_is_not_swallowed(self):
        page = _FakePage({"#/jobs": ("cards", 2)}, reopen_behaviors={"#/jobs": ("timeout",)})
        adapter = MokaAdapter()
        with mock.patch.dict(sys.modules, _fake_playwright_modules(page)):
            with self.assertRaises(Exception):
                adapter.fetch(BASE)

    def test_ready_js_checks_cards_and_empty_markers(self):
        js = MokaAdapter._READY_JS
        self.assertIn("a[href*='#/job/']", js)
        self.assertIn("'empty'", js)
        self.assertIn("'cards'", js)
        self.assertIn("'closed'", js)
        # 岗位卡优先于任何文案判定：有卡就是有岗，页面别处出现「暂无最新职位」之类不能把它判空
        self.assertLess(js.index("'cards'"), js.index("'closed'"))
        self.assertLess(js.index("'cards'"), js.index("'empty'"))


if __name__ == "__main__":
    unittest.main()

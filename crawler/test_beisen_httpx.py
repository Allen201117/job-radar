"""beisen 列表 httpx-first 抓取单测（mock httpx，不打真网络）。

覆盖：① 翻页收齐 Count + 抓全判定 ② 端点大小写两试（/api/Jobad/ 与 /api/JobAd/）
③ 仅 route 已缓存才走 httpx（否则回退浏览器，本测不触发）。
注：Category 固定取 []（全部招聘类别），不再按 url 路径猜社招/校招——单类别会漏抓另一类别导致 list-absence 误杀。
红线：抓不全(撞上限)绝不让 fetch_complete=True 误导 list-absence。
"""
import json
import unittest
from unittest import mock

from adapters import china_ats
from adapters.china_ats import BeisenAdapter


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _FakeClient:
    """按预设序返回：第一次 get(列表页 HTML 含 PortalId)，之后 post(GetJobAdPageList) 按页给 Data。"""
    def __init__(self, html, pages, ep_filter=None):
        self.html = html
        self.pages = pages
        self.calls = 0
        self.ep_filter = ep_filter  # 只对某端点大小写返回 Data，模拟大小写敏感

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        return _Resp(None) if False else type("R", (), {"text": self.html})()

    def post(self, url, json=None, headers=None):
        if self.ep_filter and self.ep_filter not in url:
            return _Resp({"error": "wrong case"})   # 不含 Data → 触发另一个大小写
        i = self.calls
        self.calls += 1
        return _Resp(self.pages[i] if i < len(self.pages) else {"Data": [], "Count": self.pages[0]["Count"]})


def _page(ids, count):
    return {"Count": count, "Data": [{"Id": str(x), "JobAdName": f"岗{x}", "Duty": "职责", "Require": "要求"}
                                     for x in ids]}


def _patch(html, pages, ep_filter=None):
    return mock.patch.object(china_ats.httpx, "Client", lambda **kw: _FakeClient(html, pages, ep_filter))


HTML = '<html>var x={"PortalId":"325fe107-c882-4ea9-8b3a-1fa2268c80ef"};</html>'


class BeisenHttpxTest(unittest.TestCase):
    def _a(self, page_size=2, max_jobs=10):
        a = BeisenAdapter()
        a._PAGE_SIZE = page_size
        a._MAX_JOBS = max_jobs
        return a

    def test_social_category_and_complete(self):
        a = self._a()
        with _patch(HTML, [_page([1, 2], 2)]):
            out = json.loads(a._httpx_fetch("https://x.zhiye.com/social/jobs"))
        self.assertEqual(out["_intercepted"][0]["Count"], 2)
        self.assertTrue(a.fetch_complete)

    def test_paginates_to_count(self):
        a = self._a(page_size=2)
        with _patch(HTML, [_page([1, 2], 3), _page([3], 3)]):
            out = json.loads(a._httpx_fetch("https://x.zhiye.com/campus"))
        self.assertEqual(len(out["_intercepted"][0]["Data"]), 3)
        self.assertTrue(a.fetch_complete)

    def test_capped_not_complete(self):
        a = self._a(page_size=2, max_jobs=2)
        with _patch(HTML, [_page([1, 2], 99), _page([3, 4], 99)]):
            a._httpx_fetch("https://x.zhiye.com/social/jobs")
        self.assertFalse(a.fetch_complete)     # 撞上限 → absence 不会误判

    def test_short_page_does_not_end_pagination_when_total_known(self):
        """限流/抖动回一个短页，不许当末页收工。

        2026-09-04 实测病例：中国交建自报 2565、深页明明有数据，却只抓到 800 就 complete=False，
        病根就是旧判据「本页条数 < pageSize → 末页」。北森被打急了会回短页，一撞就整源截断。
        """
        a = self._a(page_size=2, max_jobs=100)
        with _patch(HTML, [_page([1, 2], 5), _page([3], 5), _page([4, 5], 5)]):
            out = json.loads(a._httpx_fetch("https://x.zhiye.com/social/jobs"))
        self.assertEqual(len(out["_intercepted"][0]["Data"]), 5)   # 短页之后继续翻，收齐 5 条
        self.assertTrue(a.fetch_complete)

    def test_page_with_no_new_ids_stops_pagination(self):
        """接口在原地打转（重复回同一批）→ 必须停，否则翻到 max_jobs 才罢休、白烧配额。"""
        a = self._a(page_size=2, max_jobs=100)
        with _patch(HTML, [_page([1, 2], 99), _page([1, 2], 99), _page([3], 99)]):
            out = json.loads(a._httpx_fetch("https://x.zhiye.com/social/jobs"))
        self.assertEqual(len(out["_intercepted"][0]["Data"]), 2)
        self.assertFalse(a.fetch_complete)     # 没收齐 99 → 诚实标未抓全

    def test_duplicate_rows_across_pages_are_deduped(self):
        """重复行不能顶掉真实进度：不去重的话「收满 total 就停」会提前满足、尾巴永远抓不到。"""
        a = self._a(page_size=2, max_jobs=100)
        with _patch(HTML, [_page([1, 2], 4), _page([2, 3], 4), _page([4], 4)]):
            out = json.loads(a._httpx_fetch("https://x.zhiye.com/social/jobs"))
        ids = [r["Id"] for r in out["_intercepted"][0]["Data"]]
        self.assertEqual(ids, ["1", "2", "3", "4"])
        self.assertTrue(a.fetch_complete)

    def test_short_page_still_ends_pagination_when_total_unknown(self):
        """没有分母可判时，短页仍是唯一的自然末页信号，不能一路翻到上限。"""
        a = self._a(page_size=2, max_jobs=100)
        with _patch(HTML, [_page([1, 2], 0), _page([3], 0)]):
            out = json.loads(a._httpx_fetch("https://x.zhiye.com/social/jobs"))
        self.assertEqual(len(out["_intercepted"][0]["Data"]), 3)

    def test_transient_page_failure_is_retried_not_fatal(self):
        """限流抖一下不许把整源截断。

        2026-09-04 线上实测：单源上限 600→8000 后对 *.zhiye.com 的请求量翻十几倍，
        北森按 IP 限流（X-RateLimit-…-second: 50）开始偶发掐我们，而旧代码一页拿不到就 break
        → 上海医药 230→50、三一 135→50。重试补上后，中间一页失败仍能收齐。
        """
        class _FlakyClient(_FakeClient):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.failed_once = False

            def post(self, url, json=None, headers=None):
                if json.get("PageIndex") == 1 and not self.failed_once:
                    self.failed_once = True
                    raise RuntimeError("429 rate limited")
                return _Resp(self.pages[json["PageIndex"]] if json["PageIndex"] < len(self.pages)
                             else {"Data": [], "Count": self.pages[0]["Count"]})

        a = self._a(page_size=2, max_jobs=100)
        pages = [_page([1, 2], 5), _page([3, 4], 5), _page([5], 5)]
        with mock.patch.object(china_ats, "_PAGE_BACKOFF_SECONDS", 0), \
             mock.patch.object(china_ats.httpx, "Client", lambda **kw: _FlakyClient(HTML, pages)):
            out = json.loads(a._httpx_fetch("https://x.zhiye.com/social/jobs"))
        self.assertEqual(len(out["_intercepted"][0]["Data"]), 5)
        self.assertTrue(a.fetch_complete)

    def test_page_failing_every_retry_stops_without_claiming_complete(self):
        """真的一直拿不到 → 停，但绝不许标抓全（否则 list-absence 会拿半截列表去判撤岗）。"""
        class _DeadClient(_FakeClient):
            def post(self, url, json=None, headers=None):
                if json.get("PageIndex", 0) >= 1:
                    raise RuntimeError("429 rate limited")
                return _Resp(self.pages[0])

        a = self._a(page_size=2, max_jobs=100)
        with mock.patch.object(china_ats, "_PAGE_BACKOFF_SECONDS", 0), \
             mock.patch.object(china_ats.httpx, "Client", lambda **kw: _DeadClient(HTML, [_page([1, 2], 99)])):
            out = json.loads(a._httpx_fetch("https://x.zhiye.com/social/jobs"))
        self.assertEqual(len(out["_intercepted"][0]["Data"]), 2)
        self.assertFalse(a.fetch_complete)

    def test_endpoint_case_fallback(self):
        # 只有 /api/JobAd/（大写 A）返 Data → 适配器两试应命中它
        a = self._a()
        with _patch(HTML, [_page([1], 1)], ep_filter="/api/JobAd/"):
            out = a._httpx_fetch("https://x.zhiye.com/social/jobs")
        self.assertIsNotNone(out)

    def test_genuine_zero_returns_empty_envelope_not_none(self):
        """接口答上来了（PortalId 抽到 + Count/Total 显式 0）= 真 0 岗，必须当成功返回空信封，
        不能返回 None——否则 china_ats.fetch() 的「cached route」分支会把它当成 httpx 没打通，
        触发 raise，把「租户暂无在招岗」误记成 failed（2026-09-19 建信基金 ccbfund.zhiye.com
        实锤：25 次全 failed，live 核实其接口稳定 200 返回 Count=0/Total=0）。"""
        a = self._a()
        with _patch(HTML, [{"Data": [], "Count": 0}]):
            out = json.loads(a._httpx_fetch("https://x.zhiye.com/social/jobs"))
        self.assertEqual(out, {"_intercepted": [{"Data": [], "Count": 0}]})
        self.assertEqual(a.reported_total, 0)
        self.assertTrue(a.fetch_complete)

    def test_no_portal_id_and_no_data_returns_none(self):
        """PortalId 都没抽到（页面结构变了/不是这个租户）→ 不能当「真 0 岗」，必须回 None
        交回上层去试 ssr/cards 或最终判 failed，不能把「我们没找对」伪装成「对方真没岗」。"""
        a = self._a()
        html_no_portal = "<html>no portal id here</html>"
        with _patch(html_no_portal, [{"Data": [], "Count": 0}]):
            self.assertIsNone(a._httpx_fetch("https://x.zhiye.com/social/jobs"))


class BeisenFetchRoutingTest(unittest.TestCase):
    """fetch() 对**未缓存**租户：先 httpx 抓完整列表，浏览器只探路由；不再让残缺的 _fetch_paginated
    抓列表把长江存储/追觅这类几百上千岗的真源判 0。修复回归。"""

    def setUp(self):
        self._saved = dict(china_ats._BEISEN_ROUTE_CACHE)
        china_ats._BEISEN_ROUTE_CACHE.clear()

    def tearDown(self):
        china_ats._BEISEN_ROUTE_CACHE.clear()
        china_ats._BEISEN_ROUTE_CACHE.update(self._saved)

    def test_uncached_uses_httpx_list_then_discovers_route_no_paginate(self):
        a = BeisenAdapter()
        list_json = json.dumps({"_intercepted": [{"Data": [{"Id": "g1"}], "Count": 1}]})
        with mock.patch.object(BeisenAdapter, "_httpx_fetch", return_value=list_json) as httpx_fn, \
             mock.patch.object(BeisenAdapter, "_discover_detail_route",
                               return_value="https://x.zhiye.com/social/detail") as disc, \
             mock.patch.object(BeisenAdapter, "_fetch_paginated",
                               side_effect=AssertionError("不应回退浏览器抓列表")) as pag:
            out = a.fetch("https://x.zhiye.com/social")
        self.assertEqual(out, list_json)                       # 返回 httpx 完整列表
        self.assertEqual(a._detail_route, "https://x.zhiye.com/social/detail")
        httpx_fn.assert_called_once()
        disc.assert_called_once()
        pag.assert_not_called()                                # 未走残缺的浏览器抓列表
        self.assertIn("x.zhiye.com", china_ats._BEISEN_ROUTE_CACHE)   # 路由已缓存

    def test_uncached_httpx_miss_falls_back_to_browser(self):
        a = BeisenAdapter()
        paginated = json.dumps({"_intercepted": [{"Data": [{"Id": "g9"}], "Count": 1}]})
        with mock.patch.object(BeisenAdapter, "_httpx_fetch", return_value=None), \
             mock.patch.object(BeisenAdapter, "_fetch_paginated", return_value=paginated) as pag, \
             mock.patch.object(BeisenAdapter, "_discover_detail_route", return_value=None):
            out = a.fetch("https://y.zhiye.com/social")
        self.assertEqual(out, paginated)                       # httpx 没打通 → 回退浏览器全流程
        pag.assert_called_once()

    def test_cached_route_stays_pure_httpx(self):
        china_ats._BEISEN_ROUTE_CACHE["z.zhiye.com"] = "https://z.zhiye.com/social/detail"
        a = BeisenAdapter()
        list_json = json.dumps({"_intercepted": [{"Data": [{"Id": "g2"}], "Count": 1}]})
        with mock.patch.object(BeisenAdapter, "_httpx_fetch", return_value=list_json), \
             mock.patch.object(BeisenAdapter, "_discover_detail_route",
                               side_effect=AssertionError("已缓存不该再探路由")), \
             mock.patch.object(BeisenAdapter, "_fetch_paginated",
                               side_effect=AssertionError("已缓存不该开浏览器")):
            out = a.fetch("https://z.zhiye.com/social")
        self.assertEqual(out, list_json)
        self.assertEqual(a._detail_route, "https://z.zhiye.com/social/detail")

    def test_cached_route_httpx_fail_raises_not_browser(self):
        """route 已缓存但 httpx fetch 失败 → 应 raise RuntimeError，绝不穿透到浏览器。
        这正是 haixin.zhiye.com 的 bug 场景：路由缓存存在但 httpx 拿不到数据，
        旧代码会尝试 _fetch_paginated → 触发 Playwright.launch，CI 里直接崩溃。"""
        china_ats._BEISEN_ROUTE_CACHE["haixin.zhiye.com"] = (
            "https://haixin.zhiye.com/social/detail"
        )
        a = BeisenAdapter()
        with mock.patch.object(BeisenAdapter, "_httpx_fetch", return_value=None), \
             mock.patch.object(BeisenAdapter, "_fetch_paginated",
                               side_effect=AssertionError("路由已缓存不应开浏览器")) as pag:
            with self.assertRaises(RuntimeError):
                a.fetch("https://haixin.zhiye.com/social")
        pag.assert_not_called()



class BeisenRoutesFileContract(unittest.TestCase):
    """crawler/beisen_routes.json 的登记形状契约。

    2026-09-18 立：boe / cnnc / fosunpharma 三家的登记长期是老版 SSR 形式
    `{"ssr_param": "jobId", "ssr_path": "zwxq"}`。那是老版 SSR 列表那条通道的产物，配的是
    SSR 锚点里的**数字 id**；新版 GetJobAdPageList 给的是 **uuid**，两者不通用 ——
    `_resolve_url` 的 dict 分支只认 template，于是每行 jd_url 都是空串，整源要么
    「success + 0 岗」要么报 `list returned rows but no job could be mapped`。
    实际代价：京东方 1073 岗（校招 700）、中核集团 1316 岗（校招 863）、复星医药 160 岗
    （校招 71）三家必投公司在秋招季一个岗都进不了库，而它们的源早就 enabled 躺在表里。

    `_beisen_route_usable()` 已经会把这种形状判成不可用（清缓存 → 落首见租户分支重探），
    但那条自我修复路径要开浏览器；CI 的 httpx 车道走不到，就只能每天失败一次。
    根治是**别让这种形状再登记进来** —— 这条测试就是那道门。
    """

    def test_no_legacy_ssr_shaped_routes(self):
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "beisen_routes.json")
        with open(path, encoding="utf-8") as f:
            routes = json.load(f)
        legacy = {
            host: route for host, route in routes.items()
            if isinstance(route, dict) and ("ssr_param" in route or "ssr_path" in route)
        }
        self.assertEqual(
            legacy, {},
            "beisen_routes.json 不许再登记 {ssr_param, ssr_path} 形式："
            "它配不了新版接口的 uuid，会让每行 jd_url 变成空串。"
            "改登记成详情页 base（如 https://<租户>.zhiye.com/social/detail）。",
        )

    def test_every_route_is_usable(self):
        """每条登记都必须能给新版列表行拼出 jd_url（或自报「靠列表锚点」）。

        不可用的登记比没有登记更糟：没有登记会走首见租户分支重探，
        而不可用的登记会让 adapter 以为自己有路由、拼出空串、静默丢掉整源。
        """
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "beisen_routes.json")
        with open(path, encoding="utf-8") as f:
            routes = json.load(f)
        unusable = [h for h, r in routes.items() if not china_ats._beisen_route_usable(r)]
        self.assertEqual(unusable, [], f"这些登记拼不出 jd_url：{unusable}")


if __name__ == "__main__":
    unittest.main()

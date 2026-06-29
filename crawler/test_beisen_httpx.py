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

    def test_endpoint_case_fallback(self):
        # 只有 /api/JobAd/（大写 A）返 Data → 适配器两试应命中它
        a = self._a()
        with _patch(HTML, [_page([1], 1)], ep_filter="/api/JobAd/"):
            out = a._httpx_fetch("https://x.zhiye.com/social/jobs")
        self.assertIsNotNone(out)

    def test_no_data_returns_none(self):
        a = self._a()
        with _patch(HTML, [{"Data": [], "Count": 0}]):
            self.assertIsNone(a._httpx_fetch("https://x.zhiye.com/social/jobs"))


if __name__ == "__main__":
    unittest.main()

"""feishu httpx-first 抓取单测（mock httpx，不打真网络）。

覆盖：① _httpx_fetch 翻页/去重/抓全判定/真0岗 reached ② fetch() 决策——reached 用 httpx 不开浏览器、
reached=False 回退浏览器、complete 计算（翻到 count=True / 撞 _MAX_JOBS 上限=False）。
红线：httpx 没打通(reached=False)才回退浏览器；抓不全(撞上限)绝不让 list-absence 误判。
"""
import json
import unittest
from unittest import mock

from adapters import feishu


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _FakeClient:
    """按预设页序返回 posts API 响应；构造接受任意 kwargs（与真 httpx.Client 同签名）。"""
    def __init__(self, pages):
        self.pages = pages
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None):
        i = self.calls
        self.calls += 1
        if i < len(self.pages):
            return _Resp(self.pages[i])
        return _Resp({"data": {"job_post_list": [], "count": 0}})


def _page(ids, count):
    return {"data": {"job_post_list": [{"id": str(x), "title": f"T{x}"} for x in ids], "count": count}}


def _patch_client(pages):
    return mock.patch.object(feishu.httpx, "Client", lambda **kw: _FakeClient(pages))


class HttpxFetchTest(unittest.TestCase):
    def _adapter(self, page_size=2, max_jobs=10):
        a = feishu.NioAdapter()
        a._PAGE_SIZE = page_size
        a._MAX_JOBS = max_jobs
        return a

    def test_single_page_complete(self):
        a = self._adapter()
        with _patch_client([_page([1, 2], 2)]):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertEqual(total, 2)
        self.assertEqual(len(rows), 2)
        self.assertTrue(reached)

    def test_paginates_and_dedups_to_count(self):
        a = self._adapter(page_size=2)
        # page0=[1,2], page1=[2,3] —— 2 跨页重复应去重，收齐 count=3
        with _patch_client([_page([1, 2], 3), _page([2, 3], 3)]):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertEqual(total, 3)
        self.assertEqual(sorted(r["id"] for r in rows), ["1", "2", "3"])
        self.assertTrue(reached)

    def test_caps_at_max_jobs_not_complete(self):
        a = self._adapter(page_size=2, max_jobs=2)
        with _patch_client([_page([1, 2], 9), _page([3, 4], 9)]):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertEqual(len(rows), 2)        # 撞上限即停
        self.assertTrue(reached)
        self.assertLess(len(rows), total)     # < total → fetch() 会判 not complete

    def test_real_zero_jobs_is_reached(self):
        a = self._adapter()
        with _patch_client([_page([], 0)]):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertEqual(rows, [])
        self.assertEqual(total, 0)
        self.assertTrue(reached)              # 真 0 岗也算打通，不回退浏览器


class FetchDecisionTest(unittest.TestCase):
    def test_reached_complete_sets_flag_and_envelope(self):
        a = feishu.NioAdapter()
        with mock.patch.object(a, "_httpx_fetch", return_value=([{"id": "1", "title": "T"}], 1, True)):
            out = json.loads(a.fetch("https://nio.jobs.feishu.cn/index/position"))
        self.assertEqual(out["_intercepted"][0]["data"]["count"], 1)
        self.assertTrue(a.fetch_complete)

    def test_reached_but_capped_not_complete(self):
        a = feishu.NioAdapter()
        rows = [{"id": str(i), "title": "T"} for i in range(600)]
        with mock.patch.object(a, "_httpx_fetch", return_value=(rows, 2491, True)):
            a.fetch("https://nio.jobs.feishu.cn/index/position")
        self.assertFalse(a.fetch_complete)    # 抓不全 → absence 不会误判

    def test_reached_zero_returns_empty_no_browser(self):
        a = feishu.NioAdapter()
        called = {"browser": False}

        def _boom(_url):
            called["browser"] = True
            return "BROWSER"

        with mock.patch.object(a, "_httpx_fetch", return_value=([], 0, True)), \
                mock.patch.object(a, "_browser_fetch", _boom):
            out = json.loads(a.fetch("https://nio.jobs.feishu.cn/index/position"))
        self.assertEqual(out["_intercepted"][0]["data"]["job_post_list"], [])
        self.assertTrue(a.fetch_complete)
        self.assertFalse(called["browser"])   # httpx 打通即用，绝不多开浏览器

    def test_not_reached_falls_back_to_browser(self):
        a = feishu.NioAdapter()
        with mock.patch.object(a, "_httpx_fetch", return_value=([], None, False)), \
                mock.patch.object(a, "_browser_fetch", return_value="BROWSER"):
            self.assertEqual(a.fetch("https://nio.jobs.feishu.cn/index/position"), "BROWSER")
        self.assertFalse(a.fetch_complete)


if __name__ == "__main__":
    unittest.main()

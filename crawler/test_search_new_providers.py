"""google_cse / exa 两个新 provider 的离线夹具单测（纯函数，不打网络）。

夹具按各家官方响应形状手写：Google CSE 的 `items[]`、Exa 的 `results[]`。
口径与既有 provider 一致 —— 解析出 {title,url,snippet,text,publisher} 五个键。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import search_exa
import search_google_cse
import search_router


GOOGLE_FIXTURE = {
    "kind": "customsearch#search",
    "items": [
        {"title": "比亚迪校园招聘", "link": "https://byd.zhiye.com/campus",
         "snippet": "2027届校园招聘正式启动"},
        {"title": "比亚迪社会招聘", "link": "https://byd.zhiye.com/social",
         "snippet": "社招职位列表"},
        {"title": "没有链接的一条", "snippet": "应被丢弃"},
    ],
}

EXA_FIXTURE = {
    "requestId": "abc",
    "results": [
        {"title": "帆软招聘", "url": "https://join.fanruan.com/",
         "text": "帆软软件有限公司招聘官网，社招与校招入口。"},
        {"title": "", "url": "https://example.com/x", "text": "标题空应被丢弃"},
    ],
}


class GoogleCseParseTest(unittest.TestCase):
    def test_parses_items(self):
        out = search_google_cse.parse_response(GOOGLE_FIXTURE)
        self.assertEqual(len(out), 2, "缺 link 的那条必须丢掉")
        first = out[0]
        self.assertEqual(first["title"], "比亚迪校园招聘")
        self.assertEqual(first["url"], "https://byd.zhiye.com/campus")
        self.assertEqual(first["snippet"], "2027届校园招聘正式启动")
        self.assertEqual(first["text"], first["snippet"])
        self.assertEqual(first["publisher"], "byd.zhiye.com")

    def test_empty_and_garbage_return_empty(self):
        for payload in ({}, None, {"items": "notalist"}, {"items": [None, 3]}):
            self.assertEqual(search_google_cse.parse_response(payload), [])

    def test_request_carries_cx_and_caps_num_at_ten(self):
        with mock.patch.dict(os.environ, {search_google_cse.CX_ENV: "cx123"}):
            url, headers, params = search_google_cse.build_request("k", "比亚迪 校园招聘", 50)
        self.assertIn("customsearch/v1", url)
        self.assertEqual(params["cx"], "cx123")
        self.assertEqual(params["key"], "k")
        self.assertEqual(params["num"], 10, "num 超过 10 Google 直接 400")
        self.assertEqual(headers["Accept"], "application/json")

    def test_query_has_no_site_filter(self):
        """引擎侧已限定只收录 ATS 域名，再拼 site: 只会把结果打空。"""
        with mock.patch.dict(os.environ, {search_google_cse.CX_ENV: "cx"}):
            _url, _headers, params = search_google_cse.build_request("k", "比亚迪 招聘", 8)
        self.assertNotIn("site:", params["q"])

    def test_not_configured_without_cx(self):
        provider = search_google_cse.GoogleCseProvider()
        with mock.patch.dict(os.environ, {"GOOGLE_CSE_API_KEY": "k"}, clear=True):
            self.assertFalse(provider.is_configured(), "只配 key 不配 cx 会 400，必须当没配")
        with mock.patch.dict(os.environ,
                             {"GOOGLE_CSE_API_KEY": "k", search_google_cse.CX_ENV: "c"},
                             clear=True):
            self.assertTrue(provider.is_configured())

    def test_uses_get_not_post(self):
        self.assertEqual(search_google_cse.GoogleCseProvider().method, "GET")


class ExaParseTest(unittest.TestCase):
    def test_parses_results(self):
        out = search_exa.parse_response(EXA_FIXTURE)
        self.assertEqual(len(out), 1, "标题为空的那条必须丢掉")
        self.assertEqual(out[0]["url"], "https://join.fanruan.com/")
        self.assertEqual(out[0]["publisher"], "join.fanruan.com")
        self.assertIn("帆软", out[0]["text"])

    def test_long_text_is_truncated_in_snippet_but_kept_in_text(self):
        long_text = "岗" * 2000
        out = search_exa.parse_response(
            {"results": [{"title": "t", "url": "https://a.com/x", "text": long_text}]})
        self.assertLessEqual(len(out[0]["snippet"]), 600)
        self.assertEqual(len(out[0]["text"]), 2000)

    def test_empty_and_garbage_return_empty(self):
        for payload in ({}, None, {"results": "notalist"}):
            self.assertEqual(search_exa.parse_response(payload), [])

    def test_request_shape(self):
        url, headers, body = search_exa.build_request("key", "帆软 招聘 官网", 8)
        self.assertEqual(url, "https://api.exa.ai/search")
        self.assertEqual(headers["x-api-key"], "key")
        self.assertEqual(body["numResults"], 8)
        self.assertEqual(body["type"], "auto")
        self.assertIn("startPublishedDate", body)


class ScopedProviderTest(unittest.TestCase):
    """google_cse 只收录 ATS 域名 → 不能进通用搜索池（会白烧 T3 的额度还打薄召回）。"""

    class _Fake:
        def __init__(self, name, general=True):
            self.name = name
            self.general = general

        def is_configured(self):
            return True

        def remaining(self, _sb):
            return 10

        def search(self, *_a, **_k):
            return [{"url": "https://x/%s" % self.name, "title": self.name}]

        def consume(self, *_a, **_k):
            pass

    def _router(self):
        return search_router.SearchRouter([
            self._Fake("scoped", general=False), self._Fake("general")])

    def test_general_search_skips_scoped_providers(self):
        urls = [r["url"] for r in self._router().search(None, "q")]
        self.assertEqual(urls, ["https://x/general"])

    def test_remaining_excludes_scoped_quota(self):
        self.assertEqual(self._router().remaining(None), 10)

    def test_scoped_providers_are_reachable_explicitly(self):
        names = [p.name for p in self._router().scoped_providers()]
        self.assertEqual(names, ["scoped"])

    def test_entry_finder_plans_scoped_first(self):
        import entry_finder

        plan = entry_finder._provider_plan(self._router(), None)
        self.assertEqual(getattr(plan[0], "name", None), "scoped",
                         "找入口这条链上，ATS 域内的专用源最便宜、命中率最高，必须排第一")
        self.assertNotIn("scoped", [getattr(p, "name", "") for p in plan[1:]],
                         "同一个 provider 不许在计划里出现两次")


if __name__ == "__main__":
    unittest.main()

"""多源搜索层单测：各 provider 响应解析（纯函数，不打网络）+ 路由器预算/兜底/去重逻辑。

口径：所有 provider 解析出统一形状 {title,url,snippet,text,publisher}，与 qianfan_search.search()
字节级一致 → 可直接喂 insight_engine.run_pipeline 的 sources（writer/judge 读 text）。
"""
import os
import unittest
from datetime import datetime, timezone

import search_base
import search_bocha
import search_router
import search_serper
import search_tavily


def _res(url, title="t", text="body", publisher=None):
    return {"title": title, "url": url, "snippet": text, "text": text,
            "publisher": publisher or url}


class FakeProvider:
    """注入式假 provider，测路由器编排逻辑（不打网络、不碰 DB）。"""

    def __init__(self, name, results=None, configured=True, remaining=10, raises=False):
        self.name = name
        self._results = results or []
        self._configured = configured
        self._remaining = remaining
        self._raises = raises
        self.search_calls = 0
        self.consumed = 0

    def is_configured(self):
        return self._configured

    def remaining(self, sb):
        return self._remaining

    def search(self, query, top_k=8, client=None):
        self.search_calls += 1
        if self._raises:
            raise RuntimeError("boom")
        return list(self._results)

    def consume(self, sb, n=1):
        self.consumed += n


class TestDomainOf(unittest.TestCase):
    def test_strips_scheme_and_www(self):
        self.assertEqual(search_base.domain_of("https://www.zhihu.com/question/1"), "zhihu.com")
        self.assertEqual(search_base.domain_of("http://maimai.cn/web/x"), "maimai.cn")

    def test_blank_url_returns_web(self):
        self.assertEqual(search_base.domain_of(""), "web")
        self.assertEqual(search_base.domain_of(None), "web")


class TestRecency(unittest.TestCase):
    NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)

    def test_iso_three_years_back(self):
        self.assertEqual(search_base.recency_start_iso(3, self.NOW), "2023-06-21")

    def test_us_three_years_back(self):
        self.assertEqual(search_base.recency_start_us(3, self.NOW), "06/21/2023")

    def test_zero_years_is_today(self):
        self.assertEqual(search_base.recency_start_us(0, self.NOW), "06/20/2026")


class TestBochaParse(unittest.TestCase):
    def test_parses_webpages_value(self):
        data = {"code": 200, "data": {"webPages": {"value": [
            {"name": "字节工作体验", "url": "https://zhihu.com/q/1",
             "snippet": "短摘要", "summary": "较长正文", "siteName": "知乎"}]}}}
        out = search_bocha.parse_response(data)
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual(r["title"], "字节工作体验")
        self.assertEqual(r["url"], "https://zhihu.com/q/1")
        self.assertEqual(r["publisher"], "知乎")
        self.assertEqual(r["snippet"], "短摘要")
        self.assertEqual(r["text"], "较长正文")  # summary 优先作 LLM 正文

    def test_summary_falls_back_to_snippet_and_domain_publisher(self):
        data = {"data": {"webPages": {"value": [
            {"name": "t", "url": "https://x.com/a", "snippet": "只有短摘要"}]}}}
        out = search_bocha.parse_response(data)
        self.assertEqual(out[0]["text"], "只有短摘要")
        self.assertEqual(out[0]["publisher"], "x.com")  # 无 siteName → 域名兜底

    def test_drops_rows_missing_title_or_url(self):
        data = {"data": {"webPages": {"value": [
            {"name": "", "url": "https://x.com/a"}, {"name": "t", "url": ""}]}}}
        self.assertEqual(search_bocha.parse_response(data), [])

    def test_empty_or_malformed_returns_empty(self):
        self.assertEqual(search_bocha.parse_response({}), [])
        self.assertEqual(search_bocha.parse_response({"data": {}}), [])
        self.assertEqual(search_bocha.parse_response(None), [])


class TestTavilyParse(unittest.TestCase):
    def test_parses_results(self):
        data = {"results": [
            {"title": "T", "url": "https://glassdoor.com/x", "content": "正文内容", "score": 0.9}]}
        out = search_tavily.parse_response(data)
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual(r["title"], "T")
        self.assertEqual(r["url"], "https://glassdoor.com/x")
        self.assertEqual(r["text"], "正文内容")
        self.assertEqual(r["snippet"], "正文内容")
        self.assertEqual(r["publisher"], "glassdoor.com")

    def test_empty_returns_empty(self):
        self.assertEqual(search_tavily.parse_response({}), [])
        self.assertEqual(search_tavily.parse_response(None), [])


class TestSerperParse(unittest.TestCase):
    def test_parses_organic(self):
        data = {"organic": [
            {"title": "S", "link": "https://maimai.cn/y", "snippet": "谷歌摘要", "position": 1}]}
        out = search_serper.parse_response(data)
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual(r["title"], "S")
        self.assertEqual(r["url"], "https://maimai.cn/y")
        self.assertEqual(r["text"], "谷歌摘要")
        self.assertEqual(r["publisher"], "maimai.cn")

    def test_empty_returns_empty(self):
        self.assertEqual(search_serper.parse_response({}), [])
        self.assertEqual(search_serper.parse_response({"organic": []}), [])


class TestSearchRouter(unittest.TestCase):
    def test_unions_and_dedups_by_url_in_provider_order(self):
        a = FakeProvider("a", [_res("u1"), _res("u2")])
        b = FakeProvider("b", [_res("u2"), _res("u3")])  # u2 与 a 重复
        out = search_router.SearchRouter([a, b]).search(None, "q")
        self.assertEqual([r["url"] for r in out], ["u1", "u2", "u3"])

    def test_skips_unconfigured_provider(self):
        a = FakeProvider("a", [_res("u1")], configured=False)
        b = FakeProvider("b", [_res("u2")])
        out = search_router.SearchRouter([a, b]).search(None, "q")
        self.assertEqual(a.search_calls, 0)
        self.assertEqual([r["url"] for r in out], ["u2"])

    def test_falls_back_when_provider_errors(self):
        a = FakeProvider("a", raises=True)
        b = FakeProvider("b", [_res("u2")])
        out = search_router.SearchRouter([a, b]).search(None, "q")
        self.assertEqual([r["url"] for r in out], ["u2"])  # a 抛错不拖垮 b

    def test_skips_provider_with_no_budget(self):
        a = FakeProvider("a", [_res("u1")], remaining=0)
        b = FakeProvider("b", [_res("u2")])
        out = search_router.SearchRouter([a, b]).search(None, "q")
        self.assertEqual(a.search_calls, 0)  # 没额度不调
        self.assertEqual([r["url"] for r in out], ["u2"])

    def test_consumes_one_budget_per_used_provider(self):
        a = FakeProvider("a", [_res("u1")])
        b = FakeProvider("b", [_res("u2")], remaining=0)  # 不用 → 不消耗
        search_router.SearchRouter([a, b]).search(None, "q")
        self.assertEqual(a.consumed, 1)
        self.assertEqual(b.consumed, 0)

    def test_no_configured_providers_is_not_configured_and_returns_empty(self):
        a = FakeProvider("a", [_res("u1")], configured=False)
        router = search_router.SearchRouter([a])
        self.assertFalse(router.is_configured())
        self.assertEqual(router.search(None, "q"), [])

    def test_remaining_sums_only_configured_providers(self):
        a = FakeProvider("a", remaining=5)
        b = FakeProvider("b", remaining=3, configured=False)
        c = FakeProvider("c", remaining=7)
        self.assertEqual(search_router.SearchRouter([a, b, c]).remaining(None), 12)


class TestBuildRequest(unittest.TestCase):
    def test_bocha_puts_key_in_header_and_query_in_body(self):
        url, headers, body = search_bocha.build_request("KEY", "字节 工作体验", 8)
        self.assertIn("bochaai.com", url)
        self.assertEqual(headers["Authorization"], "Bearer KEY")
        self.assertEqual(body["query"], "字节 工作体验")
        self.assertEqual(body["count"], 8)

    def test_tavily_puts_key_in_body(self):
        url, _headers, body = search_tavily.build_request("KEY", "q", 5)
        self.assertIn("tavily.com", url)
        self.assertEqual(body["api_key"], "KEY")
        self.assertEqual(body["query"], "q")
        self.assertEqual(body["max_results"], 5)
        self.assertRegex(body["start_date"], r"^\d{4}-\d{2}-\d{2}$")  # 近 3 年时间窗

    def test_serper_puts_key_in_header(self):
        url, headers, body = search_serper.build_request("KEY", "q", 5)
        self.assertIn("serper.dev", url)
        self.assertEqual(headers["X-API-KEY"], "KEY")
        self.assertEqual(body["q"], "q")
        self.assertEqual(body["num"], 5)
        self.assertIn("cdr:1", body["tbs"])      # 近 3 年自定义时间窗
        self.assertIn("cd_min:", body["tbs"])


class TestHttpProviderConfig(unittest.TestCase):
    def setUp(self):
        import search_provider_http
        self._saved = dict(os.environ)
        self._mk = lambda: search_provider_http.HttpSearchProvider(
            "bocha", "BOCHA_API_KEY", search_bocha.parse_response,
            search_bocha.build_request, "BOCHA_DAILY_CAP", 200)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_configured_only_with_key(self):
        os.environ.pop("BOCHA_API_KEY", None)
        self.assertFalse(self._mk().is_configured())
        os.environ["BOCHA_API_KEY"] = "x"
        self.assertTrue(self._mk().is_configured())

    def test_disabled_env_overrides_key(self):
        os.environ["BOCHA_API_KEY"] = "x"
        os.environ["BOCHA_SEARCH_DISABLED"] = "true"
        self.assertFalse(self._mk().is_configured())

    def test_cap_reads_env_with_default(self):
        os.environ.pop("BOCHA_DAILY_CAP", None)
        self.assertEqual(self._mk().cap(), 200)
        os.environ["BOCHA_DAILY_CAP"] = "50"
        self.assertEqual(self._mk().cap(), 50)


class TestDefaultRouter(unittest.TestCase):
    """验证「配哪个 key 用哪个」的灵活性：未配全跳过、配一个就启用。"""

    def setUp(self):
        self._saved = dict(os.environ)
        for k in ("BOCHA_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY", "BAIDU_QIANFAN_API_KEY"):
            os.environ.pop(k, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_unconfigured_when_no_keys(self):
        self.assertFalse(search_router.default_router().is_configured())

    def test_becomes_configured_with_one_key(self):
        os.environ["BOCHA_API_KEY"] = "x"
        self.assertTrue(search_router.default_router().is_configured())


if __name__ == "__main__":
    unittest.main()

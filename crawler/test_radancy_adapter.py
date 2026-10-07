import json
import os
import re
import unittest
from unittest import mock

import httpx

from adapters.radancy import RadancyAdapter

SOURCE = "https://careers.loreal.com/en/search-jobs/China/3456/2/1814991/35/105/50/2"
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "radancy_loreal_search_p1.html")


def _fixture() -> str:
    with open(FIXTURE, encoding="utf-8") as fh:
        return fh.read()


def _page(ids, total, total_pages, per_page=2, city="Shanghai", country="China"):
    cards = "".join(
        f'<li class="search-results-list__item"><a class="search-results-list__job-link" '
        f'href="/en/job/{city.lower()}/job-{i}/3456/{i}" data-job-id="{i}">'
        f'<h3 class="search-results-list__job-title">Job &amp; {i}</h3>'
        f'<span class="search-results-list__job-info job-location">{city}, {city}, {country}</span></a></li>'
        for i in ids
    )
    return (f'<section id="search-results" data-total-results="{total}" data-total-job-results="{total}" '
            f'data-total-pages="{total_pages}" data-records-per-page="{per_page}"></section>'
            f'<ul id="search-results-jobs">{cards}</ul>')


class FakeClient:
    """按 ?p=N 返回预置页；值为异常实例则抛出。"""
    def __init__(self, pages, **kwargs):
        self.pages = pages
        self.requested = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        page = int(re.search(r"[?&]p=(\d+)", url).group(1))
        self.requested.append(page)
        body = self.pages.get(page, _page([], 0, 0))
        if isinstance(body, Exception):
            raise body
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))


def _adapter(pages):
    ad = RadancyAdapter()
    ad.timeout = 5
    client = FakeClient(pages)
    ad._client = lambda **kw: client
    ad._fake = client
    return ad


class RadancyParseTest(unittest.TestCase):
    def test_parse_real_fixture(self):
        jobs = RadancyAdapter().parse(_fixture())
        self.assertEqual(len(jobs), 4)
        first = jobs[0]
        self.assertTrue(first.title)
        self.assertEqual(first.location, "Shanghai, Shanghai Municipality, China")
        self.assertTrue(first.jd_url.startswith("https://localhost/en/job/shanghai/") or
                        first.jd_url.startswith("/en/job/"))

    def test_parse_absolutizes_with_page_url(self):
        jobs = RadancyAdapter()._parse_cards(_fixture(), SOURCE + "?p=1")
        self.assertTrue(all(j.jd_url.startswith("https://careers.loreal.com/en/job/") for j in jobs))
        self.assertEqual(len({j.jd_url for j in jobs}), 4)

    def test_results_meta(self):
        from adapters.radancy import _results_meta
        self.assertEqual(_results_meta(_fixture()), (326, 22, 15))
        self.assertEqual(_results_meta("<html>home</html>"), (None, None, None))

    def test_foreign_country_is_dropped_unknown_kept(self):
        ad = RadancyAdapter()
        ad.regions = ["CN"]
        html = (_page([1], 3, 1, city="Shanghai") +
                _page([2], 3, 1, city="New York", country="United States") +
                _page([3], 3, 1, city="Dunhua", country="China"))
        jobs = ad.parse(html)
        self.assertEqual(sorted(j.title for j in jobs), ["Job & 1", "Job & 3"])


class RadancyFetchTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch("adapters.base.time.sleep")
        p.start()
        self.addCleanup(p.stop)

    def test_paginates_to_total_and_marks_complete(self):
        ad = _adapter({1: _page([1, 2], 5, 3), 2: _page([3, 4], 5, 3), 3: _page([5], 5, 3)})
        jobs = ad.parse(ad.fetch(SOURCE))
        self.assertEqual([j.title for j in jobs], [f"Job & {i}" for i in range(1, 6)])
        self.assertEqual(ad.reported_total, 5)
        self.assertTrue(ad.fetch_complete)
        self.assertEqual(ad._fake.requested, [1, 2, 3])   # 首页复用缓存，不重复请求

    def test_short_page_does_not_end_pagination_early(self):
        # 第 2 页只回 1 条（限流/瞬时短页），但总数/总页数表明还有第 3 页。
        ad = _adapter({1: _page([1, 2], 5, 3), 2: _page([3], 5, 3), 3: _page([4, 5], 5, 3)})
        jobs = ad.parse(ad.fetch(SOURCE))
        self.assertEqual(len(jobs), 5)
        self.assertEqual(ad._fake.requested, [1, 2, 3])

    def test_later_page_failure_keeps_partial_and_marks_incomplete(self):
        ad = _adapter({1: _page([1, 2], 6, 3), 2: httpx.ConnectError("boom")})
        jobs = ad.parse(ad.fetch(SOURCE))
        self.assertEqual(len(jobs), 2)
        self.assertEqual(ad.reported_total, 6)
        self.assertFalse(ad.fetch_complete)

    def test_first_page_without_cards_raises(self):
        ad = _adapter({1: "<html><body>home page</body></html>"})
        with self.assertRaises(RuntimeError):
            ad.fetch(SOURCE)

    def test_http_error_on_first_page_raises(self):
        ad = RadancyAdapter()
        ad.timeout = 5

        class Resp404(FakeClient):
            def get(self, url):
                return httpx.Response(404, text="x", request=httpx.Request("GET", url))
        ad._client = lambda **kw: Resp404({})
        with self.assertRaises(httpx.HTTPStatusError):
            ad.fetch(SOURCE)

    def test_respects_max_pages(self):
        ad = _adapter({i: _page([2 * i - 1, 2 * i], 100, 50) for i in range(1, 6)})
        ad.MAX_PAGES = 2
        jobs = ad.parse(ad.fetch(SOURCE))
        self.assertEqual(len(jobs), 4)
        self.assertFalse(ad.fetch_complete)

    def test_page_url_keeps_existing_query(self):
        self.assertEqual(RadancyAdapter._page_url(SOURCE + "?x=1", 3), SOURCE + "?x=1&p=3")


if __name__ == "__main__":
    unittest.main()

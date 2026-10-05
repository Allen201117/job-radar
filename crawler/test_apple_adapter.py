import json
import re
import unittest

from adapters.apple import AppleAdapter


class AppleAdapterTests(unittest.TestCase):
    def test_parses_public_search_page_hydration_data(self):
        hydration = {
            "loaderData": {
                "search": {
                    "searchResults": [
                        {
                            "id": "200664580-3956",
                            "postingTitle": "Technical Product Manager",
                            "transformedPostingTitle": "technical-product-manager",
                            "team": {"teamCode": "CORSV"},
                            "locations": [{"name": "Sunnyvale"}],
                            "jobSummary": "Build official Apple Store Online products.",
                            "postingDate": "May 21, 2026",
                            "type": "REQ",
                        }
                    ]
                }
            }
        }
        html = (
            "<script>window.__staticRouterHydrationData = JSON.parse("
            + json.dumps(json.dumps(hydration))
            + ");</script>"
        )

        jobs = AppleAdapter().parse(html)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Technical Product Manager")
        self.assertEqual(jobs[0].location, "Sunnyvale")
        self.assertEqual(
            jobs[0].jd_url,
            "https://jobs.apple.com/en-us/details/200664580-3956/technical-product-manager?team=CORSV",
        )


if __name__ == "__main__":
    unittest.main()


class ApplePaginationTest(unittest.TestCase):
    """回归守卫：Apple 必须翻全，不能只发几个写死关键词各取首页。

    2026-07-28 实测：旧实现发 3 个写死关键词（software / machine learning / data）各取首页，
    每轮固定只拿 60 条，而库里已有 1041 条 active → 3 天刷新率仅 11%，全库最差之一。
    live 验证 hydration 里有 totalRecords（限美国 4636 / 全球 6047），`?page=N` 每页 20 条、
    页间零重叠 → 改成空关键词全量枚举 + 逐页翻到底后，实跑 60 → 4634 岗、fetch_complete=True。
    """

    PAGE_SIZE = 20

    def _fake_get(self, total):
        """按 ?page=N 造 hydration 页面；记录请求过的 URL 用来断言真的翻了页。"""
        seen = []

        class FakeResp:
            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                return None

        def fake_get(url, **_kw):
            seen.append(url)
            page = 1
            match = re.search(r"[?&]page=(\d+)", url)
            if match:
                page = int(match.group(1))
            start = (page - 1) * ApplePaginationTest.PAGE_SIZE
            rows = [{"id": f"REQ-{i}", "postingTitle": f"Engineer {i}",
                     "transformedPostingTitle": f"engineer-{i}"}
                    for i in range(start, min(start + ApplePaginationTest.PAGE_SIZE, total))]
            hydration = {"loaderData": {"search": {"searchResults": rows,
                                                   "totalRecords": total}}}
            encoded = json.dumps(json.dumps(hydration))
            return FakeResp(
                "<script>window.__staticRouterHydrationData = JSON.parse("
                + encoded + ");</script>")

        return fake_get, seen

    def test_fetches_every_page_not_just_the_first(self):
        fake_get, seen = self._fake_get(55)
        adapter = AppleAdapter()
        import adapters.apple as mod
        orig, mod.httpx.get = mod.httpx.get, fake_get
        try:
            jobs = adapter.parse(adapter.fetch("https://jobs.apple.com/en-us/search"))
        finally:
            mod.httpx.get = orig

        self.assertEqual(len(jobs), 55, "55 个岗必须全抓到，不能停在首页 20 条")
        self.assertEqual(adapter.reported_total, 55)
        self.assertTrue(adapter.fetch_complete)
        self.assertGreaterEqual(len(seen), 3, f"没有逐页翻，只请求了 {seen}")

    def test_empty_board_raises_instead_of_silent_success(self):
        """totalRecords=0 / 0 行必须抛错记 failed，不许记 success + 抓全。"""
        fake_get, _ = self._fake_get(0)
        adapter = AppleAdapter()
        import adapters.apple as mod
        orig, mod.httpx.get = mod.httpx.get, fake_get
        try:
            with self.assertRaises(RuntimeError):
                adapter.fetch("https://jobs.apple.com/en-us/search")
        finally:
            mod.httpx.get = orig
        self.assertFalse(getattr(adapter, "fetch_complete", False))

    def test_enumerates_with_blank_search_not_hardcoded_keywords(self):
        """写死关键词天然带偏且互相重叠；空关键词才是全量枚举。"""
        fake_get, seen = self._fake_get(5)
        adapter = AppleAdapter()
        import adapters.apple as mod
        orig, mod.httpx.get = mod.httpx.get, fake_get
        try:
            adapter.fetch("https://jobs.apple.com/en-us/search")
        finally:
            mod.httpx.get = orig

        self.assertTrue(seen)
        for keyword in ("machine+learning", "machine%20learning", "search=software"):
            self.assertTrue(all(keyword not in u for u in seen),
                            f"仍在用写死关键词 {keyword}: {seen[:3]}")


class AppleMidPageRetryTest(unittest.TestCase):
    """2026-10-03 起 CI 上每轮只抓到 20~280 / ~4,500 个岗：中途某页瞬时失败 / 回空页，
    paginate_all 就地收尾。中途页要退避重试；重试用尽仍坏，才按原语义截断并标没抓全。"""

    def _run(self, glitches, total=55):
        fake_get, seen = ApplePaginationTest()._fake_get(total)
        calls = {}

        def flaky_get(url, **kw):
            page = int(re.search(r"[?&]page=(\d+)", url).group(1))
            calls[page] = calls.get(page, 0) + 1
            mode = glitches.get(page)
            if mode and calls[page] <= mode[1]:
                if mode[0] == "raise":
                    raise RuntimeError("HTTP 503")
                return fake_get(url.replace(f"page={page}", "page=999"), **kw)  # 空页
            return fake_get(url, **kw)

        adapter = AppleAdapter()
        adapter.PAGE_RETRY_BACKOFF = (0, 0, 0)
        import adapters.apple as mod
        orig, mod.httpx.get = mod.httpx.get, flaky_get
        try:
            jobs = adapter.parse(adapter.fetch("https://jobs.apple.com/en-us/search"))
        finally:
            mod.httpx.get = orig
        return adapter, jobs, calls

    def test_transient_error_mid_page_is_retried(self):
        adapter, jobs, calls = self._run({2: ("raise", 2)})
        self.assertEqual(len(jobs), 55)
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(calls[2], 3)

    def test_transient_empty_mid_page_is_retried(self):
        adapter, jobs, _ = self._run({2: ("empty", 1)})
        self.assertEqual(len(jobs), 55)
        self.assertTrue(adapter.fetch_complete)

    def test_persistent_mid_page_failure_keeps_rows_and_marks_incomplete(self):
        adapter, jobs, calls = self._run({2: ("raise", 99)})
        self.assertEqual(len(jobs), 20)
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(calls[2], 4)

    def test_first_page_error_is_not_retried(self):
        with self.assertRaises(RuntimeError):
            self._run({1: ("raise", 99)})

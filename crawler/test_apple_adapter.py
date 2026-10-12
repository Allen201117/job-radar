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


def _loc(name, iso3=None):
    loc = {"name": name}
    if iso3:
        loc["countryID"] = f"iso-country-{iso3}"
    return loc


def _row(*locations):
    return {"id": "200686987-3154", "postingTitle": "US-Manager", "team": {"teamCode": "APPST"},
            "locations": list(locations), "type": "REQ"}


class AppleDeclaredCountryTest(unittest.TestCase):
    """列表行的 locations[].countryID 是 Apple 自报的国家，adapter 必须交给 RawJob.country_code。

    2026-10-12 香港库实测：这条源 4,773 个在招岗里 291 个 country_code 为空、job_scope=domestic，
    地点是 155 种门店 / 园区 / 城市名（Cambridge 20 / Maiden 13 / Prineville 13 / Melbourne 7 /
    Bellevue Square 6 / Vancouver 4 / Toledo 2 …）。搜索本身只查美国，每一行都带
    countryID='iso-country-USA'，adapter 只取了 name → 判不出国家 → 按源的 regions（CN）猜成国内岗。
    """

    def _parse(self, *locations):
        import json as _json
        return AppleAdapter().parse(_json.dumps([_row(*locations)]))[0]

    def _normalized(self, raw, regions=("CN",)):
        import normalizer
        job = normalizer.normalize(raw, source_id="s", company="Apple", regions=list(regions))
        return job["location"], job["country_code"], job["job_scope"]

    def test_store_name_without_a_country_uses_the_country_apple_reports(self):
        for name in ("Cambridge", "Maiden", "Bellevue Square", "Anchorage 5th Avenue Mall"):
            raw = self._parse(_loc(name, "USA"))
            self.assertEqual(raw.country_code, "US", name)
            self.assertEqual(self._normalized(raw), (name, "US", "overseas"), name)

    def test_same_name_in_another_country_follows_the_report_not_the_name(self):
        # Cambridge（美国麻省 / 英国）、Melbourne（佛州 / 澳大利亚）、Vancouver（华盛顿州 / 加拿大）：
        # 名字一个字不差，国家只能问对方。
        for name, iso3, iso2 in (("Cambridge", "GBR", "GB"), ("Melbourne", "AUS", "AU"),
                                 ("Vancouver", "CAN", "CA"), ("Toledo", "ESP", "ES")):
            self.assertEqual(self._parse(_loc(name, iso3)).country_code, iso2, name)
            self.assertEqual(self._parse(_loc(name, "USA")).country_code, "US", name)

    def test_reported_greater_china_keeps_the_job_domestic_even_on_an_overseas_only_source(self):
        # 反方向：门店名判不出国家、源又是纯海外 regions 时，原本会按 regions 猜成境外。
        raw = self._parse(_loc("Taikoo Li Sanlitun", "CHN"))
        self.assertEqual(raw.country_code, "CN")
        self.assertEqual(self._normalized(raw, regions=("US",)), ("Taikoo Li Sanlitun", "CN", "domestic"))
        self.assertEqual(self._parse(_loc("Festival Walk", "HKG")).country_code, "HK")

    def test_any_greater_china_location_wins_on_a_multi_location_row(self):
        raw = self._parse(_loc("Cupertino", "USA"), _loc("Pudong", "CHN"))
        self.assertEqual(raw.country_code, "CN")

    def test_several_overseas_countries_report_the_first(self):
        self.assertEqual(self._parse(_loc("Cambridge", "USA"), _loc("Cork", "IRL")).country_code, "US")

    def test_missing_or_unknown_report_gives_nothing(self):
        # 没报 / 报的不是 ISO 码 / 多个地点里有一个没报：都不替对方猜，回到改前的行为。
        self.assertIsNone(self._parse(_loc("Cambridge")).country_code)
        self.assertIsNone(self._parse({"name": "Cambridge", "countryID": "iso-country-ZZZ"}).country_code)
        self.assertIsNone(self._parse({"name": "Cambridge", "countryID": "USA"}).country_code)
        self.assertIsNone(self._parse({"name": "Cambridge", "countryID": None}).country_code)
        self.assertIsNone(self._parse(_loc("Cambridge", "USA"), _loc("Somewhere")).country_code)
        self.assertEqual(self._normalized(self._parse(_loc("Cambridge"))), ("Cambridge", None, "domestic"))

    def test_location_text_and_title_are_untouched(self):
        raw = self._parse(_loc("Cupertino", "USA"), _loc("Austin", "USA"))
        self.assertEqual(raw.location, "Cupertino, Austin")
        self.assertEqual(raw.title, "US-Manager")

    def test_iso3_table_covers_exactly_the_iso2_codes_normalize_accepts(self):
        import geo
        from adapters.apple import _ISO3_TO_ISO2
        self.assertEqual(sorted(_ISO3_TO_ISO2.values()), sorted(geo.ISO_ALPHA2_CODES))  # 一一对应，不多不少
        for iso3 in _ISO3_TO_ISO2:
            self.assertRegex(iso3, r"^[A-Z]{3}$")

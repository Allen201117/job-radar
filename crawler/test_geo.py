import unittest

from geo import derive_country_code, derive_job_scope, location_in_scope


class TestDeriveCountryCode(unittest.TestCase):
    def test_china_cities(self):
        self.assertEqual(derive_country_code("Beijing, China"), "CN")
        self.assertEqual(derive_country_code("上海"), "CN")
        self.assertEqual(derive_country_code("Hong Kong"), "HK")

    def test_us_cities(self):
        self.assertEqual(derive_country_code("New York, NY"), "US")
        self.assertEqual(derive_country_code("Sunnyvale, CA, United States"), "US")
        self.assertEqual(derive_country_code("Seattle"), "US")

    def test_singapore(self):
        self.assertEqual(derive_country_code("Singapore"), "SG")

    def test_remote_with_country(self):
        cases = (
            ("Remote - US", "US"),
            ("Remote, US", "US"),
            ("US - Remote", "US"),
            ("US Remote", "US"),
            ("Remote (USA)", "US"),
            ("Remote - United States", "US"),
            ("Remote, USA", "US"),
            ("Remote (US)", "US"),
            ("Remote (U.S.)", "US"),
            ("Remote - Singapore", "SG"),
            ("Remote, SG", "SG"),
            ("Singapore - Remote", "SG"),
            ("Remote (Singapore)", "SG"),
        )
        for location, expected in cases:
            with self.subTest(location=location):
                self.assertEqual(derive_country_code(location), expected)

    def test_country_code_tokens_do_not_match_substrings(self):
        self.assertEqual(derive_country_code("Business Analyst, Beijing"), "CN")
        self.assertEqual(derive_country_code("Focus Group, Shanghai"), "CN")
        self.assertIsNone(derive_country_code("Belarus"))

    def test_bare_remote_unknown(self):
        self.assertIsNone(derive_country_code("Remote"))

    def test_unknown(self):
        self.assertIsNone(derive_country_code(""))
        self.assertIsNone(derive_country_code("Multiple Locations"))


class TestDeriveJobScope(unittest.TestCase):
    def test_greater_china_is_domestic(self):
        self.assertEqual(derive_job_scope("Beijing, China"), "domestic")
        self.assertEqual(derive_job_scope("Hong Kong"), "domestic")
        self.assertEqual(derive_job_scope("澳门"), "domestic")

    def test_overseas(self):
        self.assertEqual(derive_job_scope("New York, NY"), "overseas")
        self.assertEqual(derive_job_scope("Singapore"), "overseas")
        for location in ("Remote - US", "US Remote", "Remote (USA)", "Remote - Singapore"):
            with self.subTest(location=location):
                self.assertEqual(derive_job_scope(location), "overseas")

    def test_bare_remote_defaults_domestic(self):
        self.assertEqual(derive_job_scope("Remote"), "domestic")

    def test_unknown_defaults_domestic(self):
        self.assertEqual(derive_job_scope(""), "domestic")


class TestLocationInScope(unittest.TestCase):
    def test_default_cn_matches_today(self):
        self.assertTrue(location_in_scope("Beijing, China", {"CN"}))
        self.assertTrue(location_in_scope("Hong Kong", {"CN"}))
        self.assertFalse(location_in_scope("New York", {"CN"}))
        self.assertFalse(location_in_scope("Singapore", {"CN"}))

    def test_overseas_regions(self):
        self.assertTrue(location_in_scope("New York", {"US"}))
        self.assertTrue(location_in_scope("Singapore", {"SG"}))
        self.assertFalse(location_in_scope("London", {"US", "SG"}))

    def test_remote_region(self):
        self.assertTrue(location_in_scope("Remote - US", {"US"}))
        self.assertTrue(location_in_scope("Remote", {"Remote"}))

    def test_multi_region(self):
        self.assertTrue(location_in_scope("Beijing", {"CN", "US", "SG"}))
        self.assertTrue(location_in_scope("Singapore", {"CN", "US", "SG"}))

    def test_taiwan_is_not_in_any_active_scope(self):
        for loc in ("Taiwan", "Taipei, Taiwan", "台北, 台湾"):
            with self.subTest(loc=loc):
                self.assertFalse(location_in_scope(loc, {"CN"}))
                self.assertFalse(location_in_scope(loc, {"US", "SG", "Remote"}))
                self.assertFalse(location_in_scope(loc, {"CN", "US", "SG", "Remote"}))


if __name__ == "__main__":
    unittest.main()


class TaiwanWithChinaSuffixTest(unittest.TestCase):
    """台湾写成「Taiwan, Province of China」时不许被当成 CN 放行。

    2026-07-28 Siemens 改成翻全分页后实测捞进 5 个台北岗才暴露：TW 压根不在 _COUNTRY_TOKENS 里，
    这种写法含 "china" → derive_country_code 判成 CN → 进了国内看板。
    上面的 test_taiwan_is_not_in_any_active_scope 只覆盖不含 china 字样的写法（code=None
    自然落 False），盖不住这个洞。
    """

    VARIANTS = (
        "Taipei, Taipei shih, Taiwan, Province of China",
        "Taiwan, Province of China",
        "Hsinchu, Taiwan, Province of China",
        "台北, 台湾, 中国",
    )

    def test_not_in_scope_for_any_region_set(self):
        for loc in self.VARIANTS:
            with self.subTest(loc=loc):
                self.assertFalse(location_in_scope(loc, {"CN"}))
                self.assertFalse(location_in_scope(loc, {"CN", "US", "SG", "Remote"}))

    def test_country_code_is_tw_not_cn(self):
        for loc in self.VARIANTS:
            with self.subTest(loc=loc):
                self.assertEqual(derive_country_code(loc), "TW")

    def test_mainland_and_hongkong_still_work(self):
        # 别为了拦台湾误伤大陆/港澳
        self.assertEqual(derive_country_code("Shanghai, Shanghai Shi, China"), "CN")
        self.assertEqual(derive_country_code("Wuxi, Jiangsu Sheng, China"), "CN")
        self.assertEqual(derive_country_code("Hong Kong"), "HK")
        self.assertTrue(location_in_scope("Wuxi, Jiangsu Sheng, China", {"CN"}))
        self.assertTrue(location_in_scope("Hong Kong", {"CN"}))


class BareRemoteScopeBySourceRegionsTest(unittest.TestCase):
    """裸「远程」按**源的 regions** 兜底判归属。

    2026-09-04 实测：全库 9,873 个「裸远程 + 判 domestic」的在招岗里，**9,863 个来自
    regions 不含 CN 的海外源**（AbbVie 1,512 / ServiceNow 576 / Samsara 483 / NVIDIA 360…），
    只有 10 个来自纯 CN 源 —— 用户筛「国内」时看到的是一片美国远程岗。分离度 99.9%。
    （带国家写法的「Remote - US」早已由 f306271 修好，这里补的是裸远程那一半。）
    """

    def test_bare_remote_from_overseas_source_is_overseas(self):
        self.assertEqual(derive_job_scope("远程", {"US", "SG", "Remote"}), "overseas")
        self.assertEqual(derive_job_scope("Remote", {"US", "SG", "Remote"}), "overseas")

    def test_bare_remote_from_source_including_cn_stays_domestic(self):
        """源含 CN 就可能是真国内远程岗，不许判 overseas（宁可漏判不可错杀）。"""
        self.assertEqual(derive_job_scope("远程", {"CN", "US", "SG", "Remote"}), "domestic")
        self.assertEqual(derive_job_scope("远程", {"CN"}), "domestic")

    def test_omitting_regions_keeps_legacy_behaviour(self):
        """老调用方不传 regions → 行为一字不变，避免这次改动波及别的链路。"""
        self.assertEqual(derive_job_scope("远程"), "domestic")
        self.assertEqual(derive_job_scope(""), "domestic")

    def test_explicit_location_always_wins_over_source_regions(self):
        """地点能抽出国家时以地点为准 —— 海外源里的北京岗仍是国内岗，反之亦然。"""
        self.assertEqual(derive_job_scope("Beijing, China", {"US", "SG"}), "domestic")
        self.assertEqual(derive_job_scope("香港", {"US"}), "domestic")
        self.assertEqual(derive_job_scope("New York, NY", {"CN", "US"}), "overseas")

    def test_unknown_location_from_overseas_source_is_overseas(self):
        """空地点 / Multiple Locations 与裸远程同理，都走源兜底。"""
        self.assertEqual(derive_job_scope("", {"US"}), "overseas")
        self.assertEqual(derive_job_scope("Multiple Locations", {"US"}), "overseas")

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

import unittest

import normalizer
from adapters.base import RawJob


class NormalizerGeoFieldsTest(unittest.TestCase):
    def _job(self, location):
        return RawJob(
            company="",
            title="Software Engineer",
            location=location,
            summary="Build reliable systems.",
            jd_url="https://example.com/jobs/1",
            apply_url="https://example.com/jobs/1",
        )

    def test_normalize_derives_overseas_geo_fields(self):
        job = normalizer.normalize(self._job("New York, NY"), source_id="src-1", company="Acme")

        self.assertEqual(job["country_code"], "US")
        self.assertEqual(job["job_scope"], "overseas")

    def test_normalize_derives_domestic_geo_fields(self):
        job = normalizer.normalize(self._job("Beijing"), source_id="src-1", company="Acme")

        self.assertEqual(job["country_code"], "CN")
        self.assertEqual(job["job_scope"], "domestic")


class RemoteAliasKeepsCountryTest(unittest.TestCase):
    """normalize_city 把含 remote 的串整串折叠成「远程」；国家/范围必须按折叠前的原文判。

    2026-09-23 实测：workday 在招岗 4,383 行存成「远程」且判 domestic，原文是
    United-States---Remote / Remote-Mexico / UK-Remote …（regions 含 CN 的外企源）。
    """

    CN_US = ["CN", "US", "SG", "Remote"]
    US_ONLY = ["US", "SG", "Remote"]

    def _norm(self, location, regions):
        raw = RawJob(company="", title="Engineer", location=location,
                     jd_url="https://example.com/jobs/1")
        return normalizer.normalize(raw, source_id="s", company="Acme", regions=regions)

    def test_remote_with_foreign_country_is_overseas_even_on_cn_source(self):
        for loc, code in (("United, States, , , Remote", "US"),
                          ("USA, , , Remote", "US"),
                          ("Remote Germany", None),        # smartrecruiters 出口写法
                          ("UK, Remote", "GB"),
                          ("Remote, Mexico", None)):
            job = self._norm(loc, self.CN_US)
            self.assertEqual(job["location"], "远程", loc)          # 展示列不动
            self.assertEqual(job["country_code"], code, loc)
            self.assertEqual(job["job_scope"], "overseas", loc)

    def test_china_remote_stays_domestic(self):
        for loc in ("China, , , Remote", "Remote China"):
            job = self._norm(loc, self.CN_US)
            self.assertEqual(job["location"], "远程", loc)
            self.assertEqual(job["country_code"], "CN", loc)
            self.assertEqual(job["job_scope"], "domestic", loc)
        # 香港别名排在「远程」前面，折叠成「香港」本身就判得出 HK，不走原文
        job = self._norm("Hong Kong, , , Remote", self.CN_US)
        self.assertEqual((job["location"], job["country_code"], job["job_scope"]), ("香港", "HK", "domestic"))

    def test_bare_remote_unchanged(self):
        # 原文也说不出国家 → 行为与改前逐字一致：按 source.regions 兜底
        self.assertEqual(self._norm("Remote", self.CN_US)["job_scope"], "domestic")
        self.assertEqual(self._norm("Remote", self.US_ONLY)["job_scope"], "overseas")
        self.assertIsNone(self._norm("Remote", self.CN_US)["country_code"])

    def test_non_remote_alias_path_untouched(self):
        # 别名能判出国家的（大陆城市 / 香港 / 新加坡）一律走别名后的文本，与改前相同
        self.assertEqual(self._norm("Shanghai, China", self.CN_US)["country_code"], "CN")
        self.assertEqual(self._norm("Singapore, Singapore", self.CN_US)["country_code"], "SG")
        self.assertIsNone(self._norm("Multiple Locations", self.CN_US)["location"])

    def test_only_remote_alias_target_lacks_country(self):
        # geo_basis 只改变被折叠成「远程」的行，前提是其它别名目标都判得出国家。
        # 谁往 CITY_ALIASES 里加了一个判不出国家的目标值，这条就红，逼他重新评估影响面。
        missing = {v for v in normalizer.CITY_ALIASES.values()
                   if normalizer.derive_country_code(v) is None}
        self.assertEqual(missing, {"远程"})


if __name__ == "__main__":
    unittest.main()

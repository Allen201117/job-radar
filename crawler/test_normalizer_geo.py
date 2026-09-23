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

    def test_empty_location_falls_back_to_title_city(self):
        # 2026-09-23：康龙化成 / 万物云等源把城市写在标题里、location 给空，/today 把它们当「城市未知」
        # 放给所有城市的用户（上海·杭州用户的 7 张卡全在外地）。
        raw = RawJob(company="", title="有机合成研究员-西安", location=None, summary="负责合成路线设计。",
                     jd_url="https://example.com/jobs/2", apply_url="https://example.com/jobs/2")
        job = normalizer.normalize(raw, source_id="src-1", company="Acme")

        self.assertEqual(job["location"], "西安")
        self.assertEqual(job["country_code"], "CN")
        self.assertEqual(job["job_scope"], "domestic")

    def test_title_city_never_overrides_adapter_location(self):
        raw = RawJob(company="", title="有机合成研究员-西安", location="北京", summary="x",
                     jd_url="https://example.com/jobs/3", apply_url="https://example.com/jobs/3")
        job = normalizer.normalize(raw, source_id="src-1", company="Acme")

        self.assertEqual(job["location"], "北京")

    def test_title_fallback_does_not_change_content_hash(self):
        # 派生值是标题的纯函数，不携带新信息；hash 按 adapter 给的地点算，上线不会让存量行的 hash 集体翻一遍。
        raw = RawJob(company="", title="有机合成研究员-西安", location=None, summary="x",
                     jd_url="https://example.com/jobs/4", apply_url="https://example.com/jobs/4")
        job = normalizer.normalize(raw, source_id="src-1", company="Acme")

        self.assertEqual(job["content_hash"], normalizer.make_content_hash("有机合成研究员-西安", None, "x"))

    def test_nationwide_title_stays_unknown(self):
        raw = RawJob(company="", title="城市经理（销售方向）-全国", location="", summary="x",
                     jd_url="https://example.com/jobs/5", apply_url="https://example.com/jobs/5")
        job = normalizer.normalize(raw, source_id="src-1", company="Acme")

        self.assertIsNone(job["location"])


if __name__ == "__main__":
    unittest.main()

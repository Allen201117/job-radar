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


if __name__ == "__main__":
    unittest.main()

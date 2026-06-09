import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from adapters.phenom import PhenomAdapter


def _wrap(jobs):
    return json.dumps({"_host": "https://careers.amd.com", "jobs": jobs})


class TestPhenomAdapter(unittest.TestCase):
    def test_china_filter_jdurl_and_slug_fallback(self):
        payload = _wrap([
            {"slug": "86295", "title": "BD Manager", "city": "Beijing", "state": "Beijing", "country": "China"},
            {"slug": "99", "title": "US Role", "city": "Austin", "state": "Texas", "country": "United States"},
            {"slug": "100", "title": "HK Role", "city": "Central", "country": "Hong Kong"},
            {"slug": "", "req_id": "77", "title": "Slug from req_id", "city": "Shanghai", "country": "China"},
        ])
        jobs = PhenomAdapter().parse(payload)
        urls = {j.jd_url for j in jobs}
        # jd_url = {host}/jobs/{slug}，公开详情页（非 icims apply_url）
        self.assertIn("https://careers.amd.com/jobs/86295", urls)
        self.assertIn("https://careers.amd.com/jobs/100", urls)   # HK 保留
        self.assertIn("https://careers.amd.com/jobs/77", urls)    # slug 缺则用 req_id
        self.assertNotIn("https://careers.amd.com/jobs/99", urls)  # 非华岗丢弃
        self.assertEqual(len(jobs), 3)

    def test_skip_missing_title_or_slug(self):
        payload = _wrap([
            {"slug": "1", "title": "", "country": "China"},
            {"slug": "", "req_id": "", "title": "No id", "country": "China"},
        ])
        self.assertEqual(PhenomAdapter().parse(payload), [])

    def test_parse_garbage_returns_empty(self):
        self.assertEqual(PhenomAdapter().parse("not json"), [])


if __name__ == "__main__":
    unittest.main()

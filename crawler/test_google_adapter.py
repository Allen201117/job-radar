import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from adapters.google import GoogleAdapter


class TestGoogleAdapter(unittest.TestCase):
    def test_parse_china_filter_jdurl_and_dedup(self):
        payload = json.dumps({"cards": [
            {"href": "jobs/results/111-recruiting-manager?location=China", "title": "Recruiting Manager",
             "text": "Recruiting Manager | corporate_fare | Google | place | Shanghai, China | bla"},
            {"href": "jobs/results/222-us-role?location=United+States", "title": "US Role",
             "text": "US Role | corporate_fare | Google | place | Mountain View, United States |"},
            {"href": "jobs/results/333-hk-role", "title": "HK Role",
             "text": "HK Role | place | Hong Kong |"},
            {"href": "jobs/results/111-recruiting-manager?location=China", "title": "Recruiting Manager",
             "text": "dup | place | Shanghai, China |"},
        ]})
        jobs = GoogleAdapter().parse(payload)
        urls = {j.jd_url for j in jobs}
        self.assertIn("https://www.google.com/about/careers/applications/jobs/results/111-recruiting-manager", urls)
        self.assertTrue(any(u.endswith("333-hk-role") for u in urls))  # 香港保留
        self.assertFalse(any("222-us-role" in u for u in urls))        # 美国丢弃
        self.assertEqual(len(jobs), 2)                                  # 去重
        cn = next(j for j in jobs if j.jd_url.endswith("111-recruiting-manager"))
        self.assertEqual(cn.location, "Shanghai, China")

    def test_skip_missing_title_or_href(self):
        payload = json.dumps({"cards": [
            {"href": "jobs/results/1-x", "title": "", "text": "place | Beijing, China |"},
            {"href": "", "title": "No href", "text": "place | Beijing, China |"},
        ]})
        self.assertEqual(GoogleAdapter().parse(payload), [])

    def test_parse_garbage_returns_empty(self):
        self.assertEqual(GoogleAdapter().parse("not json"), [])


if __name__ == "__main__":
    unittest.main()

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from adapters.microsoft import MicrosoftAdapter


class TestMicrosoftAdapter(unittest.TestCase):
    def test_parse_china_filter_jdurl_and_dedup(self):
        payload = json.dumps({"positions": [
            {"id": 111, "displayJobId": "200007627", "name": "Datacenter Mgr",
             "locations": ["China, Hebei, Multiple Locations"]},
            {"id": 222, "displayJobId": "200001", "name": "SDE",
             "locations": ["Redmond, Washington, United States"]},
            {"id": 333, "displayJobId": "200002", "name": "PM", "locations": ["Hong Kong SAR"]},
            {"id": 111, "displayJobId": "200007627", "name": "Datacenter Mgr",
             "locations": ["China, Hebei"]},  # 同 id/jd_url 重复
        ]})
        jobs = MicrosoftAdapter().parse(payload)
        urls = {j.jd_url for j in jobs}
        # jd_url = jobs.careers.microsoft.com/.../job/{displayJobId}
        self.assertIn("https://jobs.careers.microsoft.com/global/en/job/200007627", urls)
        self.assertIn("https://jobs.careers.microsoft.com/global/en/job/200002", urls)  # 香港保留
        self.assertNotIn("https://jobs.careers.microsoft.com/global/en/job/200001", urls)  # 美国丢弃
        self.assertEqual(len(jobs), 2)  # 去重后 2 条

    def test_skip_missing_fields(self):
        payload = json.dumps({"positions": [
            {"id": 1, "name": "", "locations": ["China"]},
            {"id": "", "displayJobId": "", "name": "No id", "locations": ["China"]},
        ]})
        self.assertEqual(MicrosoftAdapter().parse(payload), [])

    def test_parse_garbage_returns_empty(self):
        self.assertEqual(MicrosoftAdapter().parse("not json"), [])


if __name__ == "__main__":
    unittest.main()

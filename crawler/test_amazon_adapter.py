import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from adapters.amazon import AmazonAdapter, _norm_loc


class TestAmazonAdapter(unittest.TestCase):
    def test_parse_china_filter_jdurl_and_chn_normalize(self):
        payload = json.dumps({"jobs": [
            {"title": "Sr. SDE", "normalized_location": "Shenzhen, CHN", "job_path": "/en/jobs/123/sr-sde"},
            {"title": "PM", "normalized_location": "Seattle, USA", "job_path": "/en/jobs/456/pm"},
            {"title": "Ops Manager", "normalized_location": "Hong Kong, HKG", "job_path": "/en/jobs/789/ops"},
            {"title": "No Path", "normalized_location": "Beijing, CHN", "job_path": ""},
        ]})
        jobs = AmazonAdapter().parse(payload)
        urls = {j.jd_url for j in jobs}
        # 在华岗保留（含 CHN 大陆与 HK），jd_url 拼成 amazon.jobs 绝对地址
        self.assertIn("https://www.amazon.jobs/en/jobs/123/sr-sde", urls)
        self.assertIn("https://www.amazon.jobs/en/jobs/789/ops", urls)
        # 非华岗丢弃；缺 job_path 丢弃
        self.assertNotIn("https://www.amazon.jobs/en/jobs/456/pm", urls)
        self.assertEqual(len(jobs), 2)
        # CHN 归一为 China，能过 is_china_location
        cn = next(j for j in jobs if j.jd_url.endswith("sr-sde"))
        self.assertIn("China", cn.location)
        self.assertNotIn("CHN", cn.location)

    def test_dedup_by_job_path(self):
        payload = json.dumps({"jobs": [
            {"title": "Dup", "normalized_location": "Shanghai, CHN", "job_path": "/en/jobs/1/dup"},
            {"title": "Dup", "normalized_location": "Shanghai, CHN", "job_path": "/en/jobs/1/dup"},
        ]})
        self.assertEqual(len(AmazonAdapter().parse(payload)), 1)

    def test_parse_garbage_returns_empty(self):
        self.assertEqual(AmazonAdapter().parse("not json"), [])
        self.assertEqual(AmazonAdapter().parse("[]"), [])

    def test_norm_loc(self):
        self.assertEqual(_norm_loc("Shenzhen, CHN"), "Shenzhen, China")
        self.assertEqual(_norm_loc("Beijing, CHN"), "Beijing, China")
        self.assertIsNone(_norm_loc(""))


if __name__ == "__main__":
    unittest.main()

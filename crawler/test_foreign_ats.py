"""Greenhouse / Lever 通用适配器 + 在华地点过滤的单测（纯解析，不打网络）。"""
import json
import unittest

import normalizer
from adapters.greenhouse import GreenhouseAdapter
from adapters.lever import LeverAdapter


class IsChinaLocationTest(unittest.TestCase):
    def test_china_variants(self):
        for loc in ["Beijing, China", "Shanghai", "深圳", "Hong Kong", "Greater China",
                    "Beijing; Shanghai; Shenzhen", "Foshan, China"]:
            self.assertTrue(normalizer.is_china_location(loc), loc)

    def test_non_china(self):
        for loc in ["San Francisco", "London", "Singapore", "Remote - US", "", None]:
            self.assertFalse(normalizer.is_china_location(loc), loc)


class GreenhouseParseTest(unittest.TestCase):
    def test_keeps_only_china_with_title_and_url(self):
        payload = json.dumps({"jobs": [
            {"title": "AI Engineer", "absolute_url": "https://boards.greenhouse.io/airbnb/jobs/1",
             "location": {"name": "Beijing, China"}, "updated_at": "2026-05-01T00:00:00Z",
             "content": "<p>do stuff</p>"},
            {"title": "SWE", "absolute_url": "https://boards.greenhouse.io/airbnb/jobs/2",
             "location": {"name": "San Francisco"}},                       # 非在华 -> 过滤
            {"title": "", "absolute_url": "https://boards.greenhouse.io/airbnb/jobs/3",
             "location": {"name": "Shanghai"}},                            # 无标题 -> 过滤
            {"title": "Data", "absolute_url": "",
             "location": {"name": "Shanghai"}},                            # 无链接 -> 过滤
        ]})
        jobs = GreenhouseAdapter().parse(payload)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "AI Engineer")
        self.assertEqual(jobs[0].location, "Beijing, China")
        self.assertEqual(jobs[0].jd_url, "https://boards.greenhouse.io/airbnb/jobs/1")
        self.assertEqual(jobs[0].posted_at, "2026-05-01")
        self.assertEqual(jobs[0].company, "")  # 由 sources.company 兜底

    def test_bad_json(self):
        self.assertEqual(GreenhouseAdapter().parse("not json"), [])


class LeverParseTest(unittest.TestCase):
    def test_keeps_only_china(self):
        payload = json.dumps([
            {"text": "Engineer", "hostedUrl": "https://jobs.lever.co/binance/abc",
             "categories": {"location": "Hong Kong", "team": "Engineering"},
             "createdAt": 1700000000000, "descriptionPlain": "desc"},
            {"text": "PM", "hostedUrl": "https://jobs.lever.co/binance/def",
             "categories": {"location": "London"}},                        # 非在华 -> 过滤
            {"text": "", "hostedUrl": "https://jobs.lever.co/binance/ghi",
             "categories": {"location": "Shanghai"}},                      # 无标题 -> 过滤
        ])
        jobs = LeverAdapter().parse(payload)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Engineer")
        self.assertEqual(jobs[0].location, "Hong Kong")
        self.assertEqual(jobs[0].job_type, "Engineering")
        self.assertEqual(jobs[0].jd_url, "https://jobs.lever.co/binance/abc")
        self.assertTrue(jobs[0].posted_at and jobs[0].posted_at.startswith("2023-"))

    def test_bad_json(self):
        self.assertEqual(LeverAdapter().parse("{}"), [])


if __name__ == "__main__":
    unittest.main()

"""Greenhouse / Lever 通用适配器 + 在华/remote 过滤的单测（纯解析，不打网络）。"""
import json
import unittest

import normalizer
from adapters.greenhouse import GreenhouseAdapter
from adapters.lever import LeverAdapter
from adapters.apple import AppleChinaAdapter


class IsChinaLocationTest(unittest.TestCase):
    def test_china_variants(self):
        for loc in ["Beijing, China", "Shanghai", "深圳", "Hong Kong", "Greater China",
                    "Beijing; Shanghai; Shenzhen", "Foshan, China"]:
            self.assertTrue(normalizer.is_china_location(loc), loc)

    def test_non_china(self):
        for loc in ["San Francisco", "London", "Singapore", "Remote - US", "", None]:
            self.assertFalse(normalizer.is_china_location(loc), loc)


class KeepForChinaRadarTest(unittest.TestCase):
    def test_keep(self):
        # 大中华区 + 不绑定海外的 remote
        for loc in ["Beijing, China", "Shanghai", "Hong Kong", "Greater China",
                    "Remote", "Remote - APAC", "远程", "Anywhere"]:
            self.assertTrue(normalizer.keep_for_china_radar(loc), loc)

    def test_drop_base_overseas(self):
        # base 海外（含海外 remote）
        for loc in ["San Francisco", "London", "Singapore", "Tokyo, Japan",
                    "Remote - US", "Remote, United States", "Remote (Canada)", "", None]:
            self.assertFalse(normalizer.keep_for_china_radar(loc), loc)


class GreenhouseParseTest(unittest.TestCase):
    def test_keeps_china_and_flexible_remote(self):
        payload = json.dumps({"jobs": [
            {"title": "AI Engineer", "absolute_url": "https://boards.greenhouse.io/airbnb/jobs/1",
             "location": {"name": "Beijing, China"}, "updated_at": "2026-05-01T00:00:00Z",
             "content": "<p>do stuff</p>"},
            {"title": "Remote SWE", "absolute_url": "https://boards.greenhouse.io/airbnb/jobs/2",
             "location": {"name": "Remote"}},                              # 不绑定海外的 remote -> 保留
            {"title": "US SWE", "absolute_url": "https://boards.greenhouse.io/airbnb/jobs/3",
             "location": {"name": "San Francisco"}},                       # base 海外 -> 过滤
            {"title": "US Remote", "absolute_url": "https://boards.greenhouse.io/airbnb/jobs/4",
             "location": {"name": "Remote - US"}},                         # 海外 remote -> 过滤
            {"title": "", "absolute_url": "https://boards.greenhouse.io/airbnb/jobs/5",
             "location": {"name": "Shanghai"}},                            # 无标题 -> 过滤
        ]})
        jobs = GreenhouseAdapter().parse(payload)
        titles = {j.title for j in jobs}
        self.assertEqual(titles, {"AI Engineer", "Remote SWE"})
        beijing = next(j for j in jobs if j.title == "AI Engineer")
        self.assertEqual(beijing.jd_url, "https://boards.greenhouse.io/airbnb/jobs/1")
        self.assertEqual(beijing.posted_at, "2026-05-01")
        self.assertEqual(beijing.company, "")  # 由 sources.company 兜底

    def test_bad_json(self):
        self.assertEqual(GreenhouseAdapter().parse("not json"), [])


class LeverParseTest(unittest.TestCase):
    def test_keeps_china_and_flexible_remote(self):
        payload = json.dumps([
            {"text": "Engineer", "hostedUrl": "https://jobs.lever.co/binance/abc",
             "categories": {"location": "Hong Kong", "team": "Engineering"},
             "createdAt": 1700000000000, "descriptionPlain": "desc"},
            {"text": "Remote PM", "hostedUrl": "https://jobs.lever.co/binance/rem",
             "categories": {"location": "Remote"}},                        # 保留
            {"text": "London PM", "hostedUrl": "https://jobs.lever.co/binance/def",
             "categories": {"location": "London"}},                        # base 海外 -> 过滤
            {"text": "", "hostedUrl": "https://jobs.lever.co/binance/ghi",
             "categories": {"location": "Shanghai"}},                      # 无标题 -> 过滤
        ])
        jobs = LeverAdapter().parse(payload)
        titles = {j.title for j in jobs}
        self.assertEqual(titles, {"Engineer", "Remote PM"})
        hk = next(j for j in jobs if j.title == "Engineer")
        self.assertEqual(hk.location, "Hong Kong")
        self.assertEqual(hk.job_type, "Engineering")
        self.assertTrue(hk.posted_at and hk.posted_at.startswith("2023-"))

    def test_bad_json(self):
        self.assertEqual(LeverAdapter().parse("{}"), [])


class AppleChinaParseTest(unittest.TestCase):
    def test_keeps_only_china_and_remote(self):
        rows = [
            {"postingTitle": "ML Engineer", "id": "1", "locations": [{"name": "Shanghai, China"}]},
            {"postingTitle": "ML Engineer US", "id": "2", "locations": [{"name": "Cupertino"}]},  # 海外 -> 过滤
            {"postingTitle": "Remote Role", "id": "3", "locations": [{"name": "Remote"}]},          # remote -> 保留
            {"postingTitle": "No Id", "locations": [{"name": "Beijing"}]},                          # 无 id -> 跳过
        ]
        jobs = AppleChinaAdapter().parse(json.dumps(rows))
        titles = {j.title for j in jobs}
        self.assertEqual(titles, {"ML Engineer", "Remote Role"})
        self.assertTrue(all(j.company == "Apple" for j in jobs))
        self.assertTrue(all("/details/" in j.jd_url for j in jobs))


if __name__ == "__main__":
    unittest.main()

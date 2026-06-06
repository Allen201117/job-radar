"""Greenhouse / Lever 通用适配器 + 在华/remote 过滤的单测（纯解析，不打网络）。"""
import json
import unittest

import normalizer
from adapters.greenhouse import GreenhouseAdapter
from adapters.lever import LeverAdapter
from adapters.ashby import AshbyAdapter
from adapters.smartrecruiters import SmartRecruitersAdapter
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


class PublishDateTest(unittest.TestCase):
    def test_coerce_iso_date(self):
        self.assertEqual(normalizer.coerce_iso_date(1700000000000), "2023-11-14")  # epoch ms
        self.assertEqual(normalizer.coerce_iso_date(1700000000), "2023-11-14")     # epoch s
        self.assertEqual(normalizer.coerce_iso_date("2026/05/30"), "2026-05-30")
        self.assertEqual(normalizer.coerce_iso_date("2026年5月3日"), "2026-05-03")
        self.assertIsNone(normalizer.coerce_iso_date(None))
        self.assertIsNone(normalizer.coerce_iso_date(""))
        self.assertIsNone(normalizer.coerce_iso_date("n/a"))

    def test_pick_publish_date_defensive(self):
        self.assertEqual(normalizer.pick_publish_date({"publish_time": 1700000000000}), "2023-11-14")
        self.assertEqual(normalizer.pick_publish_date({"update_time": "2026-05-30"}), "2026-05-30")
        self.assertIsNone(normalizer.pick_publish_date({"foo": "bar"}))  # 无时间字段 → 不伪造
        self.assertIsNone(normalizer.pick_publish_date(None))

    def test_bytedance_map_sets_posted_at(self):
        from adapters.bytedance import BytedanceAdapter
        job = BytedanceAdapter()._map({"id": "1", "title": "算法工程师", "publish_time": 1700000000000})
        self.assertEqual(job.posted_at, "2023-11-14")
        job2 = BytedanceAdapter()._map({"id": "2", "title": "x"})  # 无时间字段 → None
        self.assertIsNone(job2.posted_at)


class AshbyParseTest(unittest.TestCase):
    def test_keeps_china_and_flexible_remote(self):
        payload = json.dumps({"jobs": [
            {"title": "AI Engineer", "location": "Shanghai, China",
             "jobUrl": "https://jobs.ashbyhq.com/notion/abc", "employmentType": "FullTime",
             "publishedAt": "2026-05-01T00:00:00Z", "descriptionPlain": "do stuff", "isListed": True},
            {"title": "Remote PM", "location": "Remote",
             "jobUrl": "https://jobs.ashbyhq.com/notion/rem"},                  # 保留
            {"title": "US SWE", "location": "New York",
             "jobUrl": "https://jobs.ashbyhq.com/notion/us"},                   # 海外 -> 过滤
            {"title": "Hidden", "location": "Beijing", "isListed": False,
             "jobUrl": "https://jobs.ashbyhq.com/notion/hid"},                  # 未挂出 -> 过滤
            {"title": "No Url", "location": "Beijing"},                         # 无 jobUrl -> 过滤
        ]})
        jobs = AshbyAdapter().parse(payload)
        titles = {j.title for j in jobs}
        self.assertEqual(titles, {"AI Engineer", "Remote PM"})
        sh = next(j for j in jobs if j.title == "AI Engineer")
        self.assertEqual(sh.jd_url, "https://jobs.ashbyhq.com/notion/abc")
        self.assertEqual(sh.posted_at, "2026-05-01")
        self.assertEqual(sh.company, "")  # 由 sources.company 兜底

    def test_address_fallback_location(self):
        payload = json.dumps({"jobs": [
            {"title": "Eng", "jobUrl": "https://jobs.ashbyhq.com/x/1",
             "address": {"postalAddress": {"addressLocality": "Beijing", "addressCountry": "China"}}},
        ]})
        jobs = AshbyAdapter().parse(payload)
        self.assertEqual(len(jobs), 1)
        self.assertIn("Beijing", jobs[0].location)

    def test_bad_json(self):
        self.assertEqual(AshbyAdapter().parse("nope"), [])


class SmartRecruitersParseTest(unittest.TestCase):
    def test_keeps_china_builds_stable_url(self):
        payload = json.dumps({"content": [
            {"name": "Data Scientist", "id": "744000",
             "company": {"identifier": "Bosch"},
             "location": {"city": "Shanghai", "country": "China", "remote": False},
             "releasedDate": "2026-05-10T00:00:00.000Z"},
            {"name": "Remote Role", "id": "744001",
             "company": {"identifier": "Bosch"},
             "location": {"remote": True, "country": "China"}},                 # remote 不绑海外 -> 保留
            {"name": "Germany Role", "id": "744002",
             "company": {"identifier": "Bosch"},
             "location": {"city": "Stuttgart", "country": "Germany"}},          # 海外 -> 过滤
            {"name": "No Identifier", "id": "744003",
             "location": {"city": "Beijing", "country": "China"}},              # 无 identifier -> 过滤
        ]})
        jobs = SmartRecruitersAdapter().parse(payload)
        titles = {j.title for j in jobs}
        self.assertEqual(titles, {"Data Scientist", "Remote Role"})
        ds = next(j for j in jobs if j.title == "Data Scientist")
        self.assertEqual(ds.jd_url, "https://jobs.smartrecruiters.com/Bosch/744000")
        self.assertEqual(ds.posted_at, "2026-05-10")
        self.assertEqual(ds.company, "")

    def test_bad_json(self):
        self.assertEqual(SmartRecruitersAdapter().parse("[]"), [])


class SlugifyTest(unittest.TestCase):
    def test_variants(self):
        import probe
        self.assertIn("procterandgamble", probe.slugify("Procter & Gamble"))
        self.assertIn("schneiderelectric", probe.slugify("Schneider Electric"))
        self.assertIn("schneider-electric", probe.slugify("Schneider Electric"))
        # 去公司后缀噪声
        self.assertIn("acme", probe.slugify("Acme Inc"))
        # 纯中文名无拉丁 slug
        self.assertEqual(probe.slugify("字节跳动"), [])

    def test_discover_candidates_only_single_host_ats(self):
        import probe
        cands = probe.build_discover_candidates()
        self.assertTrue(len(cands) > 0)
        self.assertTrue(all(c["adapter"] in probe._DISCOVER_PLATFORMS for c in cands))
        # URL 去重
        self.assertEqual(len({c["url"] for c in cands}), len(cands))


if __name__ == "__main__":
    unittest.main()

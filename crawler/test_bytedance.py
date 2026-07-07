"""字节 httpx 全量抓取单测（mock httpx，不打真实网络）。"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import normalizer
from adapters import bytedance as bt
from adapters.bytedance import BytedanceAdapter, BytedanceCampusAdapter


def _post(pid, *, category_id="cat_a", parent_id=None, city_code="CT_11", city="北京"):
    parent = {"id": parent_id, "name": "研发"} if parent_id else None
    return {
        "id": str(pid),
        "title": f"岗位{pid}",
        "city_list": [{"code": city_code, "name": city}],
        "job_category": {"id": category_id, "name": "后端", "parent": parent},
        "description": "负责系统设计",
        "requirement": "熟悉 Python",
        "recruit_type": {"parent": {"name": "社会招聘"}, "name": "正式"},
        "publish_time": 1782864000000,
    }


class MappingTest(unittest.TestCase):
    def test_social_field_map_uses_list_body_and_experienced_url(self):
        adapter = BytedanceAdapter()

        job = adapter._map(_post("7657467065993218309"))

        self.assertEqual(job.company, "字节跳动")
        self.assertEqual(job.location, "北京")
        self.assertEqual(job.job_type, "社招")
        self.assertIn("负责系统设计", job.summary)
        self.assertIn("熟悉 Python", job.summary)
        self.assertEqual(job.posted_at, "2026-07-01")
        self.assertEqual(
            job.jd_url,
            "https://jobs.bytedance.com/experienced/position/7657467065993218309/detail",
        )
        ok, reason = normalizer.validate_job_quality(
            job, "https://jobs.bytedance.com/experienced/position"
        )
        self.assertTrue(ok, reason)

    def test_campus_intern_field_map_uses_campus_url_and_recruit_type(self):
        adapter = BytedanceCampusAdapter()
        post = _post("7657467065993218310")
        post["recruit_type"] = {"parent": {"name": "校园招聘"}, "name": "暑期实习"}

        job = adapter._map(post)

        self.assertEqual(job.job_type, "暑期实习")
        self.assertEqual(
            job.jd_url,
            "https://jobs.bytedance.com/campus/position/7657467065993218310/detail",
        )

    def test_job_type_falls_back_to_track_not_category_name_when_recruit_type_unknown(self):
        post = _post("7657467065993218311")
        post["recruit_type"] = {"parent": {"name": ""}, "name": "正式"}

        social = BytedanceAdapter()._map(post)
        campus = BytedanceCampusAdapter()._map(post)

        self.assertEqual(social.job_type, "社招")
        self.assertEqual(campus.job_type, "校招")
        self.assertNotEqual(social.job_type, "后端")
        self.assertNotEqual(campus.job_type, "后端")
        self.assertNotEqual(social.job_type, "正式")
        self.assertNotEqual(campus.job_type, "正式")


class TrackPlanningTest(unittest.TestCase):
    def test_reconcile_complete_compares_parent_total_to_covered_counts(self):
        self.assertTrue(bt.reconcile_complete(10, [4, 6]))
        self.assertTrue(bt.reconcile_complete(10, [7, 6]))
        self.assertFalse(bt.reconcile_complete(10, [4, 5]))

    def test_direct_count_under_cap_pages_without_slicing(self):
        calls = []

        def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
            calls.append((rid, offset, limit, category_id, city_code))
            rows = [_post(i) for i in range(offset, min(offset + limit, 5))]
            return bt.BytedancePage(count=5, jobs=rows)

        result = bt.collect_bytedance_track(
            fake_fetch, "1", page_limit=2, max_jobs=20, sample_limit=4
        )

        self.assertEqual([p["id"] for p in result.jobs], ["0", "1", "2", "3", "4"])
        self.assertTrue(result.complete)
        self.assertTrue(all(call[3] is None and call[4] is None for call in calls))

    def test_capped_count_uses_category_then_city_and_dedups_ids(self):
        calls = []

        def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
            calls.append((rid, offset, limit, category_id, city_code))
            key = (category_id, city_code, offset, limit)
            if category_id is None and city_code is None:
                if limit == 1:
                    return bt.BytedancePage(count=4, jobs=[_post("seed", parent_id="cat_a")])
                return bt.BytedancePage(
                    count=4,
                    jobs=[
                        _post("seed-a", parent_id="cat_a"),
                        _post("seed-b", parent_id="cat_b"),
                    ],
                )
            if key == ("cat_a", None, 0, 1):
                return bt.BytedancePage(count=2, jobs=[_post("1", parent_id="cat_a")])
            if key == ("cat_a", None, 0, 2):
                return bt.BytedancePage(
                    count=2, jobs=[_post("1", parent_id="cat_a"), _post("2", parent_id="cat_a")]
                )
            if key == ("cat_b", None, 0, 1):
                return bt.BytedancePage(count=4, jobs=[_post("2", parent_id="cat_b")])
            if key == ("cat_b", None, 0, 2):
                return bt.BytedancePage(
                    count=4,
                    jobs=[
                        _post("2", parent_id="cat_b", city_code="CT_11"),
                        _post("3", parent_id="cat_b", city_code="CT_31", city="上海"),
                    ],
                )
            if key == ("cat_b", "CT_11", 0, 1):
                return bt.BytedancePage(count=2, jobs=[_post("2", parent_id="cat_b")])
            if key == ("cat_b", "CT_11", 0, 2):
                return bt.BytedancePage(
                    count=2, jobs=[_post("2", parent_id="cat_b"), _post("4", parent_id="cat_b")]
                )
            if key == ("cat_b", "CT_31", 0, 1):
                return bt.BytedancePage(
                    count=2,
                    jobs=[_post("3", parent_id="cat_b", city_code="CT_31", city="上海")],
                )
            if key == ("cat_b", "CT_31", 0, 2):
                return bt.BytedancePage(
                    count=2,
                    jobs=[
                        _post("3", parent_id="cat_b", city_code="CT_31", city="上海"),
                        _post("5", parent_id="cat_b", city_code="CT_31", city="上海"),
                    ],
                )
            return bt.BytedancePage(count=0, jobs=[])

        result = bt.collect_bytedance_track(
            fake_fetch, "1", page_limit=2, max_jobs=20, sample_limit=2, count_cap=4
        )

        self.assertEqual([p["id"] for p in result.jobs], ["1", "2", "4", "3", "5"])
        self.assertTrue(result.complete)
        self.assertIn(("1", 0, 1, "cat_b", None), calls)
        self.assertIn(("1", 0, 1, "cat_b", "CT_11"), calls)
        self.assertIn(("1", 0, 1, "cat_b", "CT_31"), calls)

    def test_category_sample_undercoverage_marks_incomplete(self):
        def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
            if category_id is None and city_code is None:
                if limit == 1:
                    return bt.BytedancePage(count=12, jobs=[_post("seed", parent_id="cat_a")])
                return bt.BytedancePage(
                    count=12,
                    jobs=[_post("seed-a1", parent_id="cat_a"), _post("seed-a2", parent_id="cat_a")],
                )
            if category_id == "cat_a" and city_code is None:
                if limit == 1:
                    return bt.BytedancePage(count=8, jobs=[_post("0", parent_id="cat_a")])
                rows = [_post(i, parent_id="cat_a") for i in range(offset, min(offset + limit, 8))]
                return bt.BytedancePage(count=8, jobs=rows)
            return bt.BytedancePage(count=0, jobs=[])

        result = bt.collect_bytedance_track(
            fake_fetch, "1", page_limit=2, max_jobs=20, sample_limit=2, count_cap=10
        )

        self.assertEqual(len(result.jobs), 8)
        self.assertFalse(result.complete)

    def test_city_sample_undercoverage_marks_incomplete(self):
        def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
            if category_id is None and city_code is None:
                if limit == 1:
                    return bt.BytedancePage(count=12, jobs=[_post("seed", parent_id="cat_a")])
                return bt.BytedancePage(
                    count=12,
                    jobs=[_post("seed-a1", parent_id="cat_a"), _post("seed-a2", parent_id="cat_a")],
                )
            if category_id == "cat_a" and city_code is None:
                if limit == 1:
                    return bt.BytedancePage(count=12, jobs=[_post("0", parent_id="cat_a")])
                return bt.BytedancePage(
                    count=12,
                    jobs=[
                        _post("city-seed-1", parent_id="cat_a", city_code="CT_11"),
                        _post("city-seed-2", parent_id="cat_a", city_code="CT_11"),
                    ],
                )
            if category_id == "cat_a" and city_code == "CT_11":
                if limit == 1:
                    return bt.BytedancePage(count=8, jobs=[_post("0", parent_id="cat_a")])
                rows = [_post(i, parent_id="cat_a") for i in range(offset, min(offset + limit, 8))]
                return bt.BytedancePage(count=8, jobs=rows)
            return bt.BytedancePage(count=0, jobs=[])

        result = bt.collect_bytedance_track(
            fake_fetch, "1", page_limit=2, max_jobs=20, sample_limit=2, count_cap=10
        )

        self.assertEqual(len(result.jobs), 8)
        self.assertFalse(result.complete)

    def test_safety_cap_stops_and_marks_incomplete(self):
        def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
            rows = [_post(i) for i in range(offset, min(offset + limit, 5))]
            return bt.BytedancePage(count=5, jobs=rows)

        result = bt.collect_bytedance_track(
            fake_fetch, "1", page_limit=2, max_jobs=3, sample_limit=4
        )

        self.assertEqual([p["id"] for p in result.jobs], ["0", "1", "2"])
        self.assertFalse(result.complete)
        self.assertTrue(result.hit_max_jobs)


class RetryTest(unittest.TestCase):
    def test_405_retries_after_backoff_without_crashing(self):
        adapter = BytedanceAdapter()
        adapter.request_interval_s = 0
        adapter.retry_backoff_s = 0
        adapter.max_retries = 3
        calls = []

        class Resp:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self._payload = payload

            def json(self):
                return self._payload

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(self.status_code)

        class Client:
            def post(self, url, json=None):
                calls.append((url, json))
                if len(calls) == 1:
                    return Resp(405, {})
                return Resp(200, {"data": {"count": 1, "job_post_list": [_post("1")]}})

        page = adapter._request_page(Client(), {"keyword": "", "limit": 1, "offset": 0})

        self.assertEqual(page.count, 1)
        self.assertEqual(len(page.jobs), 1)
        self.assertEqual(len(calls), 2)


class FetchEnvelopeTest(unittest.TestCase):
    def test_fetch_sets_complete_only_when_track_complete(self):
        adapter = BytedanceAdapter()
        rows = [_post("1")]
        result = bt.BytedanceFetchResult(jobs=rows, total=1, complete=True)
        with mock.patch.object(adapter, "_httpx_fetch", return_value=result):
            out = json.loads(adapter.fetch("https://jobs.bytedance.com/experienced/position"))

        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(out["_intercepted"][0]["data"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
